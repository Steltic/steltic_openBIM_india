"""Trace actual paper lines for the plates, holes, fasteners and welds on details."""
import math
import numpy as np


def ends(part):
    if part["kind"] == "plate":
        outline = np.asarray(part["outline"], dtype=float)
        normal = np.cross(outline, np.roll(outline,-1,axis=0)).sum(axis=0)
        offset = normal * (part["thickness_mm"] / np.linalg.norm(normal))
        for ring in [outline,*part.get("openings",[])]:
            start = np.asarray(ring)
            yield start, start + offset
        return
    a, b = np.array(part["start"]), np.array(part["end"])
    z = (b-a)/np.linalg.norm(b-a)
    x = np.asarray(part.get("ref_direction",np.cross([0,0,1],z)),dtype=float)
    if np.linalg.norm(x)<1e-7:
        x = np.array([1.,0.,0.])
    x = x - x.dot(z)*z
    x /= np.linalg.norm(x)
    y = np.cross(z,x)
    if part["kind"] == "bolt":
        angles = np.arange(24) * (math.tau/24)
        offsets = (np.outer(np.cos(angles),x) + np.outer(np.sin(angles),y))*part["diameter_mm"]/2
    else:
        offsets = np.array([np.zeros(3), x*part["leg_mm"], y*part["leg_mm"]])
    yield a+offsets, b+offsets


def check_detail(connection, detail, strokes, expect):
    parts = connection.get("parts",[])
    expect(detail["part_ids"] == [p["id"] for p in parts], "drawn part inventory",connection["id"])
    projections = detail.get("projections",[])
    expect({tuple(p["axes"]) for p in projections} == {(0,1),(0,2),(1,2)}, "orthogonal detail projections",detail["sheet"])
    traced = 0
    for part in parts:
        for a,b in ends(part):
            for view in projections:
                axes, k = view["axes"], view["points_per_mm"]
                first = a[:,axes]*k+view["origin_pt"]
                last = b[:,axes]*k+view["origin_pt"]
                for p,q in ((first,np.roll(first,-1,axis=0)),(last,np.roll(last,-1,axis=0)),(first,last)):
                    for u,v in zip(p,q):
                        if math.dist(u,v) > .02:
                            traced += 1
                            expect(strokes.has(u,v),"printed connection part or hole edge",f"{detail['sheet']} / {part['id']}")
    return traced
