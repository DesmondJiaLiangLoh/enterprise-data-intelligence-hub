# Tableau Metadata & Integration Pipeline Portal

## Quick start (Windows PowerShell)

```powershell
cd Data_Intelligence_Hub
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000 in a browser. Python 3.10+ recommended.

## Included workflows
1. Initiative Asset Intelligence
2. Operational Task Asset Intelligence
3. Tableau Metadata Extraction
4. Tableau Metadata Documentation

The original notebooks are retained unmodified in `original_notebooks/`. The runner executes code cells sequentially and injects selected CONFIG values immediately after the original CONFIG declaration. It removes notebook `%pip` lines and runs in a separate Python process. Workflow 4 skips its example CLI/demo cells and calls its `run()` function directly.

## Security and operating guidance
- Intended for **localhost or a trusted, authenticated internal environment only**. No login, CSRF protection, rate limiting, or job queue is included. Do not expose directly to the internet.
- PATs are not saved to JSON; they are passed via subprocess environment variables. Protect the host, process environment and output folders. Logs from original pipelines may contain sensitive metadata.
- Runs are stored in `runs/<run_id>`; outputs and logs can be downloaded from the portal.
- For workflow 4, `input_path` must be a path **on the Python server**; a default bundled metadata ZIP is used if blank.
- Workflow 2 uses the bundled Scrum Excel file. Replace it in `inputs/` to use a newer workbook.
- The original notebooks have not been validated against live Tableau credentials. Test in a non-production environment before broader deployment.
- The backend runs one subprocess per request and has no concurrency controls; add authentication, CSRF, upload validation, job scheduling and isolation before multi-user production deployment.
- The original notebooks' hard-coded CONFIG defaults remain in the original notebooks. Review them before sharing the package.

## Fixes in this package (2026-10-28)
- Workflow 1: `IPython.display` functions are available in the notebook execution namespace.
- Workflow 3: interactive PAT prompts are replaced at execution time with environment-variable validation. PATs are not written to job JSON.
- Workflow 3: blank portal fields no longer overwrite valid notebook defaults; project hierarchy is normalized to a list.
- Workflow 3: local workbook mode no longer requires Tableau PAT credentials.
- Windows PowerShell: commands use the virtual environment interpreter directly, without needing script execution-policy changes.

Extract this ZIP into a NEW folder or back up your old portal first. Do not copy an old `runs` directory into the new package. Create a new `.venv` or reuse your old one only if its interpreter path remains valid.

The project hierarchy for the default workbook is `Demo / Analytics / Retail`.

No live Tableau credentials or end-to-end cloud run were available for testing.


## Workflow 3 → Workflow 4 automatic handoff

Workflow 3 writes extracted files to `runs/<run_id>/outputs/` and, **only after successful or partial-success extraction**, packages those files (including the run manifest) into `inputs/metadata/<workbook_name>.zip`. Unsafe filename characters are replaced with underscores. Re-running the same workbook replaces its latest ZIP; previous run artifacts remain under `runs/`. The ZIP also appears in Workflow 3's downloadable output list.

Workflow 4 loads the workbook selector from `GET /api/metadata-workbooks`. Select the workbook and run; the backend resolves its ZIP automatically. You can leave the optional manual input path empty. A manual path is used only when no workbook is selected.

Use the original metadata extraction notebook, not a notebook-source ZIP, as the data source for Workflow 4. The portal is intended for trusted local use and has not been live-tested against Tableau Cloud.

## Hotfix: Workflow 3 CONFIG initialization (2026-10-28)
The original notebook checks PAT credentials in its imports cell, before its CONFIG cell. The runner now checks the portal mode through `PORTAL_MODE` at that early stage, without referencing `CONFIG` before initialization. The notebook's own CONFIG is still created normally and then updated with portal overrides. This fix was validated by executing the original imports cell in both cloud and local modes; live Tableau execution remains unverified.


## Unified Workflow 3 (2026-11)
Workflow 4 is now an internal documentation stage of Workflow 3. Workflow 3 extracts Tableau metadata, packages a ZIP, then (when `generate_documentation` is checked) calls the retained `original_notebooks/p4.ipynb` documentation engine. The original notebook is kept for compatibility and is not shown as a separate workflow. Metadata Explorer is available only within Workflow 3 at `/workflow3/explorer`. Existing metadata ZIP archives remain selectable.

## Branding and authentication
The application is now **Data Intelligence Hub**. The execution entrypoint is `hub_runner.py`. Existing notebook files, original source-system project paths and workflow IDs are preserved to avoid breaking extraction.

Corporate Google passwords must never be entered into the Portal. Use the approved OAuth client configuration described in `GCP_OAUTH_SETUP.md`. Private browsing is supported for localhost usage, subject to corporate SSO policy.
