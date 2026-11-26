"""Create a complete, source-bound delivery in a fresh or empty directory."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .drawings import write_drawings
from .composite import clearances, plate_clashes
from .ifc import write_ifc
from .model import handoff_bytes, load, verify_source_files


def file_digest(file):
    digest = hashlib.sha256()
    with Path(file).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def deliver(handoff, output, *, candidate_only=False, source_root=None):
    """Generate candidates, independently check by default and publish the exact checked bytes."""
    handoff, output = Path(handoff), Path(output)
    data, digest = load(handoff)
    if source_root is not None:
        verify_source_files(data, source_root)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Delivery directory must be new or empty: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".steltic-india-", dir=output.parent) as temporary:
        audit_input=handoff
        if handoff.suffix.lower()==".gz":
            audit_input=Path(temporary)/"handoff.json"
            audit_input.write_bytes(handoff_bytes(handoff))
        stage = Path(temporary) / "delivery"
        stage.mkdir()
        clashes = plate_clashes(data)
        gaps = clearances(data,clashes)
        register = write_drawings(data, digest, stage / "drawings.pdf",gaps,clashes)
        write_ifc(data, digest, stage / "model.ifc",gaps,clashes)
        register["drawings_pdf_sha256"] = file_digest(stage / "drawings.pdf")
        register["model_ifc_sha256"] = file_digest(stage / "model.ifc")
        write_json(stage / "drawing_register.json", register)
        if candidate_only:
            result = {"project_id": data["project"]["id"], "artifact_status": "candidate", "sheets":len(register["sheets"])}
        else:
            from .audit import audit
            result = audit(audit_input, stage)
            write_json(stage / "certificate.json", result)
        # Fail on input replacement even if the caller only asked for rendering.
        current=file_digest(handoff) if handoff.suffix.lower()!=".gz" else hashlib.sha256(handoff_bytes(handoff)).hexdigest()
        if current != digest:
            raise ValueError("Source handoff changed during delivery")
        if source_root is not None:
            verify_source_files(data,source_root)
        if output.exists():
            output.rmdir()
        stage.rename(output)
    return result
