"""IFC import, architectural brief export and original-file return.

The Hub invokes this module in a child process for native IFC operations.
"""
from pathlib import Path
import json
import sys

from .ifc_handoff import prepare
from .ifc_import import open_model, metadata, build_review


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")), encoding="utf-8")


def run(action, source, target):
    if action == "inspect":
        report = metadata(open_model(source))
        # The selected objects can be large. The full list is available with the source.
        report.pop("products")
        write_json(target / "inspection.json", report)
        return
    request = json.loads((target / "request.json").read_text(encoding="utf-8"))
    review = build_review(source, request["options"])
    if action == "review":
        write_json(target / "review.json", review)
        return
    if action == "brief":
        geometry, brief = prepare(source, review, request["source"], request["brief"], request["module"])
        write_json(target / "architectural_geometry.json", geometry)
        (target / "design_brief.txt").write_text(brief, encoding="utf-8")
        return
    raise ValueError(f"Unsupported exchange action {action}")


if __name__ == "__main__":
    try:
        run(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        print(str(error)[:1200], file=sys.stderr)
        sys.exit(1)
