"""Select each physically drawn rolled secondary with the native IS 800 member module."""
import math

import design_pipeline as DP
import engine3d as E
import sections as S


def select(cfg,kind,span,spacing,family,**loads):
    rec=dict(id=kind,kind=kind,level='floor' if kind=='floor joist' else 'roof',span_mm=span,spacing_mm=spacing,
             grade=cfg['steel_grade'],LLT_sag_mm=span,LLT_hog_mm=span)
    rec.update(loads)
    names=sorted(set(lab for key in family.split('/') for lab in S.list_is808(key)),key=lambda n:S.props(n)['A'])
    assessed=[]
    for name in names:
        try:E.Ipack(name)
        except KeyError:continue  # Some historical IS 808 aliases cannot be loaded by the solver.
        r=dict(rec,section=name)
        demands=DP.secondary_member_demand(cfg,r)
        check=DP.secondary_member_checks(cfg,r,demands)
        if isinstance(check.get('DC'),(float,int)):
            assessed.append((check['DC'],r))
            if check['DC']<=.92:return r
    return min(assessed,key=lambda a:a[0])[1] if assessed else dict(rec,section=names[-1])


def add(cfg,case,u):
    if case.number<=5 or case.number==21:return
    n=case.number
    patterns=cfg['load_plan'].get('member_wind',[])
    uplift=max((abs(min(0,r['roof_windward_kNm2'],r['roof_leeward_kNm2'])) for r in patterns),default=0)
    wall=max((max(abs(r[k]) for k in ('wall_windward_kNm2','wall_leeward_kNm2','wall_side_kNm2')) for r in patterns),default=0)
    members=[]
    if n in (7,8,9):
        members.append(select(cfg,'roof purlin',u.sy*1000,case.purlin_spacing*1000,'MC',wind_uplift_kNm2=uplift,
                              LLT_sag_mm=u.sy*1000/3,LLT_hog_mm=u.sy*1000/3))
    else:
        width=case.purlin_spacing if n==6 else 2.5 if n in (10,11) else 3.
        space=u.sy/math.ceil(u.sy/width)*1000
        members.append(select(cfg,'roof joist',u.sx*1000,space,'NPB/MB/WPB',wind_uplift_kNm2=uplift))
        if len(u.heights)>1:
            floor_space=u.sy/math.ceil(u.sy/(2.5 if n==11 else 3.))*1000
            members.append(select(cfg,'floor joist',u.sx*1000,floor_space,'NPB/MB/WPB'))
    if n in (6,7,8,9,10):
        spacing=case.girt_spacing*1000
        for key,span in [('side girt',u.sy*1000),('end girt',u.sx*1000)]:
            if key=='end girt' and n in (7,8,9):span/=3
            # A girt's local major axis is perpendicular to the wall; wall pressure
            # enters as a reversible transverse load with the service pressure retained.
            members.append(select(cfg,key,span,spacing,'MC/WPB',D_kNm2=0.,L_kNm2=0.,snow_kNm2=0.,
                                  extra_cases=[{'label':'1.5 wind pressure','w_kNm2':1.5*wall,'service_w_kNm2':wall},
                                               {'label':'1.5 wind suction','w_kNm2':-1.5*wall,'service_w_kNm2':wall}]))
    cfg['secondary_members']=members
    cfg['physical_secondaries']={r['id']:r['section'] for r in members}
