"""Local-only Google OAuth integration for Workflow 3.

Tokens are process-memory only, never in Flask's signed browser cookie or on disk.
This is a single-process development implementation, NOT a shared multi-worker token store.
"""
import os, time, secrets, threading
from flask import Blueprint, session, request, redirect, jsonify
from google.auth.transport.requests import Request as GoogleRequest

bp = Blueprint('gcp_oauth', __name__)
_LOCK = threading.RLock()
_TOKENS = {}  # session ID -> (google credentials, expires-at epoch, email)
_SCOPES = ['https://www.googleapis.com/auth/cloud-platform', 'openid', 'https://www.googleapis.com/auth/userinfo.email']
_TTL = 3600

def configured():
    return bool(os.getenv('GCP_OAUTH_CLIENT_ID') and os.getenv('GCP_OAUTH_CLIENT_SECRET'))

def _callback():
    return os.getenv('GCP_OAUTH_REDIRECT_URI', 'http://127.0.0.1:5000/workflow3/gcp/auth/callback')

def _flow(state=None, verifier=None):
    from google_auth_oauthlib.flow import Flow
    data={'web':{'client_id':os.environ['GCP_OAUTH_CLIENT_ID'],
        'client_secret':os.environ['GCP_OAUTH_CLIENT_SECRET'],
        'auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://oauth2.googleapis.com/token',
        'redirect_uris':[_callback()]}}
    f=Flow.from_client_config(data,scopes=_SCOPES,state=state,code_verifier=verifier,autogenerate_code_verifier=False)
    f.redirect_uri=_callback()
    return f

def _sid():
    if 'gcp_session_id' not in session:
        session['gcp_session_id']=secrets.token_urlsafe(32)
    return session['gcp_session_id']

def credentials():
    sid=session.get('gcp_session_id')
    if not sid:return None
    with _LOCK:
        record=_TOKENS.get(sid)
        if not record:return None
        creds,deadline,email=record
        if time.time() >= deadline or not creds.valid:
            _TOKENS.pop(sid,None)
            return None
        return creds

@bp.get('/api/workflow3/gcp/auth/status')
def status():
    c=credentials()
    sid=session.get('gcp_session_id')
    with _LOCK: rec=_TOKENS.get(sid) if sid else None
    return jsonify(configured=configured(),authenticated=c is not None, email=(rec[2] if c is not None and rec else None), expires_at=(rec[1] if c is not None and rec else None),
        callback_uri=_callback(),authentication_mode='session_only',
        message='Configure GCP_OAUTH_CLIENT_ID and GCP_OAUTH_CLIENT_SECRET on the Portal host.' if not configured() else '')

@bp.get('/workflow3/gcp/auth/login')
def login():
    if not configured():return 'Google OAuth client is not configured by the corporate GCP administrator.',503
    # Do not allow callback/host spoofing: fixed, configured URI and local-only HTTP.
    verifier=secrets.token_urlsafe(64)
    state=secrets.token_urlsafe(32)
    session['gcp_oauth_pending']={'state':state,'verifier':verifier,'created':time.time()}
    session.permanent=False
    f=_flow(state=state,verifier=verifier)
    url,_=f.authorization_url(access_type='online',include_granted_scopes='false',
        code_challenge_method='S256',prompt='select_account')
    return redirect(url)

@bp.get('/workflow3/gcp/auth/callback')
def callback():
    pending=session.pop('gcp_oauth_pending',None)
    if not pending or time.time()-pending['created']>600:
        return 'OAuth session expired or missing. Restart sign-in from Workflow 3.',400
    if not secrets.compare_digest(str(request.args.get('state','')),pending['state']):
        return 'OAuth state mismatch.',400
    if request.args.get('error'):
        return 'Corporate Google sign-in was declined or blocked. Contact your GCP administrator.',403
    code=request.args.get('code')
    if not code:return 'OAuth authorization code missing.',400
    try:
        f=_flow(state=pending['state'],verifier=pending['verifier'])
        f.fetch_token(code=code)
        creds=f.credentials
        # No refresh token is requested or persisted. Use the shorter of token expiry / 1 hour.
        expiry=creds.expiry.timestamp() if creds.expiry else time.time()+_TTL
        email=None
        try:
            from google.oauth2 import id_token
            if creds.id_token:
                claims=id_token.verify_oauth2_token(creds.id_token,GoogleRequest(),os.environ['GCP_OAUTH_CLIENT_ID'])
                if claims.get('email_verified'):
                    email=claims.get('email')
        except Exception:
            pass  # Identity display is optional; Cloud API token is validated by Google.
        with _LOCK:_TOKENS[_sid()]=(creds,min(expiry,time.time()+_TTL),email)
    except Exception:
        return 'Token exchange failed. Check OAuth client configuration, approved scopes, and redirect URI.',400
    response=redirect('/workflow3/gcp?auth=connected')
    response.headers['Cache-Control']='no-store'
    return response

@bp.post('/api/workflow3/gcp/auth/logout')
def logout():
    # Custom header + same-origin JSON fetch prevents cross-site form logout.
    if request.headers.get('X-GCP-Portal-Action')!='signout':return jsonify(error='Invalid request'),403
    origin=request.headers.get('Origin')
    if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):
        return jsonify(error='Origin mismatch'),403
    sid=session.pop('gcp_session_id',None)
    session.pop('gcp_oauth_pending',None)
    with _LOCK:_TOKENS.pop(sid,None)
    return jsonify(authenticated=False)
