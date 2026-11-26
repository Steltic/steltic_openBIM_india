"""Reopen a shed IFC and measure every fascia weld contact and free roof strip."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom as geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from verify_peb_bearings import common_area,triangles


def verify(handoff,ifc):
    from steltic_openbim_india.model import load
    data,signature=load(handoff)
    model=ifcopenshell.open(str(ifc))
    stamped=ifcopenshell.util.element.get_psets(model.by_type('IfcProject')[0])['Steltic_India_Source']['SourceSHA256']
    if stamped!=signature:raise ValueError('IFC was issued against a different handoff')
    products={p.Name:p for p in model.by_type('IfcElement') if p.Name}
    settings=geom.settings()
    settings.set('use-world-coords',True)
    cache={}
    def mesh(key):
        if key not in cache:
            shape=geom.create_shape(settings,products[key])
            v=np.asarray(shape.geometry.verts).reshape(-1,3)*1000
            idx=np.asarray(shape.geometry.faces).reshape(-1,3)
            cache[key]=(v,triangles(v,idx))
        return cache[key]

    connections=[j for j in data['connections'] if j['type']=='welded eave bracket']
    roofs=[r for r in data['panels'] if r['role'] in ('roof deck','roof sheeting')]
    results=[]
    least=1.
    count=0
    for j in connections:
        key=j['id']
        for weld in j['parts']:
            if weld['kind']!='weld' or weld.get('weld_type')=='cjp':continue
            suffix=weld['id'][len(key)+1:]
            if suffix.startswith(('WR','WC')):
                parents=[key+'-WEB'+suffix[2],key+('-BACK' if suffix.startswith('WR') else '-CAP')]
            elif suffix.startswith('HOLD-'):
                parents=[suffix[5:-1],key+'-CAP']
            else:
                raise ValueError(f"Unknown fascia fillet {weld['id']}")
            expected=weld['leg_mm']*math.dist(weld['start'],weld['end'])
            for parent in parents:
                common=common_area(mesh(weld['id'])[1],mesh(parent)[1])
                count+=1
                ratio=common/expected
                least=min(least,ratio)
                if ratio<.995:
                    results.append(dict(weld=weld['id'],parent=parent,expected_face_mm2=round(expected,3),
                                        measured_shared_face_mm2=round(common,3)))

    edges=[]
    for m in data['members']:
        if m['role']!='fascia rail':continue
        rail_id=m['id']
        skin=next(p for p in roofs if rail_id in p.get('bearing_members',[]))
        obj=products[skin['id']]
        solid=obj.Representation.Representations[0].Items[0]
        world=ifcopenshell.util.placement.get_local_placement(obj.ObjectPlacement)
        xform=world@ifcopenshell.util.placement.get_axis2placement(solid.Position)
        n=xform[:3,:3]@np.asarray(solid.ExtrudedDirection.DirectionRatios)
        if n[2]<0:n=-n
        sv=mesh(skin['id'])[0];rv=mesh(rail_id)[0]
        roof_plane=min(sv@n)
        soffit=sv[np.abs(sv@n-roof_plane)<.02];top=rv[np.abs(rv@n-roof_plane)<.02]
        # Cross the physical rail's principal plan direction and look towards its nearer edge.
        cross_i=int(np.argmin(np.ptp(rv[:,:2],axis=0)))
        side=-1 if rv[:,cross_i].mean()<sv[:,cross_i].mean() else 1
        edge=max(side*soffit[:,cross_i])
        gap=edge-max(side*top[:,cross_i]) if len(top)>=4 else None
        edges.append({'fascia':rail_id,'panel':skin['id'],'horizontal_axis':'xy'[cross_i],'edge_sign':side,
                      'skin_soffit_edge_mm':round(float(side*edge),3),'free_sheet_strip_mm':None if gap is None else round(float(gap),3),
                      'pass':bool(gap is not None and abs(gap-25.)<=.15)})
    success=connections and count and edges and not results and all(e['pass'] for e in edges)
    return dict(project=data['project']['id'],handoff_sha256=signature,ifc_sha256=hashlib.sha256(ifc.read_bytes()).hexdigest(),
                status='pass' if success else 'fail',brackets=len(connections),fillet_parent_faces=count,
                minimum_fraction_of_specified_fillet_face=round(least,6),failed_weld_interfaces=results,fascia_spans=edges)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('handoff',type=Path)
    ap.add_argument('ifc',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    options=ap.parse_args()
    report=verify(options.handoff,options.ifc)
    options.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(report['project'],report['status'],report['fillet_parent_faces'],'fillet contact faces',
          len(report['fascia_spans']),'spans',len(report['failed_weld_interfaces']),'failed weld interfaces')
    raise SystemExit(report['status']!='pass')
