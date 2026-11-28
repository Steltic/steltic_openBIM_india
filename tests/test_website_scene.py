import json
from pathlib import Path
import struct
import sys
from zipfile import ZipFile

import numpy as np
import pytest

from steltic_openbim_india.ifc import write_ifc

WEBSITE = Path(__file__).resolve().parents[1] / "tools/website"
sys.path.insert(0, str(WEBSITE))
from scene import digest, export
from stage_pages import validate_route
from verify_scenes import verify


def test_issued_solid_instances_keep_panel_voids_and_source_identity(tmp_path):
    source = json.loads((Path(__file__).parent / "fixtures/metric_frame.json").read_bytes())
    wall = source["panels"][0]
    source["panels"].append(
        dict(wall, id="W2", outline=[[x, y + 1000, z] for x, y, z in wall["outline"]], openings=[])
    )
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps(source), encoding="utf8")
    model = tmp_path / "model.ifc"
    write_ifc(source, digest(handoff), model)
    archive = tmp_path / "delivery.zip"
    with ZipFile(archive, "w") as z:
        z.write(model, "model.ifc")
    case = dict(
        id=source["project"]["id"],
        handoff=handoff.name,
        archive=archive.name,
        archive_sha256=digest(archive),
        native={"Main": "complete"},
        sha256={"model.ifc": digest(model), "handoff.json": digest(handoff)},
    )
    (tmp_path / "acceptance.json").write_text(json.dumps({"cases": [case]}), encoding="utf8")
    export(tmp_path, case, tmp_path)
    assert verify(tmp_path, tmp_path) == {"units": 1, "members": 6, "panels": 2}
    glb = (tmp_path / f"{case['id']}-Main.glb").read_bytes()
    n = struct.unpack_from("<I", glb, 12)[0]
    doc = json.loads(glb[20 : 20 + n])
    bin_offset = 28 + n
    volumes = {}
    for o in doc["nodes"][1:]:
        if o["name"] not in ("W1", "W2"):
            continue
        p = doc["meshes"][o["mesh"]]["primitives"][0]

        def array(index, dtype, count):
            a = doc["accessors"][index]
            view = doc["bufferViews"][a["bufferView"]]
            return np.frombuffer(
                glb, dtype=dtype, count=a["count"] * count, offset=bin_offset + view["byteOffset"]
            )

        positions = array(p["attributes"]["POSITION"], "<f4", 3).reshape(-1, 3).astype(float)
        tri = positions[array(p["indices"], "<u2", 1).reshape(-1, 3)]
        volumes[o["name"]] = abs(np.sum(tri[:, 0] * np.cross(tri[:, 1], tri[:, 2])) / 6)
    assert volumes["W2"] == pytest.approx(6 * 3.8 * 0.004, rel=1e-5)
    assert volumes["W1"] == pytest.approx((6 * 3.8 - 1.2 * 1.95) * 0.004, rel=1e-5)
    case["archive_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        export(tmp_path, case, tmp_path)


def test_route_must_stay_in_published_example():
    route = {
        "id": "IN_Ex1",
        "unit": "Main",
        "native_folder": "HR/IN_Ex1",
        "public_folder": "solutions_india/hr/Example1",
        "report": "solutions_india/hr/Example1/report.html",
        "viewer": "solutions_india/hr/Example1/viewer_3d.html",
    }
    validate_route(route, "HR")
    with pytest.raises(ValueError):
        validate_route(dict(route, public_folder="solutions_india/hr/../Example1"), "HR")
