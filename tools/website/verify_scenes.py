"""Independently read the published glTF accessors, coordinates and source binding."""

import argparse
from collections import Counter
import json
from pathlib import Path
import struct

import numpy as np
from steltic_openbim_india.geometry import frame, member_body_ends
from scene import read_handoff


def verify(root, out):
    counts = Counter()
    for case in json.loads((root / "acceptance.json").read_bytes())["cases"]:
        source = read_handoff(root, case)
        for unit in case["native"]:
            data = (out / f"{case['id']}-{unit}.glb").read_bytes()
            magic, version, length, jlen, jtype = struct.unpack_from("<4sIII4s", data)
            assert (magic, version, length, jtype) == (b"glTF", 2, len(data), b"JSON")
            doc = json.loads(data[20 : 20 + jlen])
            blen, kind = struct.unpack_from("<I4s", data, 20 + jlen)
            assert kind == b"BIN\0" and len(data) == 28 + jlen + blen
            assert doc["extras"]["ifc_sha256"] == case["sha256"]["model.ifc"]
            assert (doc["extras"]["case"], doc["extras"]["unit"]) == (case["id"], unit)
            views = doc["bufferViews"]
            access = doc["accessors"]
            meshes = []
            for mesh in doc["meshes"]:
                (prim,) = mesh["primitives"]
                pos = access[prim["attributes"]["POSITION"]]
                face = access[prim["indices"]]
                pv = views[pos["bufferView"]]
                fv = views[face["bufferView"]]
                start = 28 + jlen
                points = np.frombuffer(
                    data, offset=start + pv["byteOffset"], dtype="<f4", count=pos["count"] * 3
                ).reshape(-1, 3)
                idx = np.frombuffer(
                    data,
                    offset=start + fv["byteOffset"],
                    dtype={5123: "<u2", 5125: "<u4"}[face["componentType"]],
                    count=face["count"],
                )
                assert np.isfinite(points).all() and idx.size % 3 == 0 and idx.max() < len(points)
                np.testing.assert_array_equal(points.min(axis=0), pos["min"])
                np.testing.assert_array_equal(points.max(axis=0), pos["max"])
                meshes.append(points * 1000.0)
            rows = {
                r["id"]: r
                for k in ("members", "panels")
                for r in source[k]
                if r.get("unit", "Main") == unit
            }
            products = [doc["nodes"][i] for i in doc["nodes"][0]["children"]]
            assert len(products) == len(rows) and set(rows) == {o["name"] for o in products}
            assert len({o["extras"]["guid"] for o in products}) == len(rows)
            for o in products:
                row = rows[o["name"]]
                m = np.array(o["matrix"]).reshape(4, 4).T
                pos = m[:3, 3] * 1000
                obj = o["extras"]
                points = meshes[o["mesh"]]
                assert (obj["role"], obj["material"]) == (row["role"], row["material"])
                if "profile" in row:
                    a, b = member_body_ends(row)
                    x, y, z = frame(row["start"], row["end"], row.get("ref_direction"))
                    np.testing.assert_allclose(m[:3, :3], np.array([x, y, z]).T, rtol=0, atol=1e-7)
                    np.testing.assert_allclose(pos, a, rtol=0, atol=0.02)
                    # Detailed end cuts can remove the complete nominal end face. Such
                    # objects must remain inside their nominal cutback/sweep extent.
                    low, high = points[:, 2].min(), points[:, 2].max()
                    length = np.linalg.norm(np.subtract(b, a))
                    assert low >= -0.08 and high <= length + 0.08, (
                        case["id"],
                        row["id"],
                        low,
                        high,
                        length,
                    )
                    if not row.get("member_voids"):
                        assert abs(low) < 0.08 and abs(high - length) < 0.08, (
                            case["id"],
                            row["id"],
                            low,
                            high,
                            length,
                        )
                    assert obj["profile"] == row["profile"] and obj.get("end_profile") == row.get(
                        "end_profile"
                    )
                    assert (
                        abs(obj["length_mm"] - np.linalg.norm(np.subtract(row["end"], row["start"])))
                        <= 0.001
                    )
                    counts["members"] += 1
                else:
                    placed = points @ m[:3, :3].T + pos
                    outline = np.array(row["outline"])
                    end = outline + m[:3, 2] * row["thickness_mm"]
                    expected = np.vstack((outline, end))
                    np.testing.assert_allclose(
                        [placed.min(axis=0), placed.max(axis=0)],
                        [expected.min(axis=0), expected.max(axis=0)],
                        rtol=0,
                        atol=0.08,
                        err_msg=case["id"] + "/" + row["id"],
                    )
                    assert obj["openings"] == len(row.get("openings", []))
                    counts["panels"] += 1
            assert doc["extras"]["members"] + doc["extras"]["panels"] == len(rows)
            counts["units"] += 1
        print(case["id"], "verified", flush=True)
    print(dict(counts))
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--scenes", required=True, type=Path)
    a = parser.parse_args()
    verify(a.validation, a.scenes)
