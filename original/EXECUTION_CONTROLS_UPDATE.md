# Execution termination and Metadata Explorer source consolidation

## Terminate execution
- Workflow 1/2/3: select the workflow while running and click **Terminate execution**. Confirm the prompt.
- GCP discovery: click **Terminate discovery** on the GCP page while a scan is active.
- API: `POST /api/runs/<run_id>/terminate` returns `terminated` for an active worker.
- The process-based notebook runner uses Windows `taskkill /PID ... /T /F` (or POSIX process-group SIGTERM) to stop the child process tree. Partial output files may remain. Do not use termination as a rollback mechanism.
- GCP discovery runs in a Python thread. Termination requests set a cancellation flag; it stops at the next cancellation checkpoint, but a currently blocked cloud API call may finish first. The run is marked terminated immediately; a late result is not exported if the checkpoint is reached before export. A future version should run GCP discovery in a cancellable subprocess for stronger guarantees.
- Only active workers registered in the current Flask process can be terminated. A run left as `running` after a Flask restart cannot be safely terminated by this API.
- Localhost-only development assumption remains. Shared deployment needs authenticated user authorization and CSRF protection for every execution-control endpoint.

## Explorer source consolidation
- Byte-identical ZIP files discovered in `inputs/metadata` and run output folders are represented by one selection.
- The combined label shows the source workbook, extraction timestamp, archive name, and both origins (`Workflow 3 metadata` and `Run <id>`).
- ZIPs with different content are preserved as separate snapshots, even if workbook name matches.
- Existing source IDs are replaced by a content-based ID, so older bookmarked `?source=` values may select the latest entry instead.
