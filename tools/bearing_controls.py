"""Measure support-to-carried contact at declared stations in saved IFC solids."""
import math
import uuid

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement as placement
import numpy as np


def surface_distances(triangles, point, normal):
    """Signed station distances where a line crosses the faces of a closed mesh, in mm."""
    a,b,c=triangles.transpose(1,0,2)
    edge1,edge2=b-a,c-a
    h=np.cross(normal,edge2)
    determinant=(edge1*h).sum(axis=1)
    usable=np.abs(determinant)>1e-10
    inverse=np.divide(1.,determinant,out=np.zeros_like(determinant),where=usable)
    relative=point-a
    u=(relative*h).sum(axis=1)*inverse
    q=np.cross(relative,edge1)
    v=(q*normal).sum(axis=1)*inverse
    intersections=(edge2*q).sum(axis=1)*inverse
    keep=usable & (u>=-1e-8) & (v>=-1e-8) & (u+v<=1+1e-8)
    return np.unique(intersections[keep].round(5))


def measure(model, project, samples):
    if not samples:
        raise ValueError("No installed bearing samples")
    settings=ifcopenshell.geom.settings()
    meshes={}
    def solid(name):
        if name not in meshes:
            guid=ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL,"steltic:india:"+project+":product:"+name).hex)
            obj=model.by_guid(guid)
            if obj.Name!=name or not obj.Representation:
                raise ValueError(f"{name}: no matching physical representation")
            shape=ifcopenshell.geom.create_shape(settings,obj)
            vertices=np.asarray(shape.geometry.verts).reshape(-1,3)*1000.
            indices=np.asarray(shape.geometry.faces).reshape(-1,3)
            matrix=placement.get_local_placement(obj.ObjectPlacement)
            meshes[name]=(vertices@matrix[:3,:3].T+matrix[:3,3])[indices]
        return meshes[name]

    results=[]
    identifiers=set()
    for sample in samples:
        name=sample["id"]
        chain=sample["chain"]
        target=sample["expected_gaps_mm"]
        tol=sample.get("tolerance_mm",1.)
        normal=np.array(sample["normal"],float)
        if (not name or name in identifiers or len(chain)<2 or len(set(chain))!=len(chain) or
            len(target)!=len(chain)-1 or not all(math.isfinite(v) for v in target) or
            not 0<tol<=2 or normal.shape!=(3,) or not np.isfinite(normal).all() or np.linalg.norm(normal)<1e-9):
            raise ValueError(f"{name}: invalid bearing sample")
        identifiers.add(name)
        normal/=np.linalg.norm(normal)
        stations=[]
        for station in sample["stations_mm"]:
            point=np.asarray(station,float)
            if point.shape!=(3,) or not np.isfinite(point).all():
                raise ValueError(f"{name}: invalid global bearing station")
            hits=[surface_distances(solid(key),point,normal) for key in chain]
            missing=[k for k,h in zip(chain,hits) if len(h)<2]
            gaps=[] if missing else [round(float(b.min()-a.max()),3) for a,b in zip(hits,hits[1:])]
            stations.append({"station_mm":station, "measured_gaps_mm":gaps, "missing_material":missing,
                             "pass":not missing and all(abs(g-e)<=tol for g,e in zip(gaps,target))})
        results.append({"id":name,"chain":chain,"expected_gaps_mm":target,"normal":sample["normal"],"tolerance_mm":tol,
                        "stations":stations,"pass":bool(stations) and all(s["pass"] for s in stations)})
    return {"status":"pass" if all(r["pass"] for r in results) else "fail","samples":results}
