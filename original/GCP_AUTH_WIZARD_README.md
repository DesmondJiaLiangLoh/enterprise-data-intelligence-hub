# Workflow 3 corporate Google authentication wizard

## What changed
- Sign in with Google redirects the **current browser window** to Google/corporate SSO. Open the Portal itself in Edge InPrivate or Chrome Incognito first.
- OAuth callback validates state and PKCE, then redirects to `/workflow3/gcp?auth=connected`.
- Authenticated status optionally displays a verified Google email from an ID token.
- A read-only preflight tests project discovery and dataset listing; connection diagnostics are shown before starting discovery.
- Discovery still requires explicit authorization confirmation and user action, especially because scope is all visible projects.

## Administrator setup required
Create/approve an OAuth 2.0 Web Application client in a corporate-controlled Google Cloud project. Configure redirect URI **exactly** `http://127.0.0.1:5000/workflow3/gcp/auth/callback`, corporate consent policy, and approved `cloud-platform`, `openid`, `userinfo.email` scopes. The Portal cannot access existing Google Console browser cookies or replace OAuth client registration with an email/password.

Set these environment variables **on the host running Flask** before starting it:

```powershell
$env:GCP_OAUTH_CLIENT_ID='APPROVED_CLIENT_ID'
$env:GCP_OAUTH_CLIENT_SECRET='APPROVED_CLIENT_SECRET'
$env:GCP_OAUTH_REDIRECT_URI='http://127.0.0.1:5000/workflow3/gcp/auth/callback'
$env:GCP_METADATA_BILLING_PROJECT='APPROVED_PROJECT_ID'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Never enter Google passwords into the Portal, source files, or a shared chat. Keep the client secret in an approved secret store for shared deployments. The development server binds to localhost only.

## Important limitations
- In-memory OAuth tokens are process-local, not shared across multiple Flask workers. Restart invalidates sessions. Private browsing does **not** erase server-side tokens; use Sign out.
- The preflight tests project discovery and BigQuery dataset listing in the approved query project. It is **not** a comprehensive IAM audit and does not prove that every visible project or Dataform/dbt adapter is accessible.
- Dataform and scheduled-query adapters, plus unified Tableau-to-GCP lineage graph, remain future milestones. The existing connector currently reports them as NOT_CONFIGURED.
- The browser is never given Google API access tokens. Flask cookie is signed and HttpOnly; deploy behind HTTPS, secure cookies, and a proper shared-session store before multi-user hosting.
- OAuth can fail under corporate restrictions even after correct client registration; consult the GCP Platform / identity team.
