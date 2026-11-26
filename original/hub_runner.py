"""Data Intelligence Hub notebook runner (p1, p2, p3).

Run via: .venv\\Scripts\\python.exe hub_runner.py <path-to-job.json>
Credentials are inherited from the portal process environment, not stored here.
"""
import ast
import json
import os
import re
import sys
import traceback
import zipfile
import shutil
from pathlib import Path

import nbformat
from IPython.display import HTML, Markdown, display

ROOT = Path(__file__).resolve().parent
NOTEBOOKS = ROOT / "original_notebooks"


def clean_cell(source):
    """Remove notebook-only shell/magic lines before Python compilation."""
    return "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith(("%", "!"))
    )


def inject_config(source, overrides):
    """Apply nonempty portal overrides immediately after a top-level CONFIG assignment."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "CONFIG" for t in targets):
                lines = source.splitlines(keepends=True)
                offset = node.end_lineno
                lines.insert(offset, "\nCONFIG.update(" + repr(overrides) + ")\n")
                return "".join(lines)
    return source


def replace_interactive_pat_prompt(source):
    """Prevent Workflow 3's original notebook from requesting stdin credentials."""
    marker = 'Enter your Tableau Personal Access Token name:'
    if marker not in source:
        return source
    start_marker = 'os.environ["TABLEAU_PAT_NAME"] = input('
    end_marker = 'print("Tableau PAT credentials are set for this notebook session.")'
    start = source.find(start_marker)
    end = source.find(end_marker, start)
    if start < 0 or end < 0:
        raise RuntimeError("Unexpected Workflow 3 PAT prompt format; refusing interactive execution")
    end += len(end_marker)
    replacement = (
        'if str(PORTAL_MODE).lower() != "local":\n'
        '    if not os.environ.get("TABLEAU_PAT_NAME", "").strip() or not os.environ.get("TABLEAU_PAT_SECRET", ""):\n'
        '        raise RuntimeError("Missing Tableau PAT credentials. Enter them in the portal.")\n'
        '    print("Tableau PAT credentials loaded from portal environment.")\n'
    )
    return source[:start] + replacement + source[end:]


def workbook_slug(value):
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(value or "")).strip(" ._")
    name = re.sub(r"\s+", "_", name)
    return name[:110] or "Unnamed_Workbook"


def package_metadata(output_dir, workbook_name, job_path):
    """Publish a complete extraction snapshot atomically for Workflow 4."""
    output_dir = Path(output_dir).resolve()
    files = [p for p in output_dir.rglob("*") if p.is_file() and p.suffix.lower() != ".zip"]
    if not files:
        raise RuntimeError("Workflow 3 produced no metadata files; ZIP not published")
    manifest_path = output_dir / "tableau_metadata_run_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Workflow 3 manifest missing; refusing to publish incomplete extraction")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in {"SUCCESS", "PARTIAL_SUCCESS"}:
        raise RuntimeError("Extraction did not complete successfully; ZIP not published")
    resolved_name = (manifest.get("selected_workbook") or {})
    if isinstance(resolved_name, dict):
        resolved_name = resolved_name.get("name") or manifest.get("workbook_name_requested")
    else:
        resolved_name = manifest.get("workbook_name_requested") or workbook_name
    resolved_name = resolved_name or workbook_name
    slug = workbook_slug(resolved_name)
    input_dir = ROOT / "inputs" / "metadata"
    input_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / (slug + ".zip")
    temporary = input_dir / (slug + ".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                archive.write(path, arcname=path.relative_to(output_dir).as_posix())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Generated metadata ZIP failed integrity check")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    # A copy inside the run's outputs makes the archive downloadable in the portal.
    shutil.copy2(target, output_dir / target.name)
    print(f"METADATA ZIP: {target}", flush=True)
    print(f"WORKBOOK NAME: {resolved_name}", flush=True)


def run(job_path):
    job_path = Path(job_path).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    key = job.get("pipeline")
    if key not in {"p1", "p2", "p3"}:
        raise ValueError("Unknown pipeline")
    notebook_path = NOTEBOOKS / (key + ".ipynb")
    notebook = nbformat.read(str(notebook_path), as_version=4)
    overrides = {
        k: v for k, v in (job.get("parameters") or {}).items()
        if v is not None and v != "" and v != []
    }
    if key == "p3" and isinstance(overrides.get("project_path"), str):
        overrides["project_path"] = [
            x.strip() for x in overrides["project_path"].split("/") if x.strip()
        ]
    # Mode must be available before the notebook defines CONFIG (imports cell).
    portal_mode = overrides.get("mode", "cloud")
    # Support common Jupyter notebook globals in a plain Python exec context.
    env = {
        "__name__": "__main__",
        "__file__": str(notebook_path),
        "Path": Path,
        "PORTAL_MODE": portal_mode,
        "display": display,
        "HTML": HTML,
        "Markdown": Markdown,
    }
    for index, cell in enumerate(notebook.cells, start=1):
        if cell.cell_type != "code":
            continue
        source = clean_cell(cell.source)
        if not source.strip():
            continue
        # Workflow 4: the notebook includes demonstration cells that reference
        # HKSE.zip/results. Execute its definitions, then call run() explicitly.
        if key == "p4" and index >= 6:
            continue
        try:
            if key == "p3":
                source = replace_interactive_pat_prompt(source)
            source = inject_config(source, overrides)
            exec(compile(source, f"{key}_cell_{index}.py", "exec"), env)
        except Exception as exc:
            print(f"FAILED at notebook cell {index}: {type(exc).__name__}: {exc}", flush=True)
            raise
    if key == "p3":
        package_metadata(overrides.get("output_dir"), overrides.get("workbook_name"), job_path)
        if overrides.get("generate_documentation", True):
            metadata_dir = ROOT / "inputs" / "metadata"
            output_dir = Path(overrides["output_dir"])
            archives = sorted((p for p in output_dir.glob("*.zip") if p.is_file()), key=lambda p:p.stat().st_mtime, reverse=True)
            if not archives:
                raise RuntimeError("Workflow 3 extraction completed but no metadata archive is available for documentation")
            run_documentation(archives[0], output_dir / "documentation")


def run_documentation(input_path, output_dir):
    """Reuse original Workflow 4 DOCX generator as an internal stage of Workflow 3."""
    notebook_path = NOTEBOOKS / "p4.ipynb"
    notebook = nbformat.read(str(notebook_path), as_version=4)
    env = {"__name__": "__portal_notebook__", "__file__": str(notebook_path), "Path": Path,
           "display": display, "HTML": HTML, "Markdown": Markdown}
    for index, cell in enumerate(notebook.cells, start=1):
        if cell.cell_type != "code" or index >= 6:
            continue
        source = clean_cell(cell.source)
        if source.strip():
            exec(compile(source, f"documentation_cell_{index}.py", "exec"), env)
    if not callable(env.get("run")):
        raise RuntimeError("Internal documentation engine has no run() function")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = env["run"](Path(input_path), output_dir)
    print("DOCUMENTATION OUTPUT:", result, flush=True)




if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise SystemExit("Usage: python hub_runner.py <job.json>")
        run(sys.argv[1])
    except Exception:
        traceback.print_exc()
        sys.exit(1)
