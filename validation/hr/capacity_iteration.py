"""Size the actual columns framing into failed native capacity-design joints."""
import json
import re
from pathlib import Path
from functools import lru_cache
import math
import hashlib


DATA=Path(__file__).with_name('capacity_decisions.json')


@lru_cache(maxsize=1)
def read():
    return json.loads(DATA.read_bytes()) if DATA.exists() else {}


def revise(case,u,g):
    import hr_autosize as H
    rules=read().get(str(case.number),{}).get(u.name,{}).get('columns',{})
    for storey,section in g['col_sec']['lateral'].items():
        current=rules.get(section,section)
        H.register(current)
        g['col_sec']['lateral'][storey]=current


def select(folder,case):
    import india_is18168 as I18
    import india_is800 as I8
    import hr_autosize as H
    from design import stock
    model=json.JSONDecoder().raw_decode((folder/'viewer_3d.html').read_text(encoding='utf-8').split('const DATA = ',1)[1])[0]
    by_node={};by_tag={}
    for element in model['elements']:
        if element['type']!='column':continue
        by_tag[element['tag']]=element
        for node in element['n']:by_node.setdefault(node,[]).append(element)
    pack=folder/'design'/'calc_package.json';cp=json.loads(pack.read_bytes())
    limits={}
    def require(element,key,factor):
        section=element['sec']; rule=limits.setdefault(section,{'Zx':1.,'Zy':1.,'A':1.,'shape':False,'L':0.})
        if key=='shape':rule[key]=True
        else:rule[key]=max(rule[key],float(factor))
        rule['L']=max(rule['L'],element['L'])
    for key,c in cp['capacity_design']['checks'].items():
        if c.get('ok') is not False:continue
        name,_,location=key.partition('@')
        mat=re.match(r'J(\d+)-([XY])$',location)
        if mat and name in ('12.11.3.2_SCWB','is18168_8_2_SCWB','12.3.4.4_column_strength'):
            for e in by_node.get(int(mat.group(1)),[]):
                require(e,'Zx' if e.get('wd','X')==mat.group(2) else 'Zy',max(1.1,min(c.get('dc') or 1.5,6.0)*1.14))
        elif location.startswith('e') and location[1:].isdigit() and int(location[1:]) in by_tag:
            e=by_tag[int(location[1:])]
            if name in ('is18168_table2_column','scbf_column_plastic','smf_column_class','is18168_7_2_column_KL_r'):
                require(e,'shape',True)
            if name in ('12.3.2.2_column_axial','12.11.3.4_out_of_plane_12.2.3'):
                require(e,'A',1.15*min(4.0,c.get('dc') or 1.5))
    for member in cp['members']:
        q=member['inputs']
        if q['role']=='lateral_col' and member.get('DC',0) and member['DC']>1:
            e=by_tag[q['governing_element']]
            for key in ('Zx','Zy','A'):require(e,key,1.1*min(member['DC'],4))
    selected={}
    for old,rules in limits.items():
        p=H.props(old); options=list(stock('WPB/NPB'))
        if case.number>=11:
            options+=list(H.built_up_catalogue('box'))
            options+=[H.box_label(d,d,t) for d in (650,750,850,950,1050,1200,1350,1500) for t in (36,45,56,63,75,85)]
        if case.number in (8,9):
            options+=[H.wi_label(d,b,tf,tw) for d in (500,600,700,850,1000) for b in (400,500,600,700)
                      for tf,tw in ((28,18),(36,22),(45,28),(63,36),(75,50)) if b<=d]
        if old.startswith('BOX'):options=[a for a in options if a.startswith('BOX')]
        fy0=I8.material_for_section(p,'E250B0')['fy_MPa']
        for label in sorted(set(options),key=H.mass_kg_m):
            v=H.props(label);fy=I8.material_for_section(v,'E250B0')['fy_MPa']
            if min((v[k]*fy)/(p[k]*fy0*rules[k]) for k in ('Zx','Zy','A'))<1:continue
            if rules['L']/min(v['rx'],v['ry'])>73:continue
            if not I18.table2_check('column',v,fy,1.4,.8)['ok']:continue
            if I8.section_class_table2(v,fy,P_N=.6*v['A']*fy)['section_class']!='plastic':continue
            selected[old]=label
            break
    return {'source_package_sha256':hashlib.sha256(pack.read_bytes()).hexdigest(),'columns':selected}


if __name__=='__main__':
    import argparse
    import sys
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--hr',required=True,type=Path)
    ap.add_argument('--jobs',required=True,type=Path)
    ap.add_argument('numbers',nargs='+',type=int)
    args=ap.parse_args();sys.path.insert(0,str(args.hr.resolve()/'steel_engine'))
    from briefs import cases
    state=read().copy()
    for n in args.numbers:
        case=cases()[n]
        for unit in case.units:
            job=args.jobs/f'IN_Ex{n}'
            if len(case.units)>1:job=job/'units'/unit.name
            result=select(job,case)
            state.setdefault(str(n),{})[unit.name]=result
            print(n,unit.name,len(result['columns']),flush=True)
        DATA.write_text(json.dumps(state,indent=2,sort_keys=True)+'\n',encoding='utf-8')
