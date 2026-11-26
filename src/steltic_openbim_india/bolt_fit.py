"""Check fully engaged, perpendicular bolt shafts against their finite pierced plates."""
from collections import Counter
from functools import lru_cache
import numpy as np
from shapely.geometry import Point, Polygon


def plate_frame(ring, holes, depth):
    rows=np.asarray(ring,dtype=float)
    point=rows[0]
    x=rows[1]-point
    x/=np.linalg.norm(x)
    centered=rows-point
    z=np.cross(centered,np.roll(centered,-1,axis=0)).sum(axis=0)
    z/=np.linalg.norm(z)
    basis=np.stack((x,np.cross(z,x),z))
    def project(points):
        return ((np.asarray(points)-point)@basis.T)[:,:2]
    return point,basis,Polygon(project(rows),[project(h) for h in holes]),depth


@lru_cache(maxsize=1024)
def centered_shaft(radius):
    return Point(0,0).buffer(radius,quad_segs=24)


def assembly(plates,bolts):
    """Return counts and confirmed plate material penetrations above a 0.05 mm radial tolerance."""
    counts=Counter()
    findings=[]
    for bolt,a,b,d in bolts:
        a,b=np.asarray(a),np.asarray(b)
        for pid,(origin,basis,poly,thickness) in plates:
            start,end=(a-origin)@basis.T,(b-origin)@basis.T
            delta=end-start
            if abs(delta[2]) < .9999*np.linalg.norm(delta):
                continue
            lo,hi=sorted((start[2],end[2]))
            if lo>.05 or hi<thickness-.05:
                continue
            mid=start+delta*((thickness/2-start[2])/delta[2])
            center=Point(*mid[:2])
            rad=d/2
            if Polygon(poly.exterior).distance(center)>=rad:
                continue
            counts["shaft_plate_pairs"]+=1
            # Distance to actual material is the radius of the largest concentric
            # clear circle at this location, including the finite plate boundary.
            clearance=poly.distance(center)-rad
            if clearance<-.05:
                from shapely.affinity import translate
                circle=translate(centered_shaft(rad-.05),*mid[:2])
                area=circle.intersection(poly).area
                if area>.02:
                    findings.append({"bolt":bolt,"plate":pid,"material_penetration_mm":round(-clearance,3),
                                     "cross_section_overlap_mm2":round(area,3)})
                    continue
            counts["clear_pairs"]+=1
    return counts,findings


def from_source(data):
    count=Counter()
    findings=[]
    for c in data.get("connections",[]):
        plates=[(p["id"],plate_frame(p["outline"],p.get("openings",[]),p["thickness_mm"])) for p in c.get("parts",[]) if p["kind"]=="plate"]
        bolts=[(p["id"],p["start"],p["end"],p["diameter_mm"]) for p in c.get("parts",[]) if p["kind"]=="bolt"]
        if not plates or not bolts:
            continue
        measured,issues=assembly(plates,bolts)
        count.update(measured)
        findings.extend(dict(connection=c["id"],**r) for r in issues)
    return {"status":"fail" if findings else "pass","shaft_plate_pairs":count["shaft_plate_pairs"],
            "clear_pairs":count["clear_pairs"],"interferences":findings}
