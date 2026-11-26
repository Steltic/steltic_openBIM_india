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


def clipped(triangle,lo,hi):
    pts=list(triangle)
    for dim in range(3):
        for bound,sign in ((lo[dim],1),(hi[dim],-1)):
            old=pts;pts=[]
            for a,b in zip(old,old[1:]+old[:1]):
                da=sign*(a[dim]-bound);db=sign*(b[dim]-bound)
                if da>=0:pts.append(a)
                if (da>=0)!=(db>=0):pts.append(a+(b-a)*da/(da-db))
            if len(pts)<3:return False
    return any(np.linalg.norm(np.cross(a-pts[0],b-pts[0]))>.5 for a,b in zip(pts[1:],pts[2:]))


def door_clearances(data,mesh):
    """Check clear passage through the weather line, projecting anchors and interior frame face."""
    from briefs import cases
    from enclosure import doors
    n=int(data['project']['id'].replace('IN_Ex',''));case=cases()[n];u=case.units[0]
    shapes=[]
    def candidate(tag,points,pad):
        vertices=np.asarray(points);shapes.append((tag,vertices.min(axis=0)-pad,vertices.max(axis=0)+pad))
    for m in data['members']:
        sizes=[data['profiles'][k]['dimensions_mm'] for k in set([m['profile'],m.get('end_profile',m['profile'])])]
        radius=max(max(v.get('d',0),v.get('b',0),v.get('diameter',0)) for v in sizes)
        candidate(m['id'],[m['start'],m['end']],radius)
    for p in data['panels']:candidate(p['id'],p['outline'],p['thickness_mm'])
    for j in data['connections']:
        for p in j.get('parts',[]):
            candidate(p['id'],p['outline'] if p['kind']=='plate' else [p['start'],p['end']],
                      p.get('thickness_mm',p.get('diameter_mm',p.get('leg_mm',0))))
    records=[]
    for axis in ('X','Y'):
        along=0 if axis=='X' else 1;perp=1-along
        for side in (0,1):
            opening=doors(case,u,axis,side)
            if not opening:continue
            panel=next(p for p in data['panels'] if p['role']=='wall cladding' and f'-{axis}{side}-' in p['id'])
            skin=panel['outline'][0][perp];grid=side*((u.ny*u.sy) if axis=='X' else (u.nx*u.sx))*1000
            depth=sorted((skin+(5 if side else -5),grid+(-500 if side else 500)))
            for index,(a,b,z) in enumerate(opening,1):
                low=np.zeros(3);high=np.zeros(3)
                low[along],high[along]=a+.5,b-.5
                low[perp],high[perp]=depth
                low[2],high[2]=.5,z-.5
                clashes=[]
                for key,p,q in shapes:
                    if np.any(q<=low) or np.any(p>=high):continue
                    triangles=mesh(key)[0]
                    touch=triangles[(np.max(triangles,axis=1)>low).all(axis=1)&(np.min(triangles,axis=1)<high).all(axis=1)]
                    if any(clipped(t,low,high) for t in touch):clashes.append(key)
                records.append(dict(door=f'{axis}{side}-{index}',clear_width_mm=b-a,clear_height_mm=z,
                                    envelope_depth_mm=round(depth[1]-depth[0],1),intrusions=clashes))
    return records


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
        if joint['type'] not in ('purlin bearing','canopy purlin bearing','girt bearing','gable girt bearing'):continue
        block=joint['parts'][0]['id'];shape=mesh(block);count['blocks']+=1
        for m in joint['members']:
            area=common_area(shape,mesh(m));count['interfaces']+=1
            if area<min_area:min_area,min_pair=area,[block,m]
            if area<100:failed.append(dict(block=block,member=m,common_contact_mm2=round(area,2)))
    doors=door_clearances(data,mesh)
    return dict(project=data['project']['id'],status='pass' if count['blocks'] and not failed and not any(d['intrusions'] for d in doors) else 'fail',counts=dict(count),
                minimum_common_area_mm2=round(min_area,2) if min_pair else None,minimum_pair=min_pair,failures=failed,door_clearances=doors)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('handoff',type=Path);parser.add_argument('ifc',type=Path)
    parser.add_argument('--output',type=Path,help='Write the numerical result to this file')
    args=parser.parse_args();result=verify(args.handoff,args.ifc);report=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(report,encoding='utf-8')
    else:print(report,end='')
    raise SystemExit(result['status']!='pass')
