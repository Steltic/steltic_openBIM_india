"""Local Hub interface with immutable, project-scoped revisions."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import uuid

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import local_guard

app = FastAPI(title="Steltic openBIM India")
local_guard.install(app)
static = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=static), name="static")

DOWNLOADS = {
    "design": {"drawings.pdf", "model.ifc", "drawing_register.json", "certificate.json", "handoff.json"},
    "import": {"original.ifc", "inspection.json"},
    "review": {"review.json"},
    "brief": {"design_brief.txt", "architectural_geometry.json"},
}


def directory(project):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,99}", project) or project.endswith((".", " ")):
        raise HTTPException(400, "Use a project name of up to 100 letters, digits, spaces, dashes, underscores or dots")
    root = Path(os.environ.get("OPENBIM_JOBS", "openbim_jobs")).resolve()
    path = root / project
    if path.resolve().parent != root or path.is_reserved():
        raise HTTPException(400, "Invalid project name")
    return path


@contextmanager
def revision(project):
    base = directory(project)
    base.mkdir(parents=True, exist_ok=True)
    key = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(dir=base, prefix=".work-") as temporary:
        folder = Path(temporary) / "revision"
        folder.mkdir()
        yield key, folder
        folder.rename(base / key)


def load_state(project, key):
    if not re.fullmatch("[0-9a-f]{32}", key):
        raise HTTPException(404, "Unknown revision")
    folder = directory(project) / key
    if not (folder / "state.json").is_file():
        raise HTTPException(404, "Unknown revision")
    return folder, json.loads((folder / "state.json").read_text(encoding="utf-8"))


def save_state(key, folder, kind, label, **values):
    state = dict(id=key, kind=kind, label=label, created=datetime.now(timezone.utc).isoformat(),
                 files=sorted(p.name for p in folder.iterdir() if p.name in DOWNLOADS[kind]), **values)
    (folder / "state.json").write_text(json.dumps(state, allow_nan=False), encoding="utf-8")
    return state


def save_upload(file, target, limit):
    digest, size = sha256(), 0
    with target.open("xb") as handle:
        while chunk := file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"Maximum file size is {limit // (1024 * 1024)} MiB")
            digest.update(chunk)
            handle.write(chunk)
    if not size:
        raise HTTPException(422, "The file is empty")
    return digest.hexdigest()


def worker(module, *args, timeout=1200):
    # Separate the viewer from a native parser or mesher failure in any one import.
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
               if os.name == "nt" else {"start_new_session": True})
    command = [sys.executable, "-m", "steltic_openbim_india" + module, *map(str, args)]
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace", **options) as child:
        try:
            output, errors = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True,
                               timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            child.kill()
            child.communicate()
            raise HTTPException(422, "Processing timed out. Select one storey or group for geometry review.")
    if child.returncode:
        raise HTTPException(422, (errors or output).strip()[-1000:] or "The native worker could not process this file")


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/", include_in_schema=False)
@app.get("/ifc-import", include_in_schema=False)
@app.get("/ifc-export", include_in_schema=False)
def page():
    return FileResponse(static / "index.html")


@app.get("/api/projects/{project}")
def history(project: str):
    rows = [json.loads(state.read_text(encoding="utf-8")) for state in directory(project).glob("[0-9a-f]*/state.json")]
    return sorted(rows, key=lambda row: row["created"], reverse=True)


@app.get("/api/projects/{project}/{key}/files/{name}")
def download(project: str, key: str, name: str):
    folder, state = load_state(project, key)
    if name not in DOWNLOADS[state["kind"]] or name not in state["files"]:
        raise HTTPException(404, "Unknown artifact")
    return FileResponse(folder / name, filename=name)


def issue_design(project, source, label, job_directory=None):
    with revision(project) as (key, folder):
        digest = save_upload(source, folder / "handoff.json", 256 * 1024 * 1024)
        verification = ["--source-root", job_directory] if job_directory is not None else []
        worker("", "deliver", folder / "handoff.json", "--output", folder / "delivery", *verification)
        # The user can request a candidate even when the engineer left an explicit review item.
        for name in DOWNLOADS["design"] - {"handoff.json"}:
            (folder / "delivery" / name).rename(folder / name)
        certificate = json.loads((folder/"certificate.json").read_text(encoding="utf-8"))
        return save_state(key, folder, "design", label, source_sha256=digest,
                          artifact_check=certificate["artifact_status"], engineering=certificate["design_status"])


@app.post("/api/projects/{project}/design")
def design(project: str, file: UploadFile):
    return issue_design(project, file.file, Path(file.filename or "handoff.json").name)


def source_roots():
    return {family: Path(value).resolve() for family in ("HR", "CFS")
            if (value := os.getenv(family + "_JOBS"))}


@app.get("/api/sources")
def sources():
    result = []
    for module, root in source_roots().items():
        for path in sorted(root.glob("*/design/openbim_handoff.json")):
            if path.resolve().is_relative_to(root):
                result.append({"module": module, "job": path.parent.parent.name})
    return result


@app.post("/api/projects/{project}/sources/{module}/{job}")
def import_job(project: str, module: str, job: str):
    root = source_roots().get(module)
    if not root or not job or Path(job).name != job or job in (".", "..") or ":" in job:
        raise HTTPException(404, "Unknown source job")
    path = (root / job / "design" / "openbim_handoff.json").resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "No India handoff in that job")
    evidence = json.loads(path.read_text(encoding="utf-8")).get("source_evidence", {}).get("files", {})
    if not evidence:
        raise HTTPException(422, "The job handoff needs its design-source fingerprints. Run the native India exporter.")
    from .model import verify_source_files
    job_dir = path.parent.parent
    try:
        verify_source_files({"source_evidence": {"files": evidence}}, job_dir)
    except (OSError, ValueError) as error:
        raise HTTPException(409, "The native source revision changed. Export its current handoff.") from error
    with path.open("rb") as source:
        return issue_design(project, source, f"{module} / {job}", job_dir)


@app.post("/api/projects/{project}/import")
def import_ifc(project: str, file: UploadFile):
    with revision(project) as (key, folder):
        digest = save_upload(file.file, folder / "original.ifc", 2 * 1024**3)
        worker(".exchange", "inspect", folder / "original.ifc", folder)
        return save_state(key, folder, "import", Path(file.filename or "original.ifc").name, source_sha256=digest)


class ReviewOptions(BaseModel):
    units: str = "auto"
    scope: str = "all"
    storey: str = "all"
    group: int | str = "all"


class Brief(BaseModel):
    options: ReviewOptions
    module: str
    brief: str = Field(min_length=1, max_length=60000)


def from_import(project, key, kind, options, **extra):
    source, state = load_state(project, key)
    if state["kind"] != "import":
        raise HTTPException(422, "Choose an imported IFC revision")
    with revision(project) as (new_key, folder):
        request = dict(options=options.model_dump(), **extra,
                       source=dict(source_sha256=state["source_sha256"], filename=state["label"], revision=key))
        (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
        worker(".exchange", kind, source / "original.ifc", folder)
        return save_state(new_key, folder, kind, state["label"], source_id=key, source_sha256=state["source_sha256"])


@app.post("/api/projects/{project}/{key}/review")
def review(project: str, key: str, options: ReviewOptions):
    return from_import(project, key, "review", options)


@app.post("/api/projects/{project}/{key}/brief")
def brief(project: str, key: str, request: Brief):
    return from_import(project, key, "brief", request.options, module=request.module, brief=request.brief)
