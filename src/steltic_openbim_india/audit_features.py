"""Check drilled and slotted steel against the reopened IFC occurrence mesh."""
import ifcopenshell.geom
import ifcopenshell.util.placement as placement
import numpy as np
from shapely.geometry import Polygon


def mesh(settings,entity):
    shape=ifcopenshell.geom.create_shape(settings,entity)
    geometry=getattr(shape,"geometry",shape)
    vertices=np.asarray(geometry.verts).reshape(-1,3)*1000.
    return vertices,np.asarray(geometry.faces).reshape(-1,3)


def stock_length(triangles,p,q):
    """Lengths inside closed triangulated material along a finite drill line."""
    length=float(np.linalg.norm(q-p))
    direction=(q-p)/length
    a=triangles[:,0]
    u,v=triangles[:,1]-a,triangles[:,2]-a
    h=np.cross(direction,v)
    det=(u*h).sum(axis=1)
    valid=np.abs(det)>1e-8
    inv=np.divide(1.,det,out=np.zeros_like(det),where=valid)
    offset=p-a
    s=(offset*h).sum(axis=1)*inv
    r=np.cross(offset,u)
    t=(r*direction).sum(axis=1)*inv
    distances=(r*v).sum(axis=1)*inv
    hits=np.unique(distances[valid & (s>=-1e-8) & (t>=-1e-8) & (s+t<=1+1e-8)].round(5))
    return sum(max(0.,min(length,b)-max(0.,a)) for a,b in zip(hits[::2],hits[1::2]))


def check(row,obj,body,settings,matrix,expect,cache):
    local_to_world=matrix(obj.ObjectPlacement)
    to_host=np.linalg.inv(local_to_world)
    def xyz(mat,p):
        return (mat @ [*p,1.])[:3]
    relations=obj.HasOpenings
    openings={r.RelatedOpeningElement.Name:r.RelatedOpeningElement for r in relations}
    declared=row.get("member_voids",[])
    expect(len(openings)==len(relations)==len(declared),"member opening inventory",row["id"])
    if not declared:
        return
    samples=[]
    signature=[]
    for feature in declared:
        key=f"{row['id']}/void/{feature['id']}"
        op=openings.get(key)
        if op is None:
            expect(False,"missing member opening",key)
            continue
        expect(op.ObjectType==feature["kind"] and op.Description==feature.get("connection"),"member void and joint identity",key)
        cut=op.Representation.Representations[0].Items[0]
        mat=matrix(op.ObjectPlacement) @ placement.get_axis2placement(cut.Position)
        rel=to_host @ mat
        z=np.asarray(cut.ExtrudedDirection.DirectionRatios)*cut.Depth
        signature.append((cut.id(),tuple(rel.round(5).flat)))
        if feature["kind"]=="bore":
            fit=(cut.SweptArea.is_a("IfcCircleProfileDef") and abs(2*cut.SweptArea.Radius-feature["diameter_mm"])<.02)
            expect(fit and np.max(np.abs(mat[:3,3]-feature["start"]))<.02 and
                   np.max(np.abs(xyz(mat,z)-feature["end"]))<.02,"member bore size and position",key)
            xy=[(0.,0.)]
        else:
            shell=Polygon([pt.Coordinates for pt in cut.SweptArea.OuterCurve.Points],
                          [[pt.Coordinates for pt in curve.Points] for curve in getattr(cut.SweptArea,"InnerCurves",())])
            inv=np.linalg.inv(mat)
            rings=[[xyz(inv,p) for p in ring] for ring in [feature["outline"],*feature.get("openings",[])]]
            geom=Polygon([p[:2] for p in rings[0]],[[p[:2] for p in ring] for ring in rings[1:]])
            normal=np.zeros(3)
            vertices=np.asarray(feature["outline"])
            for a,b in zip(vertices,np.roll(vertices,-1,axis=0)):
                normal+=np.cross(a-vertices[0],b-vertices[0])
            normal/=np.linalg.norm(normal)
            expect(shell.symmetric_difference(geom).area<max(.01,shell.length*1e-6) and
                   all(abs(p[2])<.02 for ring in rings for p in ring) and
                   np.linalg.norm((mat[:3,:3]@z)-normal*feature["thickness_mm"])<.02,
                   "member slot set-out and thickness",key)
            centre=shell.representative_point()
            xy=[(centre.x,centre.y)]+[(.95*x+.05*centre.x,.95*y+.05*centre.y) for x,y in shell.exterior.coords[:-1]]
        samples.append((key,[(xyz(rel,[x,y,0.]),xyz(rel,np.array([x,y,0.])+z)) for x,y in xy]))
    token=(body.id(),tuple(signature))
    if token not in cache:
        if len(cache)>=40:
            cache.pop(next(iter(cache)))
        raw=mesh(settings,body)
        drilled=mesh(settings,obj)
        cache[token]=(raw[0][raw[1]],drilled[0][drilled[1]])
    before,after=cache[token]
    for key,probes in samples:
        along=[(stock_length(before,p,q),stock_length(after,p,q)) for p,q in probes]
        expect(any(a>.05 for a,_ in along) and all(b<.05 for a,b in along if a>.05),
               "specified cut removes actual parent steel",key)
