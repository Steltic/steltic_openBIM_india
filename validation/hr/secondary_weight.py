"""Weigh physical steel outside native frame elements and reconcile applied dead load."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from briefs import cases,floor_cells


FILE=Path(__file__).with_name('secondary_dead_loads.json')


def areas(ring):
    p=ring[0]
    cross=[0.,0.,0.]
    for a,b in zip(ring,ring[1:]+ring[:1]):
        x=[u-v for u,v in zip(a,p)];y=[u-v for u,v in zip(b,p)]
        for k in range(3):cross[k]+=x[(k+1)%3]*y[(k+2)%3]-x[(k+2)%3]*y[(k+1)%3]
    return math.hypot(*cross)/2


def measure(model,unit,case):
    from steltic_openbim_india.profiles import section_polygons
    weights=defaultdict(float);sections={}
    levels=[0.]
    for h in unit.heights:levels.append(levels[-1]+h*1000)
    def store(z):
        return min(range(1,len(levels)),key=lambda k:abs(levels[k]-z))
    for row in model['members']:
        if row['unit']!=unit.name or row.get('source_element') or row.get('source_elements'):continue
        p=row['profile']
        if p not in sections:sections[p]=sum(v.area for v in section_polygons(model['profiles'][p]))
        length=math.dist(row['start'],row['end'])-sum(row.get('end_cutbacks_mm',[]))
        weights[store((row['start'][2]+row['end'][2])/2)]+=sections[p]*length*7.85e-6
    for joint in model['connections']:
        if joint.get('unit')!=unit.name or joint['type'] in ('column base','base plate'):continue
        for part in joint.get('parts',[]):
            typ=part['kind']
            if typ=='plate':
                volume=(areas(part['outline'])-sum(areas(r) for r in part.get('openings',[])))*part['thickness_mm']
            elif typ=='bolt':volume=math.pi*part['diameter_mm']**2/4*math.dist(part['start'],part['end'])
            elif typ=='weld':
                face=(part['throat_mm']*part.get('width_mm',part['throat_mm'])
                      if part.get('weld_type')=='cjp' else part['leg_mm']**2/2)
                volume=face*math.dist(part['start'],part['end'])
            else:raise ValueError(typ)
            weights[store(joint['at'][2])]+=volume*7.85e-6
    rows={}
    for k,kg in weights.items():
        plan=len(floor_cells(unit,k))*unit.sx*unit.sy
        # No deduction for unspecified inclusions in the original imposed/dead
        # allowance. Already itemised runway/cross-frame nodal weights remain
        # in the native combination, conservatively, as separately applied loads.
        rows[str(k)]={'physical_kg':round(kg,1),'plan_m2':plan,'actual_kNm2':round(kg*.00981/plan,5)}
    return rows


def proposed(number,unit,cfg):
    if number in (15,19) or not FILE.is_file():return
    schedule=json.loads(FILE.read_bytes()).get(str(number),{}).get(unit.name,{})
    if schedule:cfg['extra_mass_floors']={int(k):v['applied_kNm2'] for k,v in schedule.items()}


def attest(model):
    rows=measure(model.data,model.u,model.case)
    if model.case.number in (15,19):return rows
    for k,row in rows.items():
        allowance=model.cfg.get('extra_mass_floors',{}).get(int(k),0.)
        row['applied_kNm2']=allowance
        if allowance:
            ratio=row['actual_kNm2']/allowance
            model.data['checks'].append(dict(id=model.pre+'PHYSICAL-DL-'+k,status='pass' if ratio<=1.00001 else 'fail',
                utilization=round(ratio,5),description=f"Storey {k} auxiliary members, bearings and physical connection steel {row['actual_kNm2']:.3f} kN/m². Additional gravity/seismic dead action {allowance:.3f} kN/m².",
                reference='IS 875 Part 1 steel density; IS 1893 Part 1 seismic mass and normal Steltic dead-load combinations.'))
        else:
            model.data['checks'].append(dict(id=model.pre+'PHYSICAL-DL-'+k,status='review',
                description=f"Storey {k} additional steel measures {row['actual_kNm2']:.3f} kN/m². Confirm the measured quantity in the native gravity and mass model."))
    return rows


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root',type=Path);ap.add_argument('numbers',nargs='+',type=int)
    arg=ap.parse_args(); current=json.loads(FILE.read_bytes()) if FILE.is_file() else {}
    for number in arg.numbers:
        model=json.loads((arg.root/f'IN_Ex{number}'/'handoff.json').read_bytes())
        case=cases()[number]
        for unit in case.units:
            rows=measure(model,unit,case)
            for k,r in rows.items():
                previous=current.get(str(number),{}).get(unit.name,{}).get(k,{}).get('applied_kNm2',0.)
                r['applied_kNm2']=max(previous,math.ceil((1.12*r['actual_kNm2']+.03)/.05)*.05)
            current.setdefault(str(number),{})[unit.name]=rows
    FILE.write_text(json.dumps(current,indent=2,sort_keys=True)+'\n',encoding='utf-8')
