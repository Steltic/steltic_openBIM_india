"""Validation at the producer/consumer boundary. No structural analysis is run here."""

import hashlib
import gzip
import json
import math
from numbers import Real
from pathlib import Path
from pathlib import PureWindowsPath

from .geometry import frame, plane, project
from .profiles import polygon, positive, section_polygons


def number(v):
    return isinstance(v, Real) and not isinstance(v, bool) and math.isfinite(v)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires a nonempty string")
    return value


def vector(v, name):
    if not isinstance(v, (list, tuple)) or len(v) != 3 or not all(number(t) for t in v):
        raise ValueError(f"{name} requires three finite coordinates")
    return v


def index(rows, subject):
    if not isinstance(rows, list):
        raise ValueError(f"{subject} must be a list")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{subject} records must be objects")
        key = text(row.get("id"), subject + " id")
        if key in result:
            raise ValueError(f"duplicate {subject} id {key}")
        result[key] = row
    return result


def require_ref(row, field, known):
    if row.get(field) not in known:
        raise ValueError(f"{row.get('id', field)}: unknown {field} {row.get(field)!r}")


def ref_list(row, field, known):
    refs = row.get(field, [])
    if not isinstance(refs, list) or any(not isinstance(key, str) or key not in known for key in refs):
        raise ValueError(f"{row['id']}: invalid {field} references")
    if len(set(refs)) != len(refs):
        raise ValueError(f"{row['id']}: repeated {field} reference")


def panel_shape(row):
    outer = row.get("outline", [])
    if not isinstance(outer, list) or len(outer) < 3:
        raise ValueError("panel outline requires at least three points")
    for ring in (outer, *row.get("openings", [])):
        for point in ring:
            vector(point, "panel vertex")
    basis = plane(outer)
    ring = project(outer, basis)
    holes = [project(h, basis) for h in row.get("openings", [])]
    return basis, polygon(ring, holes)


def validate(data):
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise ValueError("expected an India design handoff with schema_version 1.0")
    job = data["project"]
    if job.get("module") not in {"HR", "CFS"} or job.get("units") != "mm":
        raise ValueError("the handoff must specify module HR or CFS and units mm")
    text(job.get("id"), "project id")
    text(job.get("name"), "project name")
    for label, values in (("design_basis", job.get("design_basis", [])), ("assumptions", data.get("assumptions", []))):
        if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError(f"{label} must contain text entries")
    levels = index(data["levels"], "level")
    if not levels or any(not number(r.get("elevation_mm")) for r in levels.values()):
        raise ValueError("supply named storeys with finite elevations")
    for axis in ("x", "y"):
        grid = index(data["grids"][axis], f"{axis} grid")
        if not grid or any(not number(r.get("coordinate_mm")) for r in grid.values()):
            raise ValueError(f"supply finite coordinates for {axis} grids")
        if len({r["coordinate_mm"] for r in grid.values()}) != len(grid):
            raise ValueError(f"duplicate {axis} grid coordinate")
    units = index(data.get("units", []), "unit")
    for key, row in units.items():
        text(row.get("name"), key + " unit name")
        vector(row.get("origin_mm"), key + " unit origin")
        ref_list(row,"levels",levels)
        if "levels" in row and not row["levels"]:
            raise ValueError(f"{key}: declared unit has no levels")
    for key, joint in index(data.get("separation_joints", []), "separation joint").items():
        ref_list(joint, "units", units)
        if len(joint.get("units", [])) != 2 or joint.get("axis") not in ("x","y") or joint.get("direction",1) not in (-1,1):
            raise ValueError(f"{key}: specify two ordered units and an interface axis")
        for field in ("required_gap_mm","declared_gap_mm"):
            if field in joint and (not number(joint[field]) or joint[field] < 0):
                raise ValueError(f"{key}: invalid {field}")
        for field in ("elevation_range_mm","stations_mm"):
            if field in joint:
                interval=joint[field]
                if not isinstance(interval,list) or len(interval)!=2 or not all(number(v) for v in interval) or interval[0]>=interval[1]:
                    raise ValueError(f"{key}: invalid {field}")
    if "design_status" in job and job["design_status"] not in ("pass","fail","review"):
        raise ValueError("invalid project design_status")

    materials, profiles = data["materials"], data["profiles"]
    if not isinstance(materials, dict) or not isinstance(profiles, dict):
        raise ValueError("profiles and materials must be dictionaries by id")
    for name, material in materials.items():
        text(name, "material id")
        text(material.get("grade"), "material grade")
        text(material.get("standard"), "material standard or source")
        if "fy_mpa" in material:
            positive(material["fy_mpa"], "material yield strength")
    shapes = {}
    for name, profile in profiles.items():
        text(name, "profile id")
        if profile.get("family") not in {"I", "C", "Z", "L", "RHS", "CHS", "ROD", "PLATE", "POLYGON"}:
            raise ValueError(f"{name}: unknown section family")
        try:
            shapes[name] = section_polygons(profile)
        except (TypeError, ValueError) as ex:
            raise ValueError(f"{name}: {ex}") from ex
    checks = index(data.get("checks", []), "check")
    for key, row in checks.items():
        text(row.get("description"), f"{key} check description")
        status = row.get("status")
        if status not in {"pass", "fail", "review"}:
            raise ValueError(f"{key}: invalid check status")
        u = row.get("utilization")
        if u is not None and (not number(u) or u < 0 or (status == "pass" and u > 1 + 1e-7)):
            raise ValueError(f"{key}: utilization disagrees with the declared check")
    members = index(data["members"], "member")
    panels = index(data.get("panels", []), "panel")
    connections = index(data.get("connections", []), "connection")
    for category in (members, panels, connections):
        for row in category.values():
            if units:
                require_ref(row,"unit",units)
                declared=units[row["unit"]].get("levels")
                if declared and "level" in row and row["level"] not in declared:
                    raise ValueError(f"{row['id']}: level belongs to another unit")
            elif "unit" in row:
                text(row["unit"],"unit label")
    if not members:
        raise ValueError("handoff has no located members")
    ids = set()
    def unique(key):
        if key in ids:
            raise ValueError(f"ambiguous physical occurrence id {key}")
        ids.add(key)

    for row in members.values():
        unique(row["id"])
        text(row.get("role"), "member role")
        require_ref(row, "profile", profiles)
        require_ref(row, "material", materials)
        ref_list(row, "checks", checks)
        if "level" in row:
            require_ref(row, "level", levels)
        if "end_profile" in row:
            require_ref(row, "end_profile", profiles)
            ends = [shapes[row[k]] for k in ("profile", "end_profile")]
            def topology(parts):
                return [(len(p.exterior.coords), tuple(len(h.coords) for h in p.interiors)) for p in parts]
            if topology(ends[0]) != topology(ends[1]):
                raise ValueError(f"{row['id']}: tapered endpoints have incompatible section topology")
        vector(row.get("start"), "member start")
        vector(row.get("end"), "member end")
        if "ref_direction" in row:
            vector(row["ref_direction"], "section width direction")
        try:
            frame(row["start"], row["end"], row.get("ref_direction"))
        except ValueError as ex:
            raise ValueError(f"{row['id']}: {ex}") from ex
    def validate_panel(row):
        require_ref(row, "material", materials)
        positive(row.get("thickness_mm"), "plate or panel thickness")
        panel_shape(row)
    for row in panels.values():
        unique(row["id"])
        text(row.get("role"), "panel role")
        if "level" in row:
            require_ref(row, "level", levels)
        validate_panel(row)
        ref_list(row, "checks", checks)
    for row in connections.values():
        unique(row["id"])
        text(row.get("type"), "connection type")
        vector(row.get("at"), "connection workpoint")
        ref_list(row, "members", members)
        if not row.get("members"):
            raise ValueError(f"{row['id']}: connection has no receiving member")
        if units and any(members[ref]["unit"]!=row["unit"] for ref in row["members"]):
            raise ValueError(f"{row['id']}: connection crosses separate structural units")
        ref_list(row, "checks", checks)
        if "level" in row:
            require_ref(row, "level", levels)
        for part in index(row.get("parts", []), "connection part").values():
            unique(part["id"])
            require_ref(part, "material", materials)
            if part.get("kind") == "plate":
                validate_panel(part)
            elif part.get("kind") in {"bolt", "weld"}:
                vector(part.get("start"), "part start")
                vector(part.get("end"), "part end")
                if "ref_direction" in part:
                    vector(part["ref_direction"], "part width direction")
                frame(part["start"], part["end"], part.get("ref_direction"))
                key = "diameter_mm" if part["kind"] == "bolt" else "leg_mm"
                positive(part.get(key), key)
            else:
                raise ValueError(f"{part['id']}: unsupported connection part")
    return data


def handoff_bytes(path):
    path=Path(path)
    if path.suffix.lower()==".gz":
        with gzip.open(path,"rb") as stream:
            return stream.read()
    return path.read_bytes()


def load(path):
    raw = handoff_bytes(path)
    try:
        data = validate(json.loads(raw.decode("utf-8-sig")))
    except (KeyError, ValueError, TypeError, AttributeError, IndexError, ArithmeticError) as ex:
        raise ValueError(f"Invalid India handoff: {ex}") from ex
    return data, hashlib.sha256(raw).hexdigest()


def verify_source_files(data, source_root):
    """Re-read the exact native artifacts to which this design handoff is bound."""
    root=Path(source_root).resolve(strict=True)
    evidence=data.get("source_evidence",{}).get("files")
    if not isinstance(evidence,dict) or not evidence:
        raise ValueError("The handoff does not declare native source-file fingerprints")
    verified={}
    for name,expected in evidence.items():
        if not isinstance(name,str) or not isinstance(expected,str) or len(expected)!=64:
            raise ValueError("Invalid native source fingerprint")
        relative=PureWindowsPath(name)
        if relative.drive or relative.root or ".." in relative.parts:
            raise ValueError("Native fingerprints must contain relative project paths")
        file=root.joinpath(*relative.parts).resolve(strict=True)
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError(f"Invalid native source path {name}")
        h=hashlib.sha256()
        with file.open("rb") as stream:
            for block in iter(lambda:stream.read(1024*1024),b""):
                h.update(block)
        if h.hexdigest()!=expected.lower():
            raise ValueError(f"Native source fingerprint mismatch: {name}")
        verified[name]=expected.lower()
    return verified


def unit_levels(data, unit):
    if unit is None:
        return data["levels"]
    if "levels" in unit:
        return [l for l in data["levels"] if l["id"] in unit["levels"]]
    members = [m for m in data["members"] if m.get("unit")==unit["id"]]
    ends = {round(m[end][2],2) for m in members for end in ("start","end")}
    named = {m.get("level") for m in members}
    out = [l for l in data["levels"] if l["id"] in named or round(l["elevation_mm"],2) in ends]
    return out or [min(data["levels"],key=lambda r:abs(r["elevation_mm"]-unit["origin_mm"][2]))]


def at_level(data, row, elevation, levels=None):
    if row.get("level"):
        return row["level"]
    levels = sorted(levels or data["levels"], key=lambda r: r["elevation_mm"])
    occupied = [r for r in levels if r["elevation_mm"] <= elevation + 0.01]
    return (occupied[-1] if occupied else levels[0])["id"]


def design_status(data, gaps=()):
    states={r["status"] for r in [*data.get("checks",[]),*gaps]}
    states.add(data["project"].get("design_status","pass"))
    if "fail" in states:
        return "fail"
    if ("review" in states or not data.get("checks") or not data.get("connections")
            or any(not c.get("parts") for c in data.get("connections",[]))):
        return "review"
    return "pass"
