"""Size a fresh trial framing schedule, then build the Steltic India job configuration.

Member screening establishes only a starting size. The normal engine run supplies
the full analysis, per-combination member/connection checks and final design status.
"""
from functools import lru_cache
from math import atan2, ceil, degrees, hypot

import engine3d as E
import frame_build as FB
import india_is800 as I8
import india_seismic as IS
import india_wind_tables as W
import peb_build as PB
import sections as S

from briefs import floor_cells, vertices
from grounding import Grounding, roof_imposed


R = {'OMRF':3.,'SMRF':5.,'OCBF':4.,'SCBF':4.5,'EBF':5.}
Z = {'II':.10,'III':.16,'IV':.24,'V':.36}


@lru_cache(maxsize=None)
def stock(family):
    labels = set(n for p in family.split('/') for n in S.list_is808(p))
    return sorted(labels,key=lambda n:(S.props(n)['A'],n))


@lru_cache(maxsize=None)
def choose(family, role, L, w=0., axial=0., lateral_moment=0., llt=None, div=300, grade='E250'):
    """Lowest-area rolled candidate passing tributary ULS and elastic service deflection.

    w = service gravity (N/mm), axial = design axial compression (N), lateral_moment
    = design moment (N mm). K=1.0 for this screen. Full analysis follows.
    """
    result = None
    for name in stock(family):
        p=S.props(name)
        load=w+p['A']*7.85e-5
        if w and (5*load*L**4/(384*200000*p['Ix'])) > L/div:
            continue
        M=1.5*load*L**2/8 if w else 0.
        rec=dict(id='screen',section=name,role=role,L_mm=L,Kz=1,Ky=1,
                 LLT_sag_mm=llt or L,LLT_hog_mm=llt or L,grade=grade)
        dem=[dict(combo='1.5(DL+LL)',P_N=axial,Mz_i_Nmm=lateral_moment,Mz_j_Nmm=-lateral_moment,
                  Mz_free_Nmm=M,Mz_mid_Nmm=M, Vy_N=1.5*load*L/2 if w else 0.)]
        out=I8.member_check_is800(rec, dem)
        if out.get('found') and out.get('dc') is not None and out['dc'] <= .83:
            result=name
            break
    # A trial schedule still needs to exist if the rolled stock exhausts; the
    # normal engine retains its governing failure. Do not label it an accepted size.
    return result or max(stock(family),key=lambda n:S.props(n)['Ix' if w else 'A'])


def areas(case,u):
    return [(len(floor_cells(u,k))*u.sx*u.sy) if u.shape!='gym' else u.nx*u.ny*u.sx*u.sy for k in range(1,len(u.heights)+1)]


def brace_bays(case,u,k,allowed):
    nx,ny=u.nx,u.ny
    allb=[]
    for ax,n,lines in [('X',nx,[0,ny]),('Y',ny,[0,nx])]:
        system=case.system[ax=='Y']
        if system not in ('SCBF','OCBF','EBF'):
            continue
        bays=sorted({0,max(n-1,0)})
        if case.number==10: bays=[1,4] if ax=='X' else [0,3]
        if case.number==13 and ax=='X':bays=[0,n//2,n-1]
        if case.number==14: bays=[1,2,3] if ax=='X' else list(range(n))
        if case.number==19 and u.name=='Flange':
            bays=([0,2,4] if ax=='X' else [0,1])
            if ax=='Y': lines=[0,1,2,4,5,6]
        if case.number==20: lines=sorted(set(lines+[1]))
        if case.number==15:
            lines=([0,3,5] if ax=='X' else [0,4,7])
            bays=list(range(n))
        if case.number in (2,9) and ax=='Y':
            bays=sorted(set(bays+[n//2]))
            if case.number==2: lines=[0,2,nx]
        for line in lines:
            for b in bays:
                i,j = (b,line) if ax=='X' else (line,b)
                p=(i+int(ax=='X'),j+int(ax=='Y'))
                if (i,j) in allowed and p in allowed:
                    allb.append([ax,i,j])
    return allb


def frame(case,u,dl,ll,roof,roof_ll):
    n=case.number; nx,ny=u.nx,u.ny; nf=len(u.heights)
    # A secondary spans X and feeds Y girders. Both one-way beam roles are initialized independently.
    fx=choose('MB/NPB','beam',u.sx*1000,(dl+ll+case.partitions)*min(3,u.sy/3),llt=2500)
    fy=choose('NPB/WPB','beam',u.sy*1000,(dl+ll+case.partitions)*u.sx,llt=2500)
    rx=choose('MB/NPB','beam',u.sx*1000,(roof+roof_ll+case.collateral+case.pv)*min(3,u.sy/3),llt=2000,div=180)
    ry=choose('NPB/WPB','beam',u.sy*1000,(roof+roof_ll+case.collateral+case.pv)*u.sx,llt=2000,div=180)
    cols={}; grav={}; groups={}; links={}
    for k,h in enumerate(u.heights,1):
        N=1.5*u.sx*u.sy*((nf-k)*(dl+ll+case.partitions)+roof+roof_ll+case.pv+case.collateral)*1000
        load=lambda fac: round(N*fac/1000)*1000
        grav[str(k)]=choose('WPB','column',h*1000,axial=load(1.06))
        bending=round(max(9e7,(nf-k+1)*2.2e7) if 'SMRF' in case.system else 0)
        cols[str(k)]=choose('WPB','column',h*1000,axial=load(.8),lateral_moment=bending)
        groups[str(k)]=choose('WPB','brace',round(hypot(max(u.sx,u.sy),h)*1000),axial=round(load(.65)),llt=3000)
        if n in (18,19) and (n==18 or k <= nf//2):
            side=25*ceil(max(500,620+18*(nf-k) + (180 if n==18 and k==1 else 0))/25)
            t=32 if k <= nf//2 else 25
            name=f'BOX{side}X{side}X{t}X{t}'
            S.register_box(name,side,side,t,t)
            cols[str(k)]=name
        links[str(k)]=fx
    g=dict(col_sec={'lateral':cols,'gravity':grav},
           beam_sec=dict(floor_X=fx,floor_Y=fy,roof_X=rx,roof_Y=ry),brace_sec=groups,
           sfrs_base='pinned' if n in (1,5,10,13,14) else 'fixed',gravity_base='fixed' if n==6 else 'pinned')
    g['present']={}
    footprints={}
    for k in range(1,nf+1):
        present=vertices(floor_cells(u,k))
        footprints[k]=present
        g['present'][str(k)]=sorted(present)
    g['present']['0']=sorted(set.union(*footprints.values()))
    if u.shape=='gym':
        # A roof framing intersection exists at the centre, with no supporting
        # column below it. All four deck panels retain their tributary loads.
        g['present']['0'].remove((1,1))
    if u.shape=='stepped_l':
        g['roof_regions']={5:[[i,j] for i,j in sorted(floor_cells(u,5)-floor_cells(u,6))]}
    moments=[]
    if case.system[0] in ('OMRF','SMRF'):
        moments += [['X',j] for j in (range(ny+1) if n<=9 or n==21 else [0,ny])]
    if case.system[1] in ('OMRF','SMRF'):
        moments += [['Y',i] for i in (range(nx+1) if n==6 else [0,nx])]
    g['moment_lines']=moments
    if u.shape=='gym':
        g['moment_lines'].append(['X',1])
        g['beam_sec_by_line']={'X1':choose('NPB/WPB','beam',17000,roof*u.sy+roof_ll*u.sy,llt=2500,div=180)}
    bays={str(k):brace_bays(case,u,k,present) for k,present in footprints.items()}
    if 'EBF' in case.system:
        g.update(ebf_bays=bays,e_link_mm=900,ebf_brace_sec=groups,
                 ebf_beam_sec={'X':links,'Y':links},ebf_link_sec={'X':links,'Y':links})
    else:
        g['xbays']=bays
    specs={}
    if n==10:
        across=u.ny*u.sy
        g['roof_planes']=[dict(axis='Y',eave_coords_m=[0,across],eave_z_m=sum(u.heights),
             ridge_coord_m=across/2,ridge_z_m=sum(u.heights)+across/120,level=nf,
             lines=list(range(nx+1)),rafter_sec=ry,ridge_sec=rx,rafter_releases=['both','none'],
             braced_lines=list(range(nx+1)))]
    if case.rise:
        width=u.nx*u.sx; eave=sum(u.heights)
        plane=dict(axis='X',eave_coords_m=[0,width],eave_z_m=eave,ridge_coord_m=width/2,
                   ridge_z_m=eave+case.rise,level=nf,lines=list(range(ny+1)),ridge_sec='MB250',
                   braced_lines=sorted({0,1,ny-1,ny}))
        g['roof_planes']=[plane]
        fullspan=choose('NPB/WPB','beam',u.sx*1000,(roof+roof_ll+case.collateral+case.pv)*u.sy,llt=3000,div=180)
        plane['rafter_sec']=fullspan
        if n in (1,2,3,4,5):
            # Select web and flange plates by span/depth, then verify the stepped sections with Steltic.
            deep=int(ceil(u.sx*1000/25/50))*50
            shallow=int(ceil(deep*.50/25))*25
            bf=350 if n in (2,4) else 300
            tf=25 if n in (2,4) else 20
            tw=16 if n in (2,4) else 12
            tapered=f'TI{deep}-{shallow}X{bf}X{tf}X{tw}'
            column=f'TI{shallow}-{deep}X{bf}X{tf}X{tw}' if n!=3 else f'WI{deep}X{bf}X{tf}X{tw}'
            prismatic=f'WI{shallow}X{bf}X{tf}X{tw}'
            for label in (tapered,column,prismatic): PB.ensure(label)
            g['peb_column']=column
            g['col_sec']['lateral']={'default':PB.section_at(column,.5)}
            g['col_sec']['gravity']={'default':prismatic}
            plane['rafter_sec']=prismatic
            plane['rafter_members']={'lo':[(u.sx*.2*1000,tapered),(width*500,prismatic)]}
            if n==2:
                # Interior support points coincide with existing rafter grid nodes.
                plane['rafter_members']['lo']=[(u.sx*.2*1000,tapered),(u.sx*1000,prismatic),(width*500,prismatic)]
            plane['gravity_lines']=[0,ny]
            plane['rafter_members_by_line']={str(q):{'lo':[(width*500,prismatic)]} for q in [0,ny]}
        if n in (7,8,9):
            g['col_sec']['lateral']={'default':choose('WPB','column',eave*1000,axial=400000,lateral_moment=400e6)}
    return g,specs


def make(case,u,corpus):
    gr=Grounding(corpus); gr.essentials(case,u)
    n=case.number; width=u.nx*u.sx; length=u.ny*u.sy; height=sum(u.heights)
    roof=1.2 if u.name=='Gym' else case.roof_dead
    dl=3.5 if u.name=='Workshop' else case.floor_dead
    ll=5 if u.name=='Workshop' else case.floor_live
    roof_ll=roof_imposed(u,case.rise)
    importance=1 if u.name=='Workshop' else case.importance
    g,_=frame(case,u,dl,ll,roof,roof_ll)
    from size_iteration import apply
    refinement=apply(n,u.name,g)
    from final_members import section_changes
    section_changes(case,u,g)
    from capacity_iteration import revise as size_joint_columns
    size_joint_columns(case,u,g)
    if n==10:
        # True-slope girders carry a 15 m transverse tributary; the preceding
        # iteration failed both IS 800 interaction and roof service deflection.
        g['roof_planes'][0]['rafter_sec']='WPB800X300X317.36'
        g['beam_sec']['roof_Y']='WPB800X300X317.36'
    if n==7:g['brace_sec']={k:'WPB360X370X197.66' for k in g['brace_sec']}
    if n==12 and u.name in ('Link','Gym'):
        # The equal 17 m sides gave almost coincident modes in the link wing.
        # Increase the section stiffness in the X perimeter direction and on
        # the gym's 17 m clear-span line, preserving all pinned gravity bays.
        g['beam_sec']['floor_X']='WPB800X300X317.36'
        g['beam_sec']['roof_X']='WPB650X300X224.78'
        if u.name=='Gym':g['beam_sec_by_line']['X1']='WPB800X300X317.36'
    if n==21:
        g['brace_sec']={k:'CHS244.5X8' for k in g['brace_sec']}
        g['beam_sec']['roof_Y']='CHS193.7X8'
        g['roof_planes'][0]['ridge_sec']='CHS193.7X8'
    from transfer_members import decisions as transfer_decisions
    final_selection=transfer_decisions(n,u.name)
    if final_selection:
        section_changes(case,u,g,final_selection)
        refinement={**refinement,'sections':{**refinement.get('sections',{}),**{a:b for role in final_selection['sections'].values() for a,b in role.items()}}}
    use=('hospital' if n==14 else 'school' if n==12 else 'residential' if n==19 else 'commercial office' if n>=11 and n!=21 and u.name!='Workshop'
         else 'commercial retail' if n==10 else 'industrial')
    occ={'use':use,'area_m2':sum(areas(case,u)),'food_storage':False}
    if n==14: occ['hospital']=True
    if n==12: occ['educational']=True
    if n==10: occ['persons']=201
    sd={'X':R[case.system[0]],'Y':R[case.system[1]]}
    seismic=dict(zone=case.zone,Z=Z[case.zone],I=importance,R=min(sd.values()),soil='II')
    cfg=dict(units='mm',jurisdiction='india',standard='IS',heights=[h*1000 for h in u.heights],NX=u.nx,NY=u.ny,SX=u.sx*1000,SY=u.sy*1000,
             arch=f'{case.city} {u.name} {case.system[0]} / {case.system[1]}',system=' + '.join(dict.fromkeys(case.system)),
             system_x=case.system[0],system_y=case.system[1],R_x=sd['X'],R_y=sd['Y'],steel_grade=('E350' if n in (1,2,3,4,5) else 'E250B0'),
             seis=seismic,occupancy=occ,load_plan={},D_floor=dl,D_roof=roof,L_floor=ll,Lr=roof_ll,
             D_roof_collateral=case.collateral,D_roof_pv=case.pv,clad=.3 if n<=9 or n==21 else (.4 if n==10 else .5),
             self_weight=True,partitions=(len(u.heights)>1 and case.partitions>0),partition_load_kNm2=case.partitions,
             floor_system='one-way',deck_span='X' if n in (6,13,14,16) else 'Y',
             base=g['sfrs_base'],col=next(iter(g['col_sec']['lateral'].values())),beam=g['beam_sec']['floor_X'],
             brace=g['brace_sec']['1'],model=dict(bases='mixed',joints='mixed',gravity='framed'),floor_type='steel',
             diaphragm='flexible' if n==10 else 'rigid',drift_limit=.004,
             analyses=['ESM'] if case.zone=='II' and height<15 and n not in (6,7,11) else ['RSA'],
             apply_is18168=case.zone!='II',is18168=case.zone!='II',tube_grade='YST310',tube_process='HFS',
             brace_grade='E250B0',brace_config='X',K_factors={r:{'Ky':1.,'Kz':1.} for r in ('col','beam','brace')},
             LLT_sag_mm=min(u.sy/3,3.)*1000,LLT_hog_mm=u.sx*1000)
    cfg['diaphragm_7_6_4']={'basis':'Bare metal deck distributes roof inertia by tributary width.' if n==10 else
                              ('Roof plan bracing ties the frames.' if case.rise else 'Concrete topped steel deck acts in-plane.') }
    if n==6 or 10<=n<=20:
        # With a secondary spacing, Steltic's H13 one-way routine takes the
        # secondary (not the sheet corrugation) direction in deck_span.
        cfg['deck_span']='Y' if n in (11,12,13,14,16) else 'X'
        across=u.sx if cfg['deck_span']=='Y' else u.sy
        target=case.purlin_spacing if n==6 else 2.5 if n in (10,11) else 3.
        cfg['secondary_spacing_mm']=1000*across/ceil(across/target)
    if 6<=n<=21:
        from secondary_weight import proposed as physical_dead_load
        physical_dead_load(n,u,cfg)
    if n==9:
        cfg['lean_beam']='WPB800X300X317.36'
        cfg['lean_purlin']='MC400'
        cfg['lean_column']='WPB400X400X239.62'
    if n==15:
        cfg['diaphragm_stiffness']=dict(type='metal_deck',topping_t_mm=100,fck_MPa=25,source='Trial design assumption',cite='IS 456 6.2.3.1; verify with decking engineer')
    if n==9:
        cfg['snow']=.8*gr.shimla_snow()
        cfg['snow_partial']=dict(axis='X',ridge_mm=width*500)
    if n==6: cfg['storage_levels']=[1]
    if n in (1,2,3,4,5):
        grade=cfg['steel_grade']
        for lab in (g['peb_column'],g['roof_planes'][0]['rafter_sec'],g['roof_planes'][0]['rafter_members']['lo'][0][1]):
            PB.ensure(lab)
        cfg['flange_braces']={'column':{'girts_mm':[i*case.girt_spacing*1000 for i in range(1,ceil(height/case.girt_spacing))],
                                          'fly_braces_mm':[i*case.girt_spacing*1000 for i in range(1,ceil(height/case.girt_spacing))]},
                              'rafter':{'purlins_mm':[i*case.purlin_spacing*1000 for i in range(1,ceil(width/2/case.purlin_spacing))],
                                         'fly_braces_mm':[i*case.purlin_spacing*1000 for i in range(1,ceil(width/2/case.purlin_spacing))]}}
        cfg['grade_by_section']={cfg['brace']:'E250B0'}
    FB.attach_gold(cfg,g)
    from special import specialized
    specialized(case,u,cfg)
    from restraints import declare
    declare(case,u,cfg)
    from detailing import connection_trials
    connection_trials(case,u,cfg,refinement)
    if 6<=n<=21:
        from joint_iteration import revise
        revise(case,u,cfg,refinement)
        if n not in (15,19):
            from seismic_details import revise as revise_seismic
            revise_seismic(case,u,cfg)
        if n==15:
            from pune_ebf import revise as revise_pune
            revise_pune(case,u,cfg,refinement,gr)
        if n==19:
            from guwahati import revise as revise_guwahati
            revise_guwahati(case,u,cfg,refinement,gr)
    if n<=5:
        from peb_iteration import revise
        revise(case,u,cfg)
    weights,_=E.seismic_weights(cfg)
    periods={d:IS.approximate_Ta(height,extent,system=system,material='steel')['Ta_s']
             for d,extent,system in zip(('X','Y'),(width,length),case.system)}
    plan=IS.esm_summary(weights,cfg['heights'],seismic['Z'],importance,sd,'II',case.zone,periods)
    plan.update(jurisdiction='india',combinations='auto',retrieval=gr.hits)
    vb,k2,pz=gr.wind(case,height)
    kd=1 if case.k4>1 else .9
    area=min(u.sy,u.sx)*min(u.heights)
    ka=W.ka_for_area_m2(area)['Ka']
    pd=max(.7,kd*ka)*pz
    ws=dict(Vb_mps=vb,Vb=vb,terrain_category=case.terrain,k1=case.k1,k2=k2,k3=case.k3,k4=case.k4,
            cyclone_belt=case.k4>1,structure_class='industrial' if n in (7,8) else 'other',Kd=kd,Ka=ka,
            Ka_area_m2=area,Ka_basis='frame_tributary',Kc=1,pz_kNm2=pz,pd_kNm2=pd)
    plan['wind_summary']=ws
    mw=W.lowrise_member_wind(pd,height,min(width,length),max(width,length),degrees(atan2(2*case.rise,width)),case.openings,ridge_axis='Y')
    if (case.rise or len(u.heights)==1 or n==6) and mw.get('found'):
        plan['member_wind'] = mw['patterns']
        plan['member_wind_basis'] = {key:value for key,value in mw.items() if key!='patterns'}
        if n==2:
            from peb_iteration import canopy_wind
            plan['member_wind'] = canopy_wind(cfg,plan['member_wind'],pd,u)
    ratio_result={}
    for d,b,depth in [('X',length,width),('Y',width,length)]:
        co=W.cpe_walls(height/min(width,length),max(width,length)/min(width,length),0 if depth<=b else 90)
        pay=co.get('Cpe') or {}
        cp=((pay.get('A',.8)-pay.get('B',-.8)) if depth<=b else (pay.get('C',.8)-pay.get('D',-.8))) if pay else 1.6
        ratio_result[d]=dict(Cp_net=cp,basis=co.get('cite','IS 875 Part 3 Table 5') if pay else 'Trial 1.6 envelope; project-specific pressure coefficients require verification')
        z=0; loads={}
        for k,h in enumerate(u.heights,1):
            z+=h
            _,_,story_pz=gr.wind(case,z)
            f=max(.7,kd*ka)*story_pz*cp*b*h*1000
            loads[str(k)]=[f if d=='X' else 0,f if d=='Y' else 0,0]
        plan['story_forces']['W_'+d]=loads
    ws['wall_coefficients']=ratio_result
    from dynamic_wind import add as apply_dynamic_wind
    apply_dynamic_wind(case,u,gr,plan,ws,ratio_result)
    cfg['load_plan']=plan
    from rolled_secondary import add as select_rolled_secondaries
    select_rolled_secondaries(cfg,case,u)
    if case.rise:
        cfg['roof_pitch_deg']=degrees(atan2(2*case.rise,u.nx*u.sx))
    if n==10:
        from roof_drainage import indore
        indore(cfg)
    if n==9:
        from roof_drainage import shimla
        shimla(cfg)
    return cfg
