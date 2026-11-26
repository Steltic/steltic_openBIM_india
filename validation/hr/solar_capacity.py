"""Check the frozen Bengaluru roof, produce its retrofit comparison and installer note.

Pass the producer checkout, local BIS corpus and native Ex1 and Ex5 job folders.
The two full-run boundary jobs keep engineering evidence under --jobs. The
published output directory contains results and project inputs, without BIS text.
"""
import argparse
import csv
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from briefs import cases
from secondary import select_z


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_csv(path,rows):
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def fields(width_mm=30000,length_mm=75000):
    # All four fields have the same rail/module dead load. Keep a cross walkway
    # at mid-length and at least 0.6 m at both eaves and either side of the ridge.
    half_y=(length_mm-1000)/2
    field_width=.75*width_mm*length_mm/(4*half_y)
    xbands=[(600,600+field_width),(width_mm-600-field_width,width_mm-600)]
    return [(x0,x1,y0,y1) for x0,x1 in xbands for y0,y1 in ((0,half_y),(half_y+1000,length_mm))]


def frozen_config(hr,corpus,pv):
    from design import make
    case=replace(cases()[5],pv=pv)
    return make(case,case.units[0],corpus)


def section_trial(cfs,cfg):
    u=cases()[1].units[0]
    gravity=cfg['D_roof']+cfg['D_roof_collateral']+cfg['Lr']
    patterns=cfg['load_plan']['member_wind']
    uplift=max(abs(min(p['roof_windward_kNm2'],p['roof_leeward_kNm2'])) for p in patterns)
    common=(cfs,u.sy*1000,cases()[1].purlin_spacing*1000)
    label=select_z(*common,gravity,uplift)[0]
    def at(pv):
        _,_,dc,checks=select_z(*common,gravity+pv,uplift,fixed=label,details=True)
        return dc,max(checks,key=checks.get)
    return label,at


def native_bound(hr,corpus,jobs,cents):
    name=f"IN_Ex5_uniform_{cents:03d}"
    out=jobs/name
    cfg=frozen_config(hr,corpus,cents/100)
    # Re-evaluate the actual frozen steel at each boundary, including the new
    # seismic weight. Existing folders are replaced by the native entry point.
    from run_case import private_retrievals
    import pipeline
    private_retrievals(cfg,corpus,out)
    native=pipeline.design_and_report(name,cfg)
    if native.get('blocked') or not (out/'design/calc_package.json').is_file():
        raise ValueError(f"Native PV boundary {cents} did not produce a design: {native.get('error')}")
    package=read(out/'design/calc_package.json')
    st=package['design_status']['status']
    return {'native_status':st,'native_reasons':package['design_status']['reasons'],
            'max_member_dc':max(m['DC'] for m in package['members'] if m.get('DC') is not None),
            'max_connection_dc':max(m['DC'] for m in package['connections'] if m.get('DC') is not None),
            'native_gates':package['gates'],'sha256':hashlib.sha256((out/'design/calc_package.json').read_bytes()).hexdigest()}


def sensitivity(args,cfg):
    label,at=section_trial(args.cfs,cfg)
    history={}
    def z(cents):
        if cents not in history:
            dc,name=at(cents/100)
            history[cents]=dict(uniform_pv_kNm2=cents/100,section=label,dc=dc,governing=name)
        return history[cents]
    def all_gates(cents):
        row=z(cents)
        if 'native' not in row:row['native']=native_bound(args.hr,args.corpus,args.jobs,cents)
        return row['dc']<=1 and row['native']['native_status']=='complete'
    # A failing frozen purlin provides a strict upper bound. Find adjacent centi-
    # kPa settings and prove the lower setting against the full building analysis.
    lo,hi=0,25
    if z(lo)['dc']>1:raise ValueError('As-built purlin already fails at zero PV')
    while z(hi)['dc']<=1:hi*=2
    while hi-lo>1:
        mid=(lo+hi)//2
        if z(mid)['dc']<=1:lo=mid
        else:hi=mid
    all_gates(hi)
    if not all_gates(lo):
        hi=lo;lo=0
        if not all_gates(lo):raise ValueError('No admissible uniform load; baseline design remains open.')
        while hi-lo>1:
            mid=(lo+hi)//2
            if all_gates(mid):lo=mid
            else:hi=mid
    return dict(criterion='All native member, seismic, connection and serviceability gates plus frozen IS 801 purlin checks.',
        datum='Uniform added permanent PV load over the whole roof plan, kN/m²',resolution_kNm2=.01,
        last_passing_kNm2=lo/100,first_failing_kNm2=hi/100,history=[history[c] for c in sorted(history)])


def before_after(base,solar,cfs,cfg):
    native=[read(p/'design/peb_element_inputs.json') for p in (base,solar)]
    if native[0].keys()!=native[1].keys():raise ValueError('Existing analysis tags differ')
    rows=[]
    for tag in sorted(native[0],key=int):
        before,after=[p[tag] for p in native]
        if before['member']!=after['member'] or before['stations']!=after['stations']:
            raise ValueError(f'Frozen element geometry, material or restraints differ at e{tag}')
        rows.append(dict(id='e'+tag,category='native analysis element',section=before['member']['section'],
             baseline_dc=before['dc'],baseline_check=before['governing_check'],
             retrofit_dc=after['dc'],retrofit_check=after['governing_check']))
    packages=[read(p/'design/calc_package.json') for p in (base,solar)]
    con=[{v['id']:v for v in p['connections']} for p in packages]
    if set(con[0])!=set(con[1]):raise ValueError('Native connection families differ')
    for k,b in sorted(con[0].items()):
        a=con[1][k]
        rows.append(dict(id=k,category='native connection group',section=b.get('section'),
            baseline_dc=b.get('DC'),baseline_check=b.get('limit_state'),retrofit_dc=a.get('DC'),retrofit_check=a.get('limit_state')))
    name,at=section_trial(cfs,cfg)
    before,bl=at(0);after,al=at(.15)
    for p in range(1,20):
        if p==10:continue
        covered=any(x0-750<1500*p<x1+750 for x0,x1,y0,y1 in fields())
        for j in range(1,11):
            rows.append(dict(id=f'Main-PU-{p}-{j}',category='IS 801 purlin occurrence',section=name,
                baseline_dc=before,baseline_check=bl,retrofit_dc=after if covered else before,retrofit_check=al if covered else bl))
    pd=cfg['load_plan']['wind_summary']['pd_kNm2']
    gname,_,gdc,gs=select_z(cfs,7500,1800,1.35*pd,1.35*pd,details=True)
    rows.append(dict(id='Main-Z-WALL',category='IS 801 unchanged wall girt section',section=gname,
            baseline_dc=gdc,baseline_check=max(gs,key=gs.get),retrofit_dc=gdc,retrofit_check=max(gs,key=gs.get)))
    # Report every fabrication occurrence as well as every native analysis tag,
    # including the detailing-only items for which the producer has no numerical check.
    handoffs=[read(path/'design/openbim_handoff.json') for path in (base,solar)]
    occurrences=[{r['id']:r for r in h['members']} for h in handoffs]
    if occurrences[0].keys()!=occurrences[1].keys():raise ValueError('Existing physical member IDs differ')
    joints=[{j['id']:j for j in h['connections']} for h in handoffs]
    if joints[0].keys()!=joints[1].keys():raise ValueError('Retrofit changed the existing connection set')
    for mid,joint in joints[0].items():
        for field in ('type','at','members','parts','parameters'):
            if joint.get(field)!=joints[1][mid].get(field):raise ValueError(f'Frozen joint {mid} changed {field}')
    table={r['id']:r for r in rows}
    for mid,existing in occurrences[0].items():
        new=occurrences[1][mid]
        for field in ('start','end','profile','end_profile','material','ref_direction'):
            if existing.get(field)!=new.get(field):raise ValueError(f'Frozen physical member {mid} changed {field}')
        if mid in table:continue
        refs=existing.get('source_elements') or ([existing['source_element']] if existing.get('source_element') else [])
        candidates=[table['e'+str(r['tag'])] for r in refs]
        role=existing['role']
        if role=='girt':candidates=[table['Main-Z-WALL']]
        if role=='gable girt':
            checks=[next(c for c in h['checks'] if c['id']=='Main-Z-GABLE') for h in handoffs]
            candidates=[dict(baseline_dc=checks[0]['utilization'],retrofit_dc=checks[1]['utilization'],
                            baseline_check='IS 801 gable girt',retrofit_check='IS 801 gable girt')]
        if role in ('rafter flange brace','column flange brace'):
            candidates=[table['conn-peb-flange-brace-'+role.split()[0]]]
        record=dict(id=mid,category='physical '+role,section=existing['profile'])
        for stage in ('baseline','retrofit'):
            governed=[r for r in candidates if isinstance(r[stage+'_dc'],(float,int))]
            worst=max(governed,key=lambda r:r[stage+'_dc']) if governed else None
            record[stage+'_dc']=worst[stage+'_dc'] if worst else None
            record[stage+'_check']=worst[stage+'_check'] if worst else 'Local detailing-only occurrence. A separate component resistance is unverified.'
        rows.append(record)
    for row in rows:
        dc=row['retrofit_dc']
        row['action']='Consider lighter array components, an additional purlin or engineered Z/lap strengthening.' if isinstance(dc,(int,float)) and dc>1 else (
            'Check local member and connections against site conditions.' if dc is None else '')
    return rows


def reaction_changes(base,solar):
    def get(p):
        with (p/'design/reactions.csv').open(newline='',encoding='utf8') as f:
            return {(r['case'],r['node']):r for r in csv.DictReader(f)}
    old,new=get(base),get(solar)
    if old.keys()!=new.keys():raise ValueError('Reaction case/support sets differ')
    out=[]
    for (case,node),b in old.items():
        a=new[(case,node)]
        row=dict(case=case,node=node,x_m=b['x_m'],y_m=b['y_m'])
        for field in ('Fx_kN','Fy_kN','Fz_kN','Mx_kNm','My_kNm','Mz_kNm'):
            row['baseline_'+field]=b[field];row['PV_'+field]=a[field]
            row['delta_'+field]=round(float(a[field])-float(b[field]),4)
        out.append(row)
    return out


def installer_note(path,result,rows):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    failed=[r for r in rows if isinstance(r['retrofit_dc'],(int,float)) and r['retrofit_dc']>1]
    m=max(failed,key=lambda a:a['retrofit_dc']) if failed else max(rows,key=lambda a:a['retrofit_dc'] or 0)
    styles=getSampleStyleSheet()
    body=ParagraphStyle('note',parent=styles['BodyText'],fontSize=11,leading=16,spaceAfter=8)
    subsections=[
        ('Installation decision','Hold the proposed rooftop installation pending engineer approval of a revised design.' if failed else 'Refer the calculated load and attachment requirements to the engineer of record for release.'),
        ('Array and building','Bengaluru, 30 m by 75 m steel portal-frame factory. The 1,687.5 m² array covers 75% of plan across two slopes. The proposed permanent load is 0.15 kN/m² on covered purlins and 0.1125 kN/m² averaged over the frame. Keep the eaves, ridge and 1 m mid-length access route clear.'),
        ('Calculated result',f"The governing checked component is {m['section']} under {m['retrofit_check']}. Its demand/capacity ratio increases from {m['baseline_dc']:.3f} to {m['retrofit_dc']:.3f}. The verified uniform added-load limit on the stated 0.01 kN/m² grid is {result['last_passing_kNm2']:.2f} kN/m². The next load, {result['first_failing_kNm2']:.2f} kN/m², exceeds capacity."),
        ('Design and installation actions','The engineer can assess lighter modules and rails, supplemental purlins or reinforcement of existing Z sections and laps. Verify the installed steel, bridging, sheeting, connections and condition. Roof braces, door jambs and lintels require separate checks. The PV supplier designs rail and clamp uplift and local sheet fixings. Confirm the assumed flush-array wind pressures for the selected system.'),
        ('Foundation interface','The supplied reactions table gives all six reaction components, before and after the array, for every support and basic load case. The foundation engineer checks the existing anchors, concrete and soil. The engineer of record issues any approval or stability certificate.')]
    story=[Paragraph('Rooftop PV structural adequacy note',styles['Title']),Spacer(1,5*mm),Paragraph('To the PV installer · Bengaluru factory · IN_Ex5',body)]
    for heading,paragraph in subsections:
        story.extend((Paragraph(heading,styles['Heading2']),Paragraph(paragraph,body)))
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=17*mm,bottomMargin=15*mm).build(story)


def publish(args,cfg,result):
    rows=before_after(args.baseline,args.proposed,args.cfs,cfg)
    failures=[r for r in rows if isinstance(r['retrofit_dc'],(int,float)) and r['retrofit_dc']>1]
    result.update(covered_area_m2=1687.5,covered_load_kNm2=.15,average_frame_load_kNm2=.1125,
        fields_mm=fields(),proposed_failure_count=len(failures),physical_member_count=len(read(args.baseline/'design/openbim_handoff.json')['members']),
        unquantified_physical_roles=sorted({r['category'][9:] for r in rows if r['category'].startswith('physical ') and r['retrofit_dc'] is None}),
        assessment='Every purlin whose tributary strip intersects an array is conservatively checked at full covered load over the bay.',
        strengthening_options=['Lighter array and rail system','Supplemental purlins','Engineered reinforcement of existing Z sections and laps'])
    (args.out/'solar-capacity.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    write_csv(args.out/'solar-before-after.csv',rows)
    write_csv(args.out/'solar-reaction-changes.csv',reaction_changes(args.baseline,args.proposed))
    installer_note(args.out/'solar-installer-note.pdf',result,rows)
    print(f"Uniform PV bracket {result['last_passing_kNm2']:.2f}–{result['first_failing_kNm2']:.2f} kN/m²; {len(failures)} occurrences exceed capacity.",flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('hr','cfs','corpus','jobs','baseline','proposed','out'):
        p.add_argument('--'+key,type=Path,required=True)
    args=p.parse_args()
    for key,v in vars(args).items():setattr(args,key,v.resolve())
    sys.path.insert(0,str(args.hr/'steel_engine'))
    os.environ['STEEL_BUILDER_JOBS']=str(args.jobs)
    args.out.mkdir(parents=True,exist_ok=True)
    cfg=frozen_config(args.hr,args.corpus,0)
    publish(args,cfg,sensitivity(args,cfg))


if __name__=='__main__':main()
