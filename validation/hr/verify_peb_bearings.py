"""Reopen the delivered IFC and measure each PEB seat's common material contact area."""
import argparse
import json
from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom as geom
import numpy as np
from shapely.geometry import Polygon


def triangles(vertices,indices):
    faces=vertices[indices];ns=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]);lens=np.linalg.norm(ns,axis=1)
    keep=lens>.001
    return faces[keep],ns[keep]/lens[keep,None]


def common_area(first,second):
    a,an=first;b,bn=second;area=0.
    for triangle,normal in zip(a,an):
        # Faces must oppose each other, be coplanar and actually overlap in that plane.
        mask=(bn@normal<-.999999)&(np.max(np.abs((b-triangle[0])@normal),axis=1)<.04)
        if mask.any():
            dims=[i for i in range(3) if i!=np.argmax(np.abs(normal))];scale=max(abs(normal))
            poly=Polygon(triangle[:,dims]);area+=sum(poly.intersection(Polygon(f[:,dims])).area/scale for f in b[mask])
    return area


def verify(handoff,ifc):
    data=json.loads(handoff.read_text(encoding='utf-8'));f=ifcopenshell.open(str(ifc))
    products={p.Tag:p for p in f.by_type('IfcElement') if getattr(p,'Tag',None)}
    settings=geom.settings();settings.set('use-world-coords',True);cache={}
    def mesh(key):
        if key not in cache:
            s=geom.create_shape(settings,products[key]);v=np.array(s.geometry.verts).reshape(-1,3)*1000
            faces=np.array(s.geometry.faces).reshape(-1,3);cache[key]=triangles(v,faces)
        return cache[key]
    count=Counter();failed=[];min_area=float('inf');min_pair=None
    for joint in data['connections']:
        if joint['type'] not in ('purlin bearing','canopy purlin bearing','girt bearing'):continue
        block=joint['parts'][0]['id'];shape=mesh(block);count['blocks']+=1
        for m in joint['members']:
            area=common_area(shape,mesh(m));count['interfaces']+=1
            if area<min_area:min_area,min_pair=area,[block,m]
            if area<100:failed.append(dict(block=block,member=m,common_contact_mm2=round(area,2)))
    return dict(project=data['project']['id'],status='pass' if count['blocks'] and not failed else 'fail',counts=dict(count),
                minimum_common_area_mm2=round(min_area,2) if min_pair else None,minimum_pair=min_pair,failures=failed)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('handoff',type=Path);parser.add_argument('ifc',type=Path)
    parser.add_argument('--output',type=Path,help='Write the numerical result to this file')
    args=parser.parse_args();result=verify(args.handoff,args.ifc);report=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(report,encoding='utf-8')
    else:print(report,end='')
    raise SystemExit(result['status']!='pass')
