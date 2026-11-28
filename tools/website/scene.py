"""Build a Z-up inspection scene from the issued IFC solids, packaged as a Y-up glTF.

All source members and envelope panels are represented. Shared IFC bodies and
equal host-local cuts are triangulated once; occurrence transforms and IDs stay
separate. Fabrication hardware is available in the linked full IFC download.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import uuid
import zipfile

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement as placement
import numpy as np


def digest(path):
    with path.open("rb") as stream:
        sha = hashlib.sha256()
        for block in iter(lambda: stream.read(1 << 20), b""):
            sha.update(block)
        return sha.hexdigest()


def read_handoff(root, case):
    path = root / case["handoff"]
    raw = gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")
    with raw:
        content = raw.read()
    if hashlib.sha256(content).hexdigest() != case["sha256"]["handoff.json"]:
        raise ValueError(f"Handoff digest mismatch for {case['id']}")
    return json.loads(content)


def layer(row, panel):
    if panel:
        return "Panels"
    role = row["role"].casefold()
    if any(word in role for word in ("brace", "bracing", "stay", "tie", "strap")):
        return "Bracing"
    if any(
        word in role
        for word in ("stud", "joist", "track", "purlin", "girt", "bridging", "blocking", "batten")
    ):
        return "Secondary steel"
    if any(word in role for word in ("column", "post", "stanchion", "jamb", "stilt")):
        return "Columns"
    return "Other framing"


def body(product):
    return next(
        rep for rep in product.Representation.Representations if rep.RepresentationIdentifier == "Body"
    )


def geometry_key(product):
    """Compare underlying body items and each void in its host's coordinates."""
    openings = []
    for relation in product.HasOpenings:
        void = relation.RelatedOpeningElement
        vp = void.ObjectPlacement
        if vp == product.ObjectPlacement:
            transform = ()
        elif vp.PlacementRelTo == product.ObjectPlacement:
            transform = tuple(placement.get_axis2placement(vp.RelativePlacement).ravel().round(9))
        else:
            return ("unique", product.id())
        openings.append((tuple(item.id() for item in body(void).Items), transform))
    return tuple(item.id() for item in body(product).Items), tuple(sorted(openings))


def geometry(model, representatives):
    settings = ifcopenshell.geom.settings()
    settings.set("mesher-linear-deflection", 0.001)
    settings.set("use-world-coords", False)
    iterator = ifcopenshell.geom.iterator(settings, model, 2, include=representatives)
    result = {}
    if iterator.initialize():
        while True:
            shape = iterator.get()
            points = np.array(shape.geometry.verts, dtype="<f4").reshape((-1, 3))
            faces = np.array(shape.geometry.faces, dtype=np.int64)
            if (
                not len(points)
                or not len(faces)
                or len(faces) % 3
                or not np.isfinite(points).all()
                or faces.min() < 0
                or faces.max() >= len(points)
            ):
                raise ValueError(f"Invalid IFC triangulation for #{shape.id}")
            indices = faces.astype("<u2" if len(points) <= 65535 else "<u4")
            result[shape.id] = points, indices
            if not iterator.next():
                break
    missing = [p.Name for p in representatives if p.id() not in result]
    if missing:
        raise ValueError(f"IFC solids could not be triangulated: {missing[:8]}")
    return result


class Glb:
    def __init__(self, extras):
        # The IFC placements and mesh axes are natively Z-up. Standard glTF
        # applications apply this scene root to get their required Y-up system.
        self.doc = {
            "asset": {"version": "2.0", "generator": "Steltic openBIM India"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [
                {
                    "name": "IFC Z up",
                    "matrix": [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1],
                    "children": [],
                }
            ],
            "meshes": [],
            "buffers": [],
            "bufferViews": [],
            "accessors": [],
            "extras": extras,
        }
        self.binary = bytearray()

    def accessor(self, values, positions):
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        view = {
            "buffer": 0,
            "byteOffset": len(self.binary),
            "byteLength": values.nbytes,
            "target": 34962 if positions else 34963,
        }
        self.binary.extend(values.tobytes())
        accessor = {
            "bufferView": len(self.doc["bufferViews"]),
            "count": len(values),
            "componentType": 5126 if positions else 5123 if values.itemsize == 2 else 5125,
            "type": "VEC3" if positions else "SCALAR",
        }
        if positions:
            accessor.update(min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist())
        self.doc["bufferViews"].append(view)
        self.doc["accessors"].append(accessor)
        return len(self.doc["accessors"]) - 1

    def add_mesh(self, arrays):
        points, indices = arrays
        self.doc["meshes"].append(
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": self.accessor(points, True)},
                        "indices": self.accessor(indices, False),
                    }
                ]
            }
        )
        return len(self.doc["meshes"]) - 1

    def add_node(self, row, mesh, matrix, panel, guid):
        details = {
            "role": row["role"],
            "layer": layer(row, panel),
            "material": row["material"],
            "level": row.get("level", ""),
            "guid": guid,
            "checks": row.get("checks", []),
        }
        if panel:
            details.update(thickness_mm=row["thickness_mm"], openings=len(row.get("openings", [])))
        else:
            details.update(
                profile=row["profile"],
                length_mm=round(float(np.linalg.norm(np.subtract(row["end"], row["start"]))), 3),
            )
            if "end_profile" in row:
                details["end_profile"] = row["end_profile"]
            if row.get("member_voids"):
                details["openings"] = len(row["member_voids"])
            if row.get("end_cutbacks_mm"):
                details["end_cutbacks_mm"] = row["end_cutbacks_mm"]
        self.doc["nodes"][0]["children"].append(len(self.doc["nodes"]))
        self.doc["nodes"].append({"name": row["id"], "mesh": mesh, "matrix": matrix, "extras": details})

    def write(self, target):
        self.doc["buffers"] = [{"byteLength": len(self.binary)}]
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        header = json.dumps(self.doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf8"
        )
        header += b" " * (-len(header) % 4)
        scratch = target.with_suffix(".pending")
        with scratch.open("wb") as stream:
            stream.write(struct.pack("<4sII", b"glTF", 2, 28 + len(header) + len(self.binary)))
            stream.write(struct.pack("<I4s", len(header), b"JSON") + header)
            stream.write(struct.pack("<I4s", len(self.binary), b"BIN\0"))
            stream.write(self.binary)
        scratch.replace(target)


def export(root, case, out):
    handoff = read_handoff(root, case)
    archive = root / case["archive"]
    if digest(archive) != case["archive_sha256"]:
        raise ValueError(f"Issued archive digest mismatch for {case['id']}")
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory() as scratch:
        model_path = Path(scratch) / "model.ifc"
        with z.open("model.ifc") as source, model_path.open("wb") as target:
            shutil.copyfileobj(source, target)
        if digest(model_path) != case["sha256"]["model.ifc"]:
            raise ValueError("Issued IFC digest mismatch")
        model = ifcopenshell.open(str(model_path))
        records = defaultdict(list)
        representatives = {}
        parents = {}
        for listname in ("members", "panels"):
            for row in handoff.get(listname, []):
                name = "steltic:india:" + handoff["project"]["id"] + ":product:" + row["id"]
                guid = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, name).hex)
                item = model.by_guid(guid)
                if (item.Name, item.ObjectType) != (row["id"], row["role"]):
                    raise ValueError(f"Issued product differs from its source: {row['id']}")
                key = geometry_key(item)
                rep = representatives.setdefault(key, item)
                obj = item.ObjectPlacement
                parent = obj.PlacementRelTo
                if parent.id() not in parents:
                    parents[parent.id()] = placement.get_local_placement(parent)
                affine = parents[parent.id()] @ placement.get_axis2placement(obj.RelativePlacement)
                affine[:3, 3] *= 0.001  # All certified India exchange files declare millimetres.
                records[row.get("unit", "Main")].append(
                    (row, listname == "panels", guid, rep.id(), affine.T.ravel().round(9).tolist())
                )
        if set(records) != set(case["native"]):
            raise ValueError("Source units differ from the publication index")
        shapes = geometry(model, list(representatives.values()))
        for unit, rows in records.items():
            checks = {k for row, *_ in rows for k in row.get("checks", [])}
            glb = Glb(
                {
                    "case": case["id"],
                    "unit": unit,
                    "ifc_sha256": case["sha256"]["model.ifc"],
                    "members": sum(not r[1] for r in rows),
                    "panels": sum(r[1] for r in rows),
                    "checks": {c["id"]: c for c in handoff["checks"] if c["id"] in checks},
                }
            )
            indices = {}
            for row, panel, guid, rep_id, matrix in rows:
                if rep_id not in indices:
                    indices[rep_id] = glb.add_mesh(shapes[rep_id])
                glb.add_node(row, indices[rep_id], matrix, panel, guid)
            target = out / f"{case['id']}-{unit}.glb"
            glb.write(target)
            print(
                f"{target.name}: {len(rows):,} products, {len(indices):,} distinct solids, {target.stat().st_size:,} bytes",
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", action="append", help="Defaults to all cases")
    args = parser.parse_args()
    cases = json.loads((args.validation / "acceptance.json").read_text("utf8"))["cases"]
    args.out.mkdir(exist_ok=True, parents=True)
    for case in cases:
        if not args.case or case["id"] in args.case:
            export(args.validation, case, args.out)
