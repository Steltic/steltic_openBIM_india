"""Brief-based PEB plate, joint and crane designs; geometry in mm and forces in N.

The Ex5 existing building calls exactly the Ex1 selection. Only the imposed PV
action is varied. All candidates are subsequently checked by the native pipeline.
"""
from functools import lru_cache
import math

import frame_build as FB
import hr_autosize as HR
import india_connections as C
import india_is800 as IS8
import peb_autosize as PS
import peb_build as PB
import sections as S
from special import ordered_build


@lru_cache(maxsize=None)
def end_plate(section, protected):
    p=S.props(section); fy=PS.member_web_fy(section)
    demand=(1.35 if protected else 1.22)*p["Zx"]*fy
    # Symmetric end plates: try pairs of tension bolts at the actual flange
    # face, including prying, web strip and thickness-dependent plate strength.
    grade="E350B0" if protected else "E250"
    alternatives=[]
    for d in (24,30,36):
        pitch=max(80,2.5*d); width=max(p["bf"]+60,300)
        for outside in range(1,5):
            for inside in range(1,5):
                for t in (25,32,40,50,63,75):
                    ep=PS.ep_dict(section,t=t,d_bolt=d,n_out=outside,n_in=inside,pitch=pitch,b_plate=width,
                                  grade="10.9",plate_grade=grade,ext=65,gauge=max(110,3*d),web_doubler=20)
                    positions=sorted({s*(r["h_mm"]-ep["hf_mm"]/2) for r in ep["rows"] for s in (-1,1)})
                    if any(y-x<2.5*d for x,y in zip(positions,positions[1:])):continue
                    cap=C.end_plate_moment_capacity(**ep).get("capacity_Nmm") or 0
                    h=PS.ep_height(section,outside,pitch,ext=65)
                    weight=width*h*t*7.85e-6+(inside+outside)*4*d*d*.0009
                    alternatives.append((cap>=demand,weight,cap,d,ep,outside,inside))
                    if cap>=demand: break
    passing=[a for a in alternatives if a[0]]
    choice=min(passing,key=lambda a:a[1]) if passing else max(alternatives,key=lambda a:a[2])
    _,_,_,d,ep,n_out,n_in=choice
    pitch=max(80,2.5*d)
    fabrication=dict(width_mm=max(p["bf"]+60,300),height_mm=PS.ep_height(section,n_out,pitch,ext=65),
                     gauge_mm=max(110,3*d),pitch_mm=pitch,n_out=n_out,n_in=n_in)
    n=max(i for i in range(2,13) if HR.fin_plate_fits(section,i,30))
    shear=HR.double_fin(HR.fin_plate_spec(section,n,30,32,template={"slip_surface":"sand_blasted"},n_lines=2,gauge=85),section)
    # The moment-joint interface accepts the dimensional shear model directly.
    # Bolt and weld classifications are supplied on the containing joint.
    shear={k:v for k,v in shear.items() if k in ("t_plate_mm","h_plate_mm","fy_plate_MPa","fu_plate_MPa",
           "bolts","cjp","block_shear_areas","n_plates","bolt_lines","gauge_mm","a1_mm")}
    return dict(type="end_plate",end_plate=ep,fabrication=fabrication,plate_grade=grade,weld_type="cjp",bolt_type="HSFG",
                shear=shear,symmetric=True,shear_bolts=dict(n_bolts=n*2,d_mm=30,grade="8.8",mu_f=.48,n_e=2),
                column_flange_t_mm=80,column_flange_grade="E350B0",column_web_doubler_mm=30,
                continuity_plates=True,continuity_plate_t_mm=max(32,p["tf"]),doubler_t_mm=45,doubler_grade="E250",
                cite="IS 800:2007 10.3.5, 10.4.3, 10.4.7, 12.4 and Section 12 moment provisions")


@lru_cache(maxsize=None)
def base_plate(sec,fixed,small_ring=False):
    p=S.props(sec)
    sp=HR.ring_base(sec,dict(fck_MPa=35.,plate_grade="E250",anchors={"grade":"8.8"}),
                    d=48 if fixed else 36,n=2 if small_ring else (8 if fixed else 5),
                    t=200 if fixed else 65,proj=520 if fixed else 230)
    sp["fixed"]=fixed
    if fixed:
        sp["stiffeners"]=HR._base_stiffeners(None,sp,sec)
        sp["stiffeners"].update(n_per_side=4,n_per_side_y=4,t_mm=63,h_mm=750,fy_MPa=PS.plate_fy(63,"E250"))
        sp["stiffeners"].pop("note",None)
    an=sp["anchors"]
    an["pitch_mm"]=math.floor(10*(min(sp["B_mm"],sp["L_mm"])-2*an["edge_mm"])/(an["n_per_row"]-1))/10
    # Plain anchor shanks: no 60% deformed-bar bond enhancement on bolts.
    # Soil, pedestal/cone breakout and slab reinforcement are separate foundation scope.
    sp["anchors"]["embedment"]=dict(method="bond",tau_bd_MPa=1.7,bar="plain",L_mm=2800 if fixed else 1800,
        source="Trial M35 concrete and cast-in plain-shank anchor; coordinate embedment and pedestal with foundation design.",cite="IS 456:2000 26.2.1, Table 26")
    fy=PS.member_web_fy(sec)
    vd=max((IS8.shear_capacity(p,fy,axis=axis).get("Vd_N") or 0) for axis in ("y","z"))
    dims,_=PS.size_key(1.22*vd,35,b_max=min(sp["B_mm"],sp["L_mm"]))
    if not isinstance(dims,list):
        # Fabricated cruciform key, increasing thickness/depth to develop the
        # column shear floor on each axis as called for by the project brief.
        width=min(sp["B_mm"],sp["L_mm"])-80
        dims=[width,100,650]
    b,t,h=dims
    sp["shear_key"]=PS.shear_key(b,t,h,PS.plate_fy(t,"E250"),35)
    return sp


def canopy_nodes(u):
    for j in range(u.ny+1):
        tributary_y=u.sy*(.5 if j in (0,u.ny) else 1)
        for k in range(9):
            node=7500000+j if k==0 else 7510000+100*k+j
            yield node,tributary_y*.75*(.5 if k in (0,8) else 1)


def canopy_wind(cfg,patterns,pd,u):
    # Attached-canopy net coefficients are declared project assumptions. Apply
    # both signs at the actual stations with every main-roof wind pattern.
    result=[]
    for pat in patterns:
        for suffix,cp in (("CU",-2.),("CD",1.5)):
            result.append(dict(pat,name=pat["name"]+suffix,
                nodal_loads=[dict(node=node,F=[0,0,-1000*area*cp*pd,0,0,0]) for node,area in canopy_nodes(u)],
                canopy_net_coefficient=cp,canopy_pressure_kNm2=cp*pd,
                canopy_basis="Attached canopy; net pressure envelope assumed for this fixture. Confirm upper/lower-surface pressure with project wind specialist."))
    return result


def revise(case,u,cfg):
    n=1 if case.number==5 else case.number
    if n not in (1,2,3,4):return
    cfg.setdefault("peb_rules",{})["_dump_element_inputs"]=True
    cfg.update(building_type="industrial",cladding_brittle=n in (1,2,4),deflection_key_roof="rafter_profiled_sheeting")
    # Keep the Bhiwandi outside flange above the 12 m racking envelope.
    deep,shallow,b,tf,tw={1:(1100,650,360,25,14),2:(950,650,420,32,28),
                           3:(900,600,350,25,14),4:(1050,680,420,32,30)}[n]
    taper=f"TI{deep}-{shallow}X{b}X{tf}X{tw}"
    col=f"WI{deep}X{b}X{tf}X{tw}" if n==3 else f"TI{shallow}-{deep}X{b}X{tf}X{tw}"
    if n in (2,4):
        col=f"TI{shallow}-{deep}X500X45X32"
    prism=f"WI{shallow}X{b}X{tf}X{tw}"
    g=cfg["gold"]; pl=g["roof_planes"][0]
    for name in (taper,col,prism):PB.ensure(name)
    g["peb_column"]=col
    g["moment_lines"]=[["X",j] for j in range(1,u.ny)]
    g["col_sec"]={"lateral":{"default":PB.section_at(col,.5)},"gravity":{"default":prism}}
    rafter_mid=u.nx*u.sx*500
    pl["rafter_sec"]=prism
    pl["rafter_members"]={"lo":[(u.sx*200,taper),(rafter_mid,prism)]}
    pl["rafter_members_by_line"]={str(q):{"lo":[(rafter_mid,prism)]} for q in (0,u.ny)}
    br={2:"WI400X480X36X22",4:"WI350X350X28X20"}.get(n,"CHS355.6X12")
    if br.startswith("WI"):PB.ensure(br)
    g["brace_sec"]={"1":br}
    cfg["brace"]=br
    cfg["tube_grade"]="YST310"; cfg["grade_by_section"]={"brace:"+br:"E250B0"} if n in (2,4) else {}
    longitudinal="WPB300X300X88.34" if u.sy<8 else "WPB450X300X139.76"
    if n in (2,4):
        longitudinal="WI450X320X25X16"
        PB.ensure(longitudinal)
    g["beam_sec"]=dict(floor_X=prism,floor_Y=longitudinal,roof_X=prism,roof_Y=longitudinal)
    cfg["beam"]=prism; cfg["col"]=PB.section_at(col,.5)
    pl["ridge_sec"]=longitudinal
    cfg["gable_post_section"]="WI650X500X36X24" if n in (2,4) else "WPB450X300X139.76"
    if n in (2,4):PB.ensure(cfg["gable_post_section"])
    # Longitudinal struts and ridge beams have the actual, unrestrained column
    # spacing as their LTB span; each native PEB piece gets its own D-T1 lengths.
    cfg["LLT_sag_mm"]=u.sy*1000
    cfg["LLT_hog_mm"]=u.sy*1000
    cfg["plate_grade"]="E250";cfg["steel_grade"]="E350B0"
    cfg["fly_brace_grade"]="E250"
    cfg["purlin_spacing_mm"]=900 if n==2 else case.purlin_spacing*1000
    cfg["girt_spacing_mm"]={2:1000,4:1200}.get(n,case.girt_spacing*1000)
    half=u.nx*u.sx*500
    count=math.ceil(half/cfg["purlin_spacing_mm"])
    points=[half*i/count for i in range(1,count)]
    near=[x for i,x in enumerate(points,1) if x<=(5000 if n==3 else 6000) or not i%2 or
          (n==2 and min(abs(x-i*u.sx*1000) for i in range(1,u.nx))<=6000)]
    cfg["flange_braces"]["rafter"]={"purlins_mm":points,"fly_braces_mm":near}
    h=sum(u.heights)*1000; low=3000 if n in (1,2,4) else 0
    bays=math.ceil((h-low)/cfg["girt_spacing_mm"])
    girts=[low+i*(h-low)/bays for i in range(0 if low else 1,bays)]
    cfg["flange_braces"]["column"]={"girts_mm":girts,"fly_braces_mm":girts}
    cfg["flange_braces"]["members"]={"default":dict(section="ISA100X100X10",grade="E250",L_mm=1500,
        angle_deg=45,n_bolts=2,fixity="hinged",bolt=dict(d_mm=20,d0_mm=22,grade="8.8",t_mm=8,fu_plate_MPa=410,e_mm=40,p_mm=65))}
    if n==2:
        cfg["canopy_axis_height_mm"]=5850
        cfg["roof_pitch_deg"]=math.degrees(math.atan2(case.rise,u.nx*u.sx/2))
        cfg["flange_braces"]["canopy"]={"purlins_mm":[750*i for i in range(1,8)],"fly_braces_mm":[750*i for i in range(1,8)]}
        g["interior_peb_col"]="WI600X450X32X20";PB.ensure(g["interior_peb_col"])
        g["sfrs_base"]={"default":"fixed",**{f"{i},{j}":"pinned" for i in range(1,u.nx) for j in range(u.ny+1)}}
        cfg["nodal_dead_loads"]=[dict(node=node,level=1,Fz_N=-.2*area*1000,note="Roofing and purlins on canopy") for node,area in canopy_nodes(u)]
        cfg["nodal_imposed_loads"]=[dict(node=node,level=1,kind="roof",Fz_N=-.75*area*1000,note="Canopy maintenance imposed load") for node,area in canopy_nodes(u)]
        # Put the 8 tapered beam pieces' steel on these same stations precisely
        # once. Off-diaphragm members with nodal dead load require this in O2.
        canopy_label="TI700-300X300X20X12";PB.ensure(canopy_label)
        own_weight={}
        for j in range(u.ny+1):
            nodes=[7500000+j]+[7510000+k*100+j for k in range(1,9)]
            for k,(a,bb) in enumerate(zip(nodes,nodes[1:])):
                section=PB.section_at(canopy_label,(k+.5)/8)
                half=S.props(section)["A"]*750*7.85e-5/2
                for nd in (a,bb):own_weight[nd]=own_weight.get(nd,0)+half
        for load in cfg["nodal_dead_loads"]:
            load["Fz_N"]-=own_weight[load["node"]]
            load["note"]+=" and adjacent half-piece steel weights"
        cfg["self_weight_in_nodal_loads"]={"sections":[PB.section_at(canopy_label,(k+.5)/8) for k in range(8)],
            "cite":"IS 875 Part 1 structural steel unit weight; Steltic O2","note":"Each off-diaphragm canopy piece contributes both half weights at actual stations."}
    if n in (2,4):
        cfg["beam_lateral_bracing"]={"default":{"near_end_mm":1500,"elsewhere_mm":3000,
            "basis":"Both flange levels tied to the purlin / plan-bracing line at the scheduled fly braces."}}
        cfg["column_lateral_support_both_flanges"]=True
    # Rebuild native section callbacks after replacing design variables.
    FB.attach_gold(cfg,g); cfg["custom_build"]=ordered_build
    protected=n in (2,4)
    conn=cfg["connections"]
    knee=PB.section_at(taper,0)
    bc={sec:end_plate(sec,protected) for sec in (knee,prism)}
    bc["default"]=bc[knee]
    conn["beam_column"]=bc
    conn["rafter_splice"]={prism:end_plate(prism,protected),"default":end_plate(prism,protected)}
    if n==2:
        canopy="WI700X300X20X12";PB.ensure(canopy)
        conn["rafter_splice"]["canopy_root"]=end_plate(canopy,False)
    conn["knee_panel"]={"doubler_t_mm":30,"doubler_grade":"E250",
                        "diagonal_stiffener":{"b_mm":min(180,b/2-20),"t_mm":40,"n":2,"grade":"E250"},
                        "flange_stiffener":{"b_mm":min(180,b/2-20),"t_mm":45,"n":2,"grade":"E250"}}
    conn["brace_end"]={br:HR.brace_end_chs_spec(br,55 if n==2 else 40,1550 if n==2 else 1350 if protected else 700)}
    base_face=PB.section_at(col,0); bp=base_plate(base_face,n in (2,3,4),n==1)
    conn["column_base"]={"default":bp,base_face:bp,prism:base_plate(prism,False,n==1),
                         cfg["gable_post_section"]:base_plate(cfg["gable_post_section"],False,n==1)}
    # Supply explicit base geometry for the segment-centre label used by the
    # native connection record without replacing the actual selected face plate.
    conn["column_base"][PB.section_at(col,1/16)]=bp
    conn["column_splice"]={"default":{"none":True,"note":"Full-height, shop-fabricated column; no field splice."}}
    conn["beam_shear"].update({prism:HR.fin_plate_spec(prism,5,24,20,template={"slip_surface":"sand_blasted"},n_lines=2),
                               longitudinal:HR.fin_plate_spec(longitudinal,3,20,16,template={"slip_surface":"sand_blasted"})})
    if n==2:
        interior=dict(base_plate(g["interior_peb_col"],False),t_plate_mm=110,fy_plate_MPa=PS.plate_fy(110,"E250"))
        interior["anchors"]=dict(interior["anchors"],embedment=dict(interior["anchors"]["embedment"],L_mm=2200))
        conn["column_base"][g["interior_peb_col"]]=interior
        for i in range(8):
            face=PB.section_at("TI700-300X300X20X12",(i+.5)/8)
            conn["beam_shear"][face]=HR.fin_plate_spec(face,3,20,16)
    if n==3:
        gantry="WPB600X300X177.78"; bracket="WI550X280X22X12";PB.ensure(bracket)
        cr=cfg["crane"]
        station=(PB.COL_K0+1)*100000
        cr["bracket_nodes"]={"L":station+u.ny//2,"R":station+100*u.nx+u.ny//2}
        cr.update(gantry_section=gantry,gantry_grade="E250",gantry_LLT_mm=u.sy*1000,rail_weight_N_per_mm=.30)
        dead=(S.props(gantry)["A"]*7.85e-5+.30)*u.sy*1000
        cr["bracket"]={"section":bracket,"projection_mm":cr["bracket_eccentricity_mm"]-deep/2,
                       "rail_height_mm":S.props(gantry)["d"]+75,"dead_N":dead,"weld_leg_mm":12,"electrode_fu_MPa":410,
                       "gamma_mw":1.25,"grade":"E250","column_section":col,
                       "column_stiffeners":{"b_mm":120,"t_mm":20,"n":2,"grade":"E250"}}
        cfg["nodal_dead_loads"]=[row for row in cfg["nodal_dead_loads"] if 0<row["node"]%100<u.ny]
        for row in cfg["nodal_dead_loads"]:
            j=row["node"]%100
            row["node"]=station+row["node"]%100000
            row["Fz_N"]=-dead*(.5 if j in (1,u.ny-1) else 1)
