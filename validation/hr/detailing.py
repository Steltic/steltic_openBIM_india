"""Geometric trial details derived from the frame's sections; capacity checks remain in Steltic."""
from functools import lru_cache
from math import ceil, floor
from types import SimpleNamespace

import hr_autosize as HR
import sections as S


@lru_cache(maxsize=256)
def fin(section, shear):
    return HR.design_fin_plate(section,shear,template={'slip_surface':'sand_blasted'})


def connection_trials(case,u,cfg,refinement):
    g=cfg['gold']
    beam_sections=set(s for s in g['beam_sec'].values() if isinstance(s,str))
    columns={s for m in g['col_sec'].values() for s in m.values()}
    if case.number==9:
        beam_sections.update([cfg['lean_beam'],cfg['lean_purlin']]);columns.add(cfg['lean_column'])
    for plane in g.get('roof_planes',[]):
        beam_sections.update([plane['rafter_sec'],plane['ridge_sec']])
    out={k:{} for k in ('beam_shear','beam_column','column_base','brace_end','column_splice')}
    for sec in sorted(beam_sections):
        props=S.props(sec)
        # Bolt group is selected for a span tributary shear or the web design shear where lower.
        shear=min(.50*props['Aw']*230/(3**.5*1.1),1.5*(case.floor_dead+case.floor_live+case.partitions)*u.sx*u.sy*500)
        sources=[s for s,t in refinement.get('sections',{}).items() if t==sec]+[sec]
        target=max([shear]+[refinement.get('fin_design_resultant_N',{}).get(s,0) for s in sources])
        detail=fin(sec,ceil(target/1000)*1000)
        if detail:
            out['beam_shear'][sec]=detail
            if 'MRF' in ''.join(case.system) and case.number not in (1,2,3,4,5):
                sp=HR.cover_plate_joint_spec(sec,factor=1.4,continuity_t=25,doubler_t=20)
                sp['shear']=detail
                out['beam_column'][sec]=sp
    for sec in sorted(columns):
        p=S.props(sec)
        sources=[s for s,t in refinement.get('sections',{}).items() if t==sec]+[sec]
        base=HR.ring_base(sec,dict(fck_MPa=30.,plate_grade='E250',anchors={'grade':'8.8'}),d=36,
                          n=2 if case.number in (1,5) else 4,t=60)
        fails=[row for s in sources for row in refinement.get('base_checks',{}).get(s,())]
        if fails:base=HR.bump_base(base,fails,sec)
        anchors=base['anchors']
        anchors['pitch_mm']=floor(10*(min(base['L_mm'],base['B_mm'])-2*anchors['edge_mm'])/(anchors['n_per_row']-1))/10
        base['fixed']=cfg['base']=='fixed'
        out['column_base'][sec]=base
        if len(u.heights)==1:
            out['column_splice'][sec]={'none':True,'note':'Full-height column delivered to site without field splice.'}
        else:
            lows=set()
            for stack in g['col_sec'].values():
                for k in range(2,len(u.heights)+1):
                    if stack.get(str(k))==sec and stack.get(str(k-1)):
                        lows.add(stack[str(k-1)])
            f=refinement.get('section_forces',{})
            forces={key:max([f.get(s,{}).get(key,0) for s in sources]+[0]) for key in ('N','My','Mz')}
            out['column_splice'][sec]=HR.designed_splice(SimpleNamespace(group_demand=lambda _:forces),{},sec,sec,cfg['steel_grade'],sorted(lows))
    # Capacity-protected brace ends use a welded brace/gusset and a bolted gusset/
    # frame interface. They are two successive force transfers.
    brace_sizes=set(g['brace_sec'].values())
    if case.number==21:brace_sizes.add('CHS168.3X8')
    for sec in brace_sizes:
        p=S.props(sec); tg=ceil((p['tf']+6)/4)*4
        demand=max(refinement.get('brace_capacity_demand_N',{}).get(sec,0),1.1*1.4*250*p['A'])
        pitch=95.;edge=65.;d0=33.;lines=2;rows=max(4,ceil(demand/(lines*180000)))
        length=(rows-1)*pitch+2*edge
        width=p['bf']+2*edge
        throat=min(tg,p['tf'])
        f_weld=min(HR.plate_fy(tg),HR.plate_fy(throat))
        length_weld=max(p['bf'],ceil(demand*1.25*3**.5/(4*throat*f_weld*.88)/25)*25)
        connection=HR.brace_end_chs_spec(sec,tg,length_weld)
        connection.update(weld_type='cjp',bolt_type='HSFG',An_mm2=p['A'],
            bolts=dict(n_bolts=lines*rows,d_mm=30,d0_mm=d0,grade='8.8',t_mm=tg,fu_plate_MPa=410,
                       e_mm=edge,p_mm=pitch,n_e=2,mu_f=.48),
            gusset=dict(t_mm=tg,fy_MPa=250.,fu_MPa=410.,w_start_mm=width,L_conn_mm=length,L_unbraced_mm=150.,K=1.,
                        Avg_mm2=2*(length-edge)*tg,Avn_mm2=2*(length-edge-(rows-.5)*d0)*tg,
                        Atg_mm2=(width-2*edge)*tg,Atn_mm2=(width-2*edge-d0)*tg),
            bolts_and_welds_share=False,slip_surface='sand_blasted')
        # Bolted transfer has fewer active gusset millimetres than the full Whitmore width
        # where the bolted group limits the physical plate. Use that narrower plate.
        connection['moment_capacity_Nmm']=tg*min(width,p['bf']+2*length_weld*3**-.5)**2/4*HR.plate_fy(tg)/1.1
        connection['moment_capacity_cite']='IS 800 8.2, gusset in-plane plastic moment on the lesser of plate and Whitmore width.'
        out['brace_end'][sec]=connection
    cfg['connections']=out
