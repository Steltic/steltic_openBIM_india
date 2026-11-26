"""Unit set-outs and conservative separation between the outer physical faces."""

import math

from shapely.geometry import Polygon, box
from shapely.strtree import STRtree

from .geometry import dot, frame, member_body_ends, plane, project, sub
from .profiles import section_polygons


def transformed(ring, origin, x, y):
    return [[origin[i]+u*x[i]+v*y[i] for i in range(3)] for u,v in ring]


def faces_between(start, end):
    yield start
    yield end
    for i in range(len(start)):
        j=(i+1) % len(start)
        yield [start[i],start[j],end[j],end[i]]


def member_faces(row, shapes):
    a,b = member_body_ends(row)
    x,y,_ = frame(a,b,row.get("ref_direction"))
    for p,q in zip(shapes[row["profile"]],shapes[row.get("end_profile",row["profile"])]):
        start=transformed(list(p.exterior.coords)[:-1],a,x,y)
        end=transformed(list(q.exterior.coords)[:-1],b,x,y)
        yield from faces_between(start,end)


def plate_faces(row):
    ring=row["outline"]
    normal=plane(ring)[3]
    end=[[p[i]+normal[i]*row["thickness_mm"] for i in range(3)] for p in ring]
    yield from faces_between(ring,end)


def clipped(vertices, coordinate, boundary, sign):
    result=[]
    if not vertices:
        return result
    a=vertices[-1]
    for b in vertices:
        da,db=(a[coordinate]-boundary)*sign,(b[coordinate]-boundary)*sign
        if (da<0) != (db<0):
            t=da/(da-db)
            result.append([a[i]+(b[i]-a[i])*t for i in range(3)])
        if db>=0:
            result.append(b)
        a=b
    return result


def unit_geometry(data,uid,shapes):
    for m in data["members"]:
        if m.get("unit")==uid:
            yield m["id"], member_faces(m,shapes)
    for p in data.get("panels",[]):
        if p.get("unit")==uid:
            yield p["id"], plate_faces(p)
    for c in data.get("connections",[]):
        if c.get("unit")!=uid:
            continue
        for p in c.get("parts",[]):
            if p["kind"]=="plate":
                yield p["id"],plate_faces(p)
            else:
                x,y,_=frame(p["start"],p["end"],p.get("ref_direction"))
                if p["kind"]=="bolt":
                    r=p["diameter_mm"]/2
                    coords=[(r*math.cos(i*math.tau/96),r*math.sin(i*math.tau/96)) for i in range(96)]
                else:
                    size=p["leg_mm"]
                    coords=[(0.,0.),(size,0.),(0.,size)]
                yield p["id"],faces_between(transformed(coords,p["start"],x,y),transformed(coords,p["end"],x,y))


def plate_clashes(data):
    """Positive common volume of parallel, extruded plates in different units.

    A bounding box narrows the search; the result uses both actual polygon
    boundaries, their holes and the finite overlap of their extrusion intervals.
    """
    if len(data.get("units",[]))<2:
        return []
    rows=[]
    for p in data.get("panels",[]):
        rows.append((p["unit"],p))
    for c in data.get("connections",[]):
        rows.extend((c["unit"],p) for p in c.get("parts",[]) if p["kind"]=="plate")
    records=[]; envelopes=[]
    for uid,p in rows:
        basis=plane(p["outline"]); origin,x,y,z=basis
        shape=Polygon(project(p["outline"],basis),[project(r,basis) for r in p.get("openings",[])])
        top=[[v[i]+p["thickness_mm"]*z[i] for i in range(3)] for v in p["outline"]]
        points=p["outline"]+top
        ext=[(min(v[i] for v in points),max(v[i] for v in points)) for i in range(3)]
        records.append((uid,p,basis,shape,ext))
        envelopes.append(box(ext[0][0],ext[1][0],ext[0][1],ext[1][1]))
    tree=STRtree(envelopes)
    findings=[]
    for i,(uid,p,basis,shape,ext) in enumerate(records):
        origin,x,y,z=basis
        for j in tree.query(envelopes[i]):
            if j<=i:
                continue
            other,q,qbasis,_,qext=records[j]
            if uid==other or min(ext[2][1],qext[2][1])-max(ext[2][0],qext[2][0])<=1e-7:
                continue
            cos=dot(z,qbasis[3])
            if abs(cos)<1-1e-9:
                continue
            qa=dot(sub(qbasis[0],origin),z); qb=qa+cos*q["thickness_mm"]
            depth=min(p["thickness_mm"],max(qa,qb))-max(0,min(qa,qb))
            if depth<=1e-7:
                continue
            def align(ring):
                return [(dot(sub(v,origin),x),dot(sub(v,origin),y)) for v in ring]
            qshape=Polygon(align(q["outline"]),[align(r) for r in q.get("openings",[])])
            area=shape.intersection(qshape).area
            if area*depth>1:
                findings.append(dict(units=[uid,other],occurrences=[p["id"],q["id"]],overlap_area_mm2=area,
                                     overlap_depth_mm=depth,overlap_volume_mm3=area*depth,status="fail"))
    return findings


def clearances(data, clashes=()):
    joints=data.get("separation_joints",[])
    if not joints:
        return []
    shapes={name:section_polygons(p) for name,p in data["profiles"].items()}
    records=[]
    for joint in joints:
        axis=0 if joint["axis"]=="x" else 1
        direction=joint.get("direction",1)
        limits=[]
        for coord,key in ((1-axis,"stations_mm"),(2,"elevation_range_mm")):
            if key in joint:
                low,high=joint[key]
                limits.extend([(coord,low,1),(coord,high,-1)])
        extreme=[]
        for side,uid in enumerate(joint["units"]):
            best=None; owner=None
            for mid,faces in unit_geometry(data,uid,shapes):
                for face in faces:
                    for args in limits:
                        face=clipped(face,*args)
                    if not face:
                        continue
                    values=[direction*p[axis] for p in face]
                    value=min(values) if side else max(values)
                    if best is None or (value<best if side else value>best):
                        best=value; owner=mid
            extreme.append((best,owner))
        a,b=extreme
        measured=b[0]-a[0] if a[0] is not None and b[0] is not None else None
        required=joint.get("required_gap_mm")
        status="review" if measured is None or required is None else ("pass" if measured+.02>=required else "fail")
        if joint.get("declared_basis")=="clear" and measured is not None and joint.get("declared_gap_mm") is not None and abs(measured-joint["declared_gap_mm"])>.02:
            status="fail" if measured<joint["declared_gap_mm"] else ("review" if status=="pass" else status)
        collisions=[r["occurrences"] for r in clashes if set(r["units"])==set(joint["units"])]
        if collisions:
            status="fail"
        records.append(dict(joint,measured_gap_mm=measured,limiting_occurrences=[a[1],b[1]],status=status,plate_clash_pairs=collisions,
                            basis="Signed distance between outermost material planes in the declared direction and comparison window."))
    return records
