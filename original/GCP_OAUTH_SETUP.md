# Workflow 3 — Corporate Google OAuth (local development)

## Administrator prerequisites

1. Have the GCP Platform team register an **OAuth 2.0 Web application** client, with corporate consent / OAuth application policy approval.
2. Register this exact redirect URI: `http://127.0.0.1:5000/workflow3/gcp/auth/callback`.
3. Approve the requested scope `https://www.googleapis.com/auth/cloud-platform` (the Cloud Platform scope is required for some metadata query-job APIs; strict read-only application operations and least-privilege IAM enforce the boundary). Google Cloud APIs may require additional scopes/permissions depending on resource; expand only with approval.
4. Grant the signed-in identity appropriate metadata-read permissions and BigQuery query-job permissions on an approved billing project. Read-only OAuth scopes do not replace IAM permissions.
5. Configure **environment variables on the Portal host**, never commit real client credentials:

```powershell
$env:GCP_OAUTH_CLIENT_ID="YOUR_APPROVED_WEB_CLIENT_ID"
$env:GCP_OAUTH_CLIENT_SECRET="YOUR_APPROVED_WEB_CLIENT_SECRET"
$env:GCP_OAUTH_REDIRECT_URI="http://127.0.0.1:5000/workflow3/gcp/auth/callback"
$env:GCP_METADATA_BILLING_PROJECT="YOUR_APPROVED_GCP_PROJECT"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000/workflow3/gcp` **inside the same Edge InPrivate / Chrome Incognito window** where Google sign-in will occur. Click **Sign in with Google**, authenticate via corporate SSO, and return automatically. Never open the callback manually.

## Security and limitations

- OAuth authorization-code flow with PKCE S256, random state and 10-minute state expiration.
- Access tokens held **only in server process memory**, keyed by an opaque signed-cookie session identifier. They are never written to JSON, logs, command-line arguments or browser cookies.
- Access tokens expire at Google expiry or one hour, whichever comes first. No refresh token is requested. Reauthentication is required when expired.
- Closing a private browser clears its cookies, but does **not** automatically clear the token in server memory. Tokens expire, are cleared by explicit sign-out, or are lost on Portal restart.
- Intended only for **single-user localhost development**. Do NOT expose Flask development server to a network. A multi-user deployment requires authenticated portal identities, centralized server-side session storage, HTTPS, secure cookies, authorization policies and CSRF protection for all endpoints, including job/results/download APIs.
- The current Portal's other run/download APIs predate OAuth and are not protected by it. Keep Portal bound to `127.0.0.1` until those routes are secured.
- If corporate policy blocks OAuth client/scopes, contact GCP Platform; Incognito does not bypass policy.
- OAuth does not enable missing Dataform or scheduled-query adapters; these remain NOT_CONFIGURED in this foundation.
