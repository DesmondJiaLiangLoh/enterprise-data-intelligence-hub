# Workflow 3 — GCP Metadata Connector (foundation release)

## Implemented
- Separate read-only connector CLI (`gcp_connector.py`) and a Portal entry at `/workflow3/gcp`.
- Corporate ADC authentication through official Google Cloud Python libraries.
- Cloud Resource Manager project search, all projects visible to approved identity.
- BigQuery datasets, tables, view SQL fingerprints, columns and nested fields.
- Conservative backtick-qualified SQL references emitted as **CANDIDATE**, not verified lineage.
- Offline dbt `manifest.json` import (via `dbt_manifests` in CLI configuration).
- Evidence gaps for inaccessible projects/datasets and unconfigured sources.
- JSON ZIP with schema-versioned metadata manifest and seven normalized collections.
- Asynchronous execution and download using existing `/api/runs/<run_id>` endpoint.

## Not implemented yet (do not treat as complete)
- Dataform API adapter, scheduled-query transfer-config adapter, BigQuery job-history lineage, routines, repository autodetection.
- dbt manifest registration through Portal UI (CLI config only).
- Unified graph rendering and Tableau-to-BigQuery reconciliation inside existing Explorer.
- Server-side corporate SSO / user-scoped metadata authorization. **Do not expose this local development Portal as a shared corporate service.**

## Installation
In existing virtual environment: `pip install google-cloud-bigquery google-cloud-resource-manager`
Authenticate with corporate-approved ADC (for example `gcloud auth application-default login` where policy permits). Do not commit ADC files or service-account keys.

Set `GCP_METADATA_BILLING_PROJECT` for the Portal process if a billing/query project is required. The current connector uses metadata listing APIs; it does not submit BigQuery SQL jobs.

Launch `python app.py`, then visit `http://127.0.0.1:5000/workflow3/gcp`.

CLI:
`python gcp_connector.py --config gcp_discovery_config.example.json --output GCP_Metadata_Discovery.zip`

## IAM preflight checklist
- Cloud Resource Manager `resourcemanager.projects.list/get` (project search as authorized).
- BigQuery dataset/table metadata: `bigquery.datasets.get`, `bigquery.tables.list/get`.
- Additional permissions are needed for later job history, Dataform, transfer configurations and Git. Grant only on approval.
- The metadata inventory is bounded by permissions, not guaranteed complete for the corporation.
- View SQL may contain sensitive literals; treat resulting ZIP as restricted corporate information.

## Acceptance tests
`python -m unittest discover -s tests -p 'test_gcp*.py'`

## Operational limits
- No data rows queried; no Dataform workflow triggered; no BigQuery SQL executed.
- All-project enumeration can be slow; run against an appropriately scoped identity and validate policy first.
- Existing Portal's run directory is not encrypted or subject to enterprise retention controls; do not use it for regulated metadata until controls are approved.
