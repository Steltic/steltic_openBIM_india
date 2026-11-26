"""PEB permanent loads from the modeled parts and the supplier envelope allowance."""
import ast
import csv
import math
from collections import defaultdict
from pathlib import Path

NODAL_FAMILIES={'apex splice','portal knee','rafter splice','panel zone doubler','canopy root'}


def area(loop):
    from steltic_openbim_india.geometry import cross,sub
    area_vector=[0.,0.,0.]
    for a,b in zip(loop,loop[1:]+loop[:1]):
        for i,v in enumerate(cross(sub(a,loop[0]),sub(b,loop[0]))):area_vector[i]+=v
    return math.hypot(*area_vector)/2


def part_weight(part):
    if part['kind']=='plate':
        volume=(area(part['outline'])-sum(area(r) for r in part.get('openings',[])))*part['thickness_mm']
    else:
        if part['kind']=='bolt':section=math.pi*part['diameter_mm']**2/4
        elif part.get('weld_type')=='cjp':section=part['throat_mm']*part.get('width_mm',part['throat_mm'])
        else:section=part['leg_mm']**2/2
        volume=section*math.dist(part['start'],part['end'])
    return volume*7.85e-6*9.81/1000   # kN


def coordinate(point):return tuple(round(v,2) for v in point)


def joint_weights(data):
    loads=defaultdict(float)
    for j in data['connections']:
        if j['type'] in NODAL_FAMILIES:loads[coordinate(j['at'])]+=sum(map(part_weight,j.get('parts',())))
    return loads


def load_schedule(case):
    rows=[]
    with Path(__file__).with_name('peb_detail_loads.csv').open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            if int(r['case'])!=case:continue
            for j in range(int(r['last_frame'])-int(r['first_frame'])+1):
                rows.append(dict(node=int(r['first_node'])+j*int(r['node_increment']),level=1,
                    Fz_N=-float(r['load_kN'])*1000,note='Shop connection steel at portal, splice or canopy assembly',
                    x_mm=float(r['x_mm']),y_mm=float(r['first_y_mm'])+j*float(r['bay_mm']),z_mm=float(r['z_mm'])))
    return rows


def regenerate(inputs,output):
    """Bind the independent trial take-off to actual native model nodes and group identical frames."""
    records=[]
    for n,data,source_path in inputs:
        nodes=defaultdict(list)
        for line in (source_path/'model_opensees.py').read_text(encoding='utf-8').splitlines():
            if line.startswith('ops.node('):
                tag,x,y,z=ast.literal_eval('('+line.partition('(')[2])
                nodes[coordinate((x,y,z))].append(tag)
        group=defaultdict(list);spacing=data['grids']['y'][1]['coordinate_mm']
        for (x,y,z),force in joint_weights(data).items():
            candidates=nodes.get((x,y,z),[])
            if not candidates:raise ValueError(f'No native node at {(x,y,z)}')
            node=min(candidates);j=round(y/spacing)
            # Round each individual permanent detail load up to the next quarter kN.
            group[x,z,math.ceil(force*4)/4].append((j,node))
        for (x,z,force),stations in sorted(group.items()):
            pending=sorted(stations)
            while pending:
                first,node=pending.pop(0);last=first;increment=0
                if pending and pending[0][0]==first+1:increment=pending[0][1]-node
                while pending and pending[0]==(last+1,node+(last+1-first)*increment):
                    last=pending.pop(0)[0]
                records.append(dict(case=n,x_mm=x,z_mm=z,first_y_mm=first*spacing,bay_mm=spacing,
                    first_frame=first,last_frame=last,first_node=node,node_increment=increment,load_kN=force))
    with Path(output).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)


def verify(model):
    from handoff import check
    from steltic_openbim_india.profiles import section_polygons
    import json

    d=model.data;n=model.case.number;cfg=json.loads((model.folder/'design'/'cfg_snapshot.json').read_text(encoding='utf-8'))
    schedule=cfg.get('nodal_dead_loads',[])
    given={(r['x_mm'],r['y_mm'],r['z_mm']):-r['Fz_N']/1000 for r in schedule if 'x_mm' in r}
    wanted=joint_weights(d)
    if set(given)!=set(wanted):raise ValueError('Physical connection load stations differ from the native dead-load schedule')
    ratio=max(wanted[k]/v for k,v in given.items())
    check(d['checks'],model.pre+'NODE-STEEL-WEIGHT',f'{len(given)} roof frame and canopy-root assembly points. '
          f'Modeled steel totals {sum(wanted.values()):.2f} kN, applied at its actual native nodes as {sum(given.values()):.2f} kN.',
          'pass' if ratio<=1.00001 else 'fail',ratio,'IS 875 Part 1. Comparative nodal plate, shaft and weld take-off including cut openings.')
    gs={k:sum(poly.area for poly in section_polygons(v)) for k,v in d['profiles'].items()}
    categories=defaultdict(float);roof_area=roof_slope=canopy_area=wall_area=0.
    for m in d['members']:
        if m['role'] not in ('purlin','girt','gable girt','roof brace','rafter flange brace','column flange brace','door jamb','door lintel','canopy purlin'):continue
        weight=gs[m['profile']]*math.dist(m['start'],m['end'])*7.85e-6*9.81/1000
        # Include a 10% linear allowance for laps even though the supplier sets the final overlap.
        if m['role'] in ('purlin','girt','gable girt','canopy purlin'):weight*=1.1
        categories[m['role']]+=weight
    for j in d['connections']:
        if ' bearing' in j['type']:categories[j['type']]+=sum(map(part_weight,j.get('parts',())))
    for p in d['panels']:
        role=p['role'];gross=area(p['outline']);material=p['material']
        if role=='roof sheeting':
            xs,ys,_=zip(*p['outline']);roof_area+=(max(xs)-min(xs))*(max(ys)-min(ys))/1e6;roof_slope+=gross/1e6
        if role=='dock canopy':
            xs,ys,_=zip(*p['outline']);canopy_area+=(max(xs)-min(xs))*(max(ys)-min(ys))/1e6
        if material not in ('SHEET','DAYLIGHT'):continue
        if role=='wall cladding':wall_area+=gross/1e6
        net=gross-sum(area(h) for h in p.get('openings',[]))
        kg_m3=7850 if material=='SHEET' else 1200
        # 10% allowance on sheet material for ribs, laps and local trims.
        categories[role]+=1.10*net*p['thickness_mm']*kg_m3*9.81e-12
    wool=.05*.314*roof_slope if n in (2,4) else 0.
    groups=[('ROOF',roof_area,cfg['D_roof'],wool,('purlin','roof brace','rafter flange brace','purlin bearing','roof sheeting','rooflight','eave flashing','gable verge flashing')),
            ('WALL',wall_area,cfg['clad'],0.,('girt','gable girt','girt bearing','gable girt bearing','door jamb','door lintel','wall cladding','column flange brace'))]
    if n==2:groups.append(('CANOPY',canopy_area,.27,0.,('canopy purlin','dock canopy','canopy purlin bearing')))
    for label,surface,allowance,other,sets in groups:
        actual=(sum(categories[k] for k in sets)+other)/surface
        check(d['checks'],model.pre+label+'-ASSEMBLY-WEIGHT',f'{label.title()} envelope weighs {actual:.3f} kN/m² '
              f'over {surface:.1f} m² against {allowance:g} kN/m² applied. Includes modeled parts, 10% secondary laps, 10% sheet ribs and laps'
              +(' and 50 mm glass-wool insulation.' if other else '.'),'pass' if actual<=allowance else 'fail',actual/allowance,
              'IS 875 Part 1:2026 PDF page 4, IS 875 Part 1 steel unit weight and project specification. Supplier validates ribs, laps and roofing assembly.')
    for role in ('rafter','column'):
        fly=[m for m in d['members'] if m['role']==role+' flange brace']
        proof=next(r for r in model.native['connections'] if r['id']=='conn-peb-flange-brace-'+role)
        cap=min(r['limit'] for r in proof['checks'] if ' in compression' in r['name'] or 'shear / bearing' in r['name'])
        lengths=[math.dist(m['start'],m['end']) for m in fly]
        cosine=min(abs(m['end'][1]-m['start'][1])/length for m,length in zip(fly,lengths))
        force=proof['demand']['F_point_N']/cosine
        util=max(max(lengths)/1500,force/cap)
        check(d['checks'],model.pre+role.upper()+'-FLY-SET-OUT',f'{len(fly)} installed angles, '
              f'longest {max(lengths):.1f} mm. Largest axial angle demand {force/1000:.2f} kN at actual component cosine {cosine:.4f}. '
              f'Controlling member or bolt capacity at the 1.5 m design length is {cap/1000:.2f} kN. Confirm attachment and local Z flange stiffening.',
              'pass' if util<=1 else 'fail',util,'IS 800 8.3.2, 7.5.1.2 and 10.3.3–10.3.4. Native flange force and paired angle assembly.')
