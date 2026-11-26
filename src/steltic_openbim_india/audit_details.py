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
    elif part.get("weld_type") == "cjp":
        half_y = y*part["throat_mm"]/2
        half_x = x*part.get("width_mm",part["throat_mm"])/2
        offsets = np.array([-half_x-half_y, half_x-half_y, half_x+half_y, -half_x+half_y])
    else:
        offsets = np.array([np.zeros(3), x*part["leg_mm"], y*part["leg_mm"]])
    yield a+offsets, b+offsets


def check_detail(connection, detail, strokes, expect, members):
    parts = connection.get("parts",[])
    expect(detail["part_ids"] == [p["id"] for p in parts], "drawn part inventory",connection["id"])
    projections = detail.get("projections",[])
    expect({tuple(p["axes"]) for p in projections} == {(0,1),(0,2),(1,2)}, "orthogonal detail projections",detail["sheet"])
    traced = 0
    if parts:
        for view in projections:
            axes=view['axes'];scale=view['points_per_mm'];origin=np.array(view['origin_pt'])
            limits=view.get('receiver_clip_pt',[])
            expect(len(limits)==4,"receiver projection bounds",detail['sheet'])
            if len(limits)!=4:continue
            for key in connection['members']:
                row=members[key]
                a,b=[np.asarray(p)[axes]*scale+origin for p in (row['start'],row['end'])]
                v=b-a;lo,hi=0.,1.
                # Clip the independently projected workline to the printed viewport.
                for i in (0,1):
                    if abs(v[i])<1e-10:
                        if not limits[i]-.001<=a[i]<=limits[i+2]+.001:hi=-1.
                    else:
                        t,u=sorted(((limits[i]-a[i])/v[i],(limits[i+2]-a[i])/v[i]))
                        lo=max(lo,t);hi=min(hi,u)
                if hi>lo and np.linalg.norm(v)*(hi-lo)>.025:
                    traced+=1
                    expect(strokes.has(a+lo*v,a+hi*v),"printed connected member workline",f"{detail['sheet']} / {key}")
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
