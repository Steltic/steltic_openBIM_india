"""Revise member groups against this run's native concurrent force envelopes."""
import argparse
import json
import math
from pathlib import Path
import sys


FILE=Path(__file__).with_name('trial_refinements.json')


def apply(number,unit,g):
    if number<=5 or not FILE.is_file():return {}
    instructions=json.loads(FILE.read_text(encoding='utf-8')).get(str(number),{}).get(unit,{})
    mapping=instructions.get('sections',{})
    from hr_autosize import register
    for name in mapping.values():register(name)
    def use(obj):
        if isinstance(obj,dict):return {k:use(v) for k,v in obj.items()}
        if isinstance(obj,list):return [use(v) for v in obj]
        if isinstance(obj,tuple):return tuple(use(v) for v in obj)
        if isinstance(obj,str):return mapping.get(obj,obj)
        return obj
    for key in ('col_sec','beam_sec','brace_sec','ebf_link_sec','ebf_beam_sec','ebf_brace_sec',
                'col_sec_by_line','beam_sec_by_line','roof_planes'):
        if key not in g:continue
        if key in ('brace_sec','ebf_brace_sec'):
            # A section label may serve both a brace and a column. The welded-box
            # substitutions size columns; retain the specified rolled brace family.
            g[key]={storey:(name if mapping.get(name,'').startswith('BOX') else mapping.get(name,name)) for storey,name in g[key].items()}
        else:g[key]=use(g[key])
    return instructions


def proposals(case,unit,cfg,folder):
    import sections as S
    import india_is800 as I8
    import static_model as SM
    from design import stock
    cp=json.loads((folder/'design/calc_package.json').read_text(encoding='utf-8-sig'))
    records=json.loads((folder/'design/member_combo_forces.json').read_text(encoding='utf-8-sig'))['elements']
    import hr_autosize as HR
    candidates={}; fins={}; braces={}; base_checks={}; section_demand={}; no_candidate=[]
    for m in cp['members']:
        dc=m.get('DC') or 0
        sec=m['inputs']['section']; p=S.props(sec)
        if dc<=.96 or p['section_type']!='I' or p.get('welded') or sec.startswith(('WI','TI')):continue
        kind=m['inputs']['kind']
        group=m['inputs']['role']
        governing=m.get('governing_element_result') or {}
        tag=str(governing.get('id','')).lstrip('e') or str(m['inputs']['governing_element'])
        if tag not in records:continue
        rec=records[tag]
        force=SM.combo_forces_for_member_check(rec['records'],kind)
        def index(f):
            return abs(f['P_N'])/p['A']+max(abs(f.get(k,0)) for k in ('Mz_i_Nmm','Mz_j_Nmm','Mz_mid_Nmm'))/p['Zx']+max(abs(f.get(k,0)) for k in ('My_i_Nmm','My_j_Nmm','My_mid_Nmm'))/p['Zy']
        shortlist=sorted(force,key=index,reverse=True)[:24]
        if governing.get('governing_combo'):
            shortlist.extend(x for x in force if x['combo']==governing['governing_combo'])
        role={'col':'column','beam':'beam','brace':'brace'}.get(kind,kind)
        material=governing.get('material') or {}
        # Native interaction and Table 3 are re-evaluated with the same restraint convention.
        inp=dict(grade=(material.get('grade') or cfg['steel_grade']),role=role,L_mm=rec['L_mm'],Kz=1,Ky=1,
                 LLT_sag_mm=cfg['LLT_sag_mm'],LLT_hog_mm=cfg['LLT_hog_mm'])
        names=list(stock('MB' if case.number==21 and kind=='col' else 'WPB' if kind in ('col','brace') else 'NPB/WPB/MB'))
        if kind=='col' and case.number in (11,12,13,14,15,16,17,18,19,20):
            names+=HR.built_up_catalogue('box')
        elif case.number not in (10,21) and kind in ('beam','brace'):
            dims=[(d,b,tf,tw) for d in (550,700,850,1000,1200,1400) for b in (300,400,500,600)
                  for tf,tw in ((22,14),(28,18),(36,22),(45,28),(56,36)) if b<=d]
            names+=sorted((HR.wi_label(*v) for v in dims),key=HR.mass_kg_m)
        replacing=None
        for name in names:
            trial=HR.props(name)
            if trial['A']<=p['A'] or kind=='col' and trial['Iy']<p['Iy']:continue
            if kind=='col' and case.zone!='II' and rec['L_mm']/min(trial['rx'],trial['ry'])>74:continue
            out=I8.member_check_is800(dict(inp,section=name),shortlist)
            if out.get('found') and out['dc']<=.84:
                replacing=name;break
        if replacing:
            old=candidates.get(sec)
            if not old or S.props(replacing)['A']>S.props(old)['A']:candidates[sec]=replacing
        else:no_candidate.append(sec)
    for c in cp['connections']:
        d=c.get('demand') or {};sec=c.get('section')
        if not sec:continue
        f=d.get('V_P_resultant_N') or d.get('V_N')
        if f:fins[sec]=max(fins.get(sec,0),round(f,1))
        if d.get('Pu_capacity_design_N'):
            braces[sec]=max(braces.get(sec,0),round(d['Pu_capacity_design_N'],1))
        for row in c.get('checks',[]):
            if 'column base' in row.get('name','') and (row.get('dc') or 0)>.90:
                base_checks.setdefault(sec,[]).append([row['name'].split(': ')[-1],round(row['dc'],5)])
    for m in cp['members']:
        q=m['inputs']; group=q['section']
        dst=section_demand.setdefault(group,{'N':0,'Mz':0,'My':0})
        for k,key in [('N','P_comp_N'),('Mz','Mz_Nmm'),('My','My_Nmm')]:dst[k]=max(dst[k],abs(q.get(key) or 0))
    return dict(sections=candidates,fin_design_resultant_N=fins,brace_capacity_demand_N=braces,
                base_checks=base_checks,section_forces=section_demand,exhausted_rolled_groups=sorted(set(no_candidate)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('numbers',type=int,nargs='+')
    for arg in ('hr','jobs','corpus'):parser.add_argument('--'+arg,required=True,type=Path)
    args=parser.parse_args();sys.path.insert(0,str(args.hr.resolve()/'steel_engine'))
    from briefs import cases
    from design import make
    saved=json.loads(FILE.read_text(encoding='utf-8')) if FILE.is_file() else {}
    for n in args.numbers:
        c=cases()[n];current=saved.setdefault(str(n),{})
        for u in c.units:
            job=args.jobs/f'IN_Ex{n}'
            if len(c.units)>1:job=job/'units'/u.name
            cfg=make(c,u,args.corpus)
            r=proposals(c,u,cfg,job);prev=current.get(u.name,{}).get('sections',{})
            nextmap={k:r['sections'].get(v,v) for k,v in prev.items()}
            nextmap.update({k:v for k,v in r['sections'].items() if k not in nextmap})
            print(n,u.name,len(r['sections']),flush=True)
            r['sections']=nextmap;current[u.name]=r
    FILE.write_text(json.dumps(saved,indent=2,sort_keys=True)+'\n',encoding='utf-8')


if __name__=='__main__':main()
