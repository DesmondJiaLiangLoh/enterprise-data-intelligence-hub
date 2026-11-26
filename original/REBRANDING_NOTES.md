# Data Intelligence Hub — naming migration

- Portal display name: **Data Intelligence Hub**
- Workflow 1: **Initiative Asset Intelligence**
- Workflow 2: **Operational Task Asset Intelligence**
- Workflow 3: **Metadata & Lineage Intelligence**
- Backend notebook execution module: `hub_runner.py` (previously `runner.py`)
- Flask entrypoint remains `app.py` to preserve existing startup commands.
- Workflow IDs `p1`, `p2`, `p3`, GCP OAuth routes, and original notebooks are preserved for compatibility.
- Source-system project hierarchy containing `CDM` remains an actual Tableau project path, not Portal terminology. Change it only if your Tableau project is different.
- Google email/password direct collection is intentionally NOT implemented. Corporate Google sign-in uses the approved OAuth 2.0 client.
- On Windows, install in a fresh `Data_Intelligence_Hub` folder, or back up the old folder and migrate your local inputs/runs deliberately.
