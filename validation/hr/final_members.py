"""Select SFRS sections against the previous independent Steltic analysis."""
import csv
import json
from pathlib import Path
from functools import lru_cache
import math
import re


DATA=Path(__file__).with_name('section_decisions.json')


@lru_cache(maxsize=1)
def decisions():
    return json.loads(DATA.read_bytes()) if DATA.exists() else {}


def section_changes(case,unit,g):
    import hr_autosize as HR
    if case.number<=5:return {}
    trial=decisions().get(str(case.number),{}).get(unit.name,{})
    names=trial.get('sections',{})
    def replace(role,name):
        selected=names.get(role,{}).get(name,name)
        HR.register(selected)
        return selected
    for role,items in g['col_sec'].items():
        for k,sec in items.items():
            items[k]=replace(role+'_col',sec)
    for k,sec in g['beam_sec'].items():
        g['beam_sec'][k]=replace(k.split('_')[0],sec)
    for plane in g.get('roof_planes',[]):
        for key in ('rafter_sec','ridge_sec'):
            plane[key]=replace('roof',plane[key])
    for k,sec in g['brace_sec'].items():
        g['brace_sec'][k]=replace('brace',sec)
    for axis,sec in g.get('beam_sec_by_line',{}).items():
        g['beam_sec_by_line'][axis]=replace('roof',sec)
    for k in ('ebf_link_sec','ebf_beam_sec'):
        for axis,sections in g.get(k,{}).items():
            for lev,sec in sections.items():sections[lev]=replace('floor',sec)
    return trial


def select(case,unit,folder):
    import hr_autosize as HR
    import india_is800 as I8
    import india_is18168 as I18
    import static_model as static
    from design import stock
    p=json.loads((folder/'design'/'calc_package.json').read_bytes())
    envelope=json.loads((folder/'design'/'member_combo_forces.json').read_bytes())['elements']
    with (folder/'design'/'member_schedule.csv').open(encoding='utf-8-sig',newline='') as file:
        schedule={int(r['ele_tag']):r for r in csv.DictReader(file)}
    problems={}
    for key,c in p['capacity_design']['checks'].items():
        name,_,tag=key.partition('@e')
        if not tag.isdigit() or int(tag) not in schedule or c.get('ok') is not False:continue
        r=schedule[int(tag)]; problems.setdefault((r['role'],r['section']),set()).add(name)
    modes=p.get('seismic_analysis',{}).get('modes',[])
    freq={}
    for d in ('x','y'):
        if modes:
            m=max(modes,key=lambda a:a.get('mass_'+d) or 0)
            freq[d]=round(1/m['T'],6)
    decisions={'sections':{},'frequency_hz':freq,'source_package_sha256':__import__('hashlib').sha256((folder/'design/calc_package.json').read_bytes()).hexdigest()}
    for item in p['members']:
        if case.number==21:break
        q=item['inputs'];sec=q['section']; old=HR.props(sec); role=q['role']; kinds=problems.get((role,sec),set())
        dc=item.get('DC') or 0
        targeted=any(name.startswith(('is18168_table2','brace_KL_r','is18168_7_2_column','brace_plastic','scbf_column_plastic',
                                      'smf_column_class','smf_beam_class','12.3.2.2_column_axial','12.3.2.2_brace_axial')) for name in kinds)
        if not (targeted or dc>.96 or (case.number==7 and role=='lateral_col')):continue
        kind=q['kind']; role0={'beam':'beam','col':'column','brace':'brace'}.get(kind)
        if not role0 or old['section_type'] not in ('I','box') or case.number==21:continue
        fs=envelope[str(q['governing_element'])]
        loads=static.combo_forces_for_member_check(fs['records'],kind)
        def norm(f):
            return abs(f['P_N'])/old['A']+max(abs(f.get(k,0)) for k in ('Mz_i_Nmm','Mz_j_Nmm','Mz_mid_Nmm'))/old['Zx']+max(abs(f.get(k,0)) for k in ('My_i_Nmm','My_j_Nmm','My_mid_Nmm'))/old['Zy']
        controlling=sorted(loads,key=norm,reverse=True)[:18]
        controlling.extend(f for f in loads if f['combo']==q.get('governing_combo'))
        pmax=q.get('P_comp_N') or 0; L=fs['L_mm']
        candidates=list(stock('WPB' if kind in ('col','brace') else 'NPB/WPB/MB'))
        if kind=='col' and case.number>=11:
            candidates=candidates+HR.built_up_catalogue('box')
        if kind=='col' and case.number==7:
            candidates+=[HR.wi_label(d,b,tf,tw) for d in (600,700,800) for b in (400,450,500,550) for tf,tw in ((28,18),(36,22),(45,28))]
        # Preserve the stronger weak axis too when a column predominantly works in one plane.
        inertia_factor=1.8 if case.number==7 and kind=='col' else 1.
        min_ix=old['Ix']*inertia_factor
        if case.number==10 and role=='roof' and dc>1:min_ix=max(min_ix,old['Ix']*1.65)
        # When the current rolled stock is exhausted, a compact fabricated candidate
        # is considered only for the briefs admitting welded sections.
        if kind=='col' and case.number in (15,16,17,18,19,20):
            candidates+= [HR.box_label(d,d,t) for d in (650,750,850,950,1050,1200) for t in (36,45,56,63)]
        if sec.startswith('WI') and kind=='beam':
            candidates+= [HR.wi_label(d,b,tf,tw) for d in (700,850,1000,1200) for b in (350,450,550)
                           for tf,tw in ((32,20),(40,25),(50,32))]
        if sec.startswith('BOX') and kind=='col':candidates=[s for s in candidates if s.startswith('BOX')]
        for selected in sorted(set(candidates),key=HR.mass_kg_m):
            v=HR.props(selected); fy=I8.material_for_section(v,q['grade']).get('fy_MPa')
            if not fy or v['A']<old['A']*.96 or v['Ix']<min_ix or (kind=='col' and v['Iy']<old['Iy']*.95):continue
            if kind=='brace' and case.number in (7,10,11):KL=L*.5
            else:KL=L
            if kind=='brace' and KL/min(v['rx'],v['ry'])>(119 if 'OCBF' in case.system else 157):continue
            if role=='lateral_col' and case.zone!='II' and L/min(v['rx'],v['ry'])>74:continue
            if case.zone!='II' and (role in ('lateral_col','brace') or kind=='beam' and targeted):
                component=('link' if 'is18168_table2_link' in kinds else role0)
                if not I18.table2_check(component,v,fy,1.4,1.1*pmax/(fy*v['A'])).get('ok'):continue
                if I8.section_class_table2(v,fy,P_N=pmax)['section_class']!='plastic':continue
            elif kind=='brace' and I8.section_class_table2(v,fy,P_N=pmax)['section_class']=='slender':continue
            length_hog=3000 if case.number==8 and kind=='beam' else unit.sx*1000
            trial=dict(grade=q['grade'],role=role0,L_mm=L,Kz=KL/L,Ky=KL/L,LLT_sag_mm=min(unit.sy/3,3)*1000,LLT_hog_mm=length_hog)
            res=I8.member_check_is800(dict(trial,section=selected),controlling)
            if res.get('found') and res.get('dc',2) <= (.68 if dc>1 else .89):
                decisions['sections'].setdefault(role,{})[sec]=selected
                break
    return decisions


if __name__=='__main__':
    import argparse
    import sys
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--hr',required=True,type=Path)
    ap.add_argument('--jobs',required=True,type=Path)
    ap.add_argument('numbers',nargs='+',type=int)
    args=ap.parse_args();sys.path.insert(0,str(args.hr.resolve()/'steel_engine'))
    from briefs import cases
    result=decisions().copy()
    for n in args.numbers:
        case=cases()[n]; entry=result.setdefault(str(n),{})
        for unit in case.units:
            folder=args.jobs/f'IN_Ex{n}'
            if len(case.units)>1:folder=folder/'units'/unit.name
            entry[unit.name]=select(case,unit,folder)
            print(n,unit.name,sum(len(x) for x in entry[unit.name]['sections'].values()),flush=True)
        DATA.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
