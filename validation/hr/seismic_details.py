"""Use the independently solved panel-shear actions to size and locate SMRF plates."""
import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path


SOURCE=Path(__file__).with_name('seismic_detail_actions.json')


@lru_cache(maxsize=1)
def actions():
    return json.loads(SOURCE.read_bytes()) if SOURCE.exists() else {}


def derive(folder):
    from india_is800 import panel_zone_check
    package=folder/'design'/'calc_package.json'
    calc=json.loads(package.read_bytes())
    viewer=json.JSONDecoder().raw_decode((folder/'viewer_3d.html').read_text(encoding='utf-8').split('const DATA = ',1)[1])[0]
    elements={e['tag']:e for e in viewer['elements']}
    nodes=viewer['nodes']
    attached={}
    for e in elements.values():
        if e['type']=='beam':
            for node in e['n']:attached.setdefault(node,[]).append(e)
    beams=[];cols=[];doubler={};brace_actions={};seen={}
    for row in calc['capacity_design']['section12']['checks']:
        name=row['id'];label=row.get('member','')
        if name=='brace_conn_bolts' and label.startswith('e') and row.get('value'):
            sec=elements[int(label[1:])]['sec']
            brace_actions[sec]=max(brace_actions.get(sec,0.),row['value'])
        if name=='is18168_6_2_beam_bracing' and label.startswith('e'):beams.append(int(label[1:]))
        if name=='12.11.3.3_column_lateral_support' and label.startswith('e'):cols.append(int(label[1:]))
        if name!='12.11.2.3_panel_zone' or not (row.get('detail') or {}).get('found'):continue
        res=row['detail'];node_s,axis=label[1:].split('-');nd=int(node_s);i=0 if axis=='X' else 1
        inputs=dict(res['inputs']);inputs.update(doubler_grade='E250',doubler_fy_MPa=None,
                                       n_webs=res['n_webs'],continuity_plates=True)
        value=max(0,res['doubler_provided_mm'])
        if not res['ok']:
            value=max(value,5*math.ceil(res['doubler_required_mm']/5),5*math.ceil(res['t_min_mm']/5))
            key=(tuple(sorted(inputs.items())),value)
            if key not in seen:
                for _ in range(35):
                    trial=panel_zone_check(**dict(inputs,doubler_t_mm=value))
                    if not trial.get('web_thickness_ok') or (trial['pass'] and trial['dc']<=.95):break
                    value+=5
                # A single plate must fit between the web and the flange tip.
                # A larger requirement calls for a different column detail.
                available=max(0,5*math.floor(((inputs['bf_mm']-inputs['tw_mm'])/2-12)/5))
                seen[key]=min(value,100,available)
            value=seen[key]
        # The native beam-column spec is keyed by beam section. Account for
        # every actual beam sharing this panel's frame direction.
        for e in attached.get(nd,[]):
            a,b=[nodes[str(k)] for k in e['n']]
            if abs(a[i]-b[i])>abs(a[1-i]-b[1-i]):
                doubler[e['sec']]=max(value,doubler.get(e['sec'],0.))
    return {'source_package_sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
            'doubler_by_beam_mm':doubler,'brace_action_N':brace_actions,'beam_tags':sorted(set(beams)),'column_tags':sorted(set(cols))}


def revise(case,u,cfg):
    import india_connections as C
    row=actions().get(str(case.number),{}).get(u.name,{})
    if row.get('beam_tags'):
        from flange_restraints import design
        design(case,u,cfg,row)
    conn=cfg['connections']['beam_column']
    for sec,t in row.get('doubler_by_beam_mm',{}).items():
        if sec in conn and t:
            conn[sec]['doubler_t_mm']=t
            conn[sec]['doubler_grade']='E250'
    for section,demand in row.get('brace_action_N',{}).items():
        spec=cfg['connections']['brace_end'].get(section)
        if not spec or not spec.get('bolts'):continue
        bolts=spec['bolts'];g=spec['gusset'];t=g['t_mm'];edge=bolts['e_mm'];pitch=bolts['p_mm'];hole=bolts['d0_mm']
        unit=C.bolt_group_capacity_is800(**dict(bolts,n_bolts=1))
        if not unit.get('found'):continue
        rows=max(math.ceil(bolts['n_bolts']/2),math.ceil(1.06*demand/(2*unit['capacity_N'])))
        bolts['n_bolts']=2*rows;length=(rows-1)*pitch+2*edge
        width=g.get('plate_width_mm') or g['w_start_mm']
        g.update(L_conn_mm=length,Avg_mm2=2*(length-edge)*t,Avn_mm2=2*(length-edge-(rows-.5)*hole)*t,
                 Atg_mm2=(width-2*edge)*t,Atn_mm2=(width-2*edge-hole)*t)


def draw(model):
    from native_joint_parts import plate,steel
    from flange_restraints import draw as draw_restraints
    draw_restraints(model)
    rows=(model.native.get('capacity_design') or {}).get('section12',{}).get('checks',[])
    beams=model.data['members'];by_tag={}
    for beam in beams:
        ref=beam.get('source_element',{})
        if ref.get('unit')==model.u.name:by_tag[ref['tag']]=beam
    if not rows:return
    import engine3d as E
    import openseespy.opensees as ops
    native=E.build(model.cfg,'Linear');by_node={}
    for tag,kind,sec,a,b in native['ele']:
        if tag not in by_tag:continue
        for n in (a,b):by_node.setdefault(n,[]).append((tag,kind))
    for row in rows:
        if row['id']!='12.11.2.3_panel_zone':continue
        d=row.get('detail') or {};t=d.get('doubler_provided_mm')
        if not t:continue
        node,direction=row['member'][1:].split('-');nd=int(node)
        at=model.xyz(ops.nodeCoord(nd)); along=(1,0,0) if direction=='X' else (0,1,0)
        z=(0,0,1);normal=(along[1],-along[0],0);geo=d['inputs']
        # IFC plate extrusion is the ordered polygon's positive normal.
        # A doubler lies on one web surface; for a box choose that axis's outer web.
        offset=geo['tw_mm']/2 if d.get('n_webs',1)==1 else geo['bf_mm']/2
        width,height=d['bp_mm'],d['dp_mm'];origin=[at[i]+normal[i]*offset-along[i]*width/2-z[i]*height/2 for i in range(3)]
        members=[by_tag[tag]['id'] for tag,_ in by_node.get(nd,[])]
        if not members:continue
        jid=model.pre+'PZ-'+row['member'];part=plate(jid+'-DP',origin,along,z,width,height,t,steel(model,'E250'))
        model.data['connections'].append(dict(id=jid,unit=model.u.name,level=model.level(ops.nodeCoord(nd)[2]),
                 type='panel zone doubler',at=at,members=members,parts=[part],parameters={'thickness_mm':t,
                 'panel_width_mm':width,'panel_height_mm':height,'native_shear_dc':d['dc']},
                 description='Panel-zone web reinforcement sized for the native joint shear. Weld preparation and termination require fabrication design.'))


if __name__=='__main__':
    import sys
    p=argparse.ArgumentParser();p.add_argument('--hr',required=True,type=Path);p.add_argument('--jobs',required=True,type=Path)
    p.add_argument('numbers',nargs='+',type=int);a=p.parse_args();sys.path.insert(0,str(a.hr.resolve()/'steel_engine'))
    from briefs import cases
    result=actions().copy()
    for n in a.numbers:
        case=cases()[n];g=result.setdefault(str(n),{})
        for u in case.units:
            folder=a.jobs/f'IN_Ex{n}'
            if len(case.units)>1:folder=folder/'units'/u.name
            g[u.name]=derive(folder)
    SOURCE.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
