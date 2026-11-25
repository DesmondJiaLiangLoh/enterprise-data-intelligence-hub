# Data Intelligence Hub — Technical design

Reconstructed from supplied source; not an original approved design.

## Business problem

Enterprise BI teams need to discover, understand and reuse assets before developing new reports. AI for BI targets engineering productivity rather than conversational business analytics.

## Architecture

Flask portal → workflow catalogue and run API → subprocess notebook runner → metadata extraction and documentation artifacts → integrated Metadata Explorer. A separate GCP metadata connector and OAuth integration extend the foundation.

## Workflow 1

Initiative Asset Intelligence: discover Tableau projects and assets for a domain or initiative; produce inventory and activity prioritization outputs. Verify actual ranking coverage before claiming non-owner usage prioritization.

## Workflow 2

Operational Task Asset Intelligence: match request titles and descriptions against Tableau workbooks, data sources and flows. Matching is not automatically evidence of generative AI.

## Workflow 3

Metadata & Lineage Intelligence: cloud or local workbook extraction, optional documentation generation using the retained fourth notebook, ZIP packaging and integrated Metadata Explorer. The current catalogue has three workflows, not four standalone workflows.

## GCP foundation

Read-only project and BigQuery metadata discovery, nested fields, candidate SQL references and offline dbt manifest import. Candidate references are not verified lineage. Unified Tableau-to-BigQuery reconciliation, Dataform and job-history lineage are not established by the supplied implementation notes.

## Execution controls

Run status, logs, downloads and termination controls are present. Notebook execution uses subprocesses; GCP cancellation is cooperative. Identical metadata ZIPs are consolidated for Explorer selection.

## Evidence and status

The archive contains a completed run status with exit code zero and metadata, DOCX and HTML outputs. This is artifact evidence, not independent live-system validation. Tests are present but were not executed in this review.

## Security and roadmap

Local/trusted POC only. Shared deployment needs authentication, authorization, CSRF protection, job isolation, retention and secret management. Semantic retrieval, verified cross-platform lineage and effort estimation remain proposed unless separately evidenced. Measure discovery time, reuse rate and documentation effort against a baseline.