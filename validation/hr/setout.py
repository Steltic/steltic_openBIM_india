"""Lay out independent units from the outer steel and base hardware, preserving clear joints."""
import json
import math

from steltic_openbim_india.composite import clearances


def translate(data,unit,axis,delta):
    unit['origin_mm'][axis]+=delta
    def translate_point(p):p[axis]=round(p[axis]+delta,4)
    def physical(row):
        for k in ('start','end','at'):
            if k in row:translate_point(row[k])
        for pt in row.get('outline',[]):translate_point(pt)
        for ring in row.get('openings',[]):
            for pt in ring:translate_point(pt)
        for part in row.get('parts',[]):physical(part)
        refs=row.get('source_elements') or ([row['source_element']] if 'source_element' in row else [])
        # Each reference carries a separate copy of its set-out, assigned after moving.
        for ref in refs:ref['offset_mm']=list(unit['origin_mm'])
    for kind in ('members','connections','panels'):
        for r in data[kind]:
            if r.get('unit')==unit['id']:physical(r)


def place(data,case,jobdir):
    by_id={u['id']:u for u in data['units']}
    path=jobdir/'units_summary.json'
    if not path.is_file():raise ValueError('Composite jobs require the native units summary')
    native=json.loads(path.read_text(encoding='utf-8-sig'))['joints']
    for joint in data['separation_joints']:
        ids=joint['units'];anchor=next(r for r in native if r['units']==ids)
        axis=0 if joint['axis']=='x' else 1; tangent=1-axis
        members=[next(u for u in case.units if u.name==uid) for uid in ids]
        origins=[by_id[uid]['origin_mm'] for uid in ids]
        lengths=[(u.nx*u.sx,u.ny*u.sy)[tangent]*1000 for u in members]
        joint['stations_mm']=[max(o[tangent] for o in origins),min(o[tangent]+l for o,l in zip(origins,lengths))]
        joint['required_gap_mm']=anchor['value']
        target=max(joint['declared_gap_mm'],anchor['value'])
        probe=dict(data,separation_joints=[joint])
        measured=clearances(probe)[0]['measured_gap_mm']
        if measured is None: raise ValueError(f"{joint['id']} has no overlapping comparison window")
        delta=joint['direction']*math.ceil((target-measured)*100)/100
        translate(data,by_id[ids[1]],axis,delta)
        result=clearances(probe)[0]
        if result['measured_gap_mm']<target-.02:raise ValueError('Computed clear joint below design set-out')
        joint['measured_clear_mm']=result['measured_gap_mm']
        joint['limiting_occurrences']=result['limiting_occurrences']
        joint['native_demand_mm']=anchor['value']
        joint['reference']='IS 1893 Part 1, 7.11.3; native inter-unit displacement envelope'
        joint['axis_gap_mm']=round(abs(by_id[ids[1]]['origin_mm'][axis]-by_id[ids[0]]['origin_mm'][axis])
                                   -(members[0 if joint['direction']==1 else 1].nx*members[0 if joint['direction']==1 else 1].sx if axis==0
                                     else members[0 if joint['direction']==1 else 1].ny*members[0 if joint['direction']==1 else 1].sy)*1000,3)
    by_axis=[set(),set()]
    for u in case.units:
        origin=by_id[u.name]['origin_mm']
        for k,(n,spacing) in enumerate([(u.nx,u.sx),(u.ny,u.sy)]):
            by_axis[k].update(round(origin[k]+spacing*i*1000,4) for i in range(n+1))
    data['grids']={a:[dict(id=f'{a.upper()}{i+1}',coordinate_mm=v) for i,v in enumerate(sorted(coords))]
                   for a,coords in zip(('x','y'),by_axis)}
