"""Measure separation on triangulated IFC solids in world millimetres."""
import numpy as np


def clipped_extreme(vertices, triangles, axis, direction, limits, maximum):
    """Extremum of a finite mesh cut by the transverse station/elevation window."""
    lower, upper = vertices.min(axis=0), vertices.max(axis=0)
    if any(upper[i] < a or lower[i] > b for i, a, b in limits):
        return None
    choose = max if maximum else min
    signed = vertices[:, axis] * direction
    target = signed.max() if maximum else signed.min()
    inside = np.ones(len(vertices), dtype=bool)
    for i, a, b in limits:
        inside &= (vertices[:, i] >= a) & (vertices[:, i] <= b)
    if np.any(inside & (signed == target)):
        return target
    best = choose(signed[inside]) if inside.any() else None
    tris = vertices[triangles]
    candidates = np.ones(len(tris), dtype=bool)
    for i, a, b in limits:
        candidates &= (tris[:, :, i].max(axis=1) >= a) & (tris[:, :, i].min(axis=1) <= b)
    for tri in tris[candidates]:
        points = list(tri)
        for coord, low, high in limits:
            for boundary, side in ((low, 1), (high, -1)):
                clipped = []
                if points:
                    a = points[-1]
                    for b in points:
                        da, db = (a[coord]-boundary)*side, (b[coord]-boundary)*side
                        if (da < 0) != (db < 0):
                            clipped.append(a + da/(da-db)*(b-a))
                        if db >= 0:
                            clipped.append(b)
                        a = b
                points = clipped
        if points:
            value = choose(p[axis]*direction for p in points)
            best = value if best is None else choose(best, value)
    return best


def measure(joints, solids, expect):
    records = []
    for joint in joints:
        axis = 0 if joint["axis"] == "x" else 1
        limits = [(i, *joint[k]) for i, k in ((1-axis, "stations_mm"), (2, "elevation_range_mm")) if k in joint]
        faces = []
        for side, unit in enumerate(joint["units"]):
            best, owner = None, None
            for key, vertices, triangles in solids.get(unit, []):
                value = clipped_extreme(vertices, triangles, axis, joint.get("direction", 1), limits, side == 0)
                if value is not None and (best is None or (value > best if side == 0 else value < best)):
                    best, owner = value, key
            faces.append((best, owner))
        a, b = faces
        gap = float(b[0]-a[0]) if a[0] is not None and b[0] is not None else None
        claimed = joint.get("measured_gap_mm")
        expect((gap is None and claimed is None) or (gap is not None and claimed is not None and
               abs(gap-claimed) <= .15), "joint clearance measured on IFC mesh", joint["id"])
        records.append({"id": joint["id"], "ifc_gap_mm": gap, "limiting_occurrences": [a[1], b[1]]})
    return records
