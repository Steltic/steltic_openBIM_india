"""Construct fresh Steltic CFS inputs from each active Indian building brief."""
import math
from pathlib import Path

from grounding import retrieve, terrain_category


DEFLECT = "IS 800:2007 Table 6; project adopts L/360 floors and L/240 cladding"
COLD = "IS 1079 material specified at Fy >= 250 MPa, mill certificate required; IS 801:1975 Table 2"


def joint_specs(brace_section):
    import csv
    import india_cfs_env
    with (Path(india_cfs_env.__file__).parent/"hr_vendor"/"is808_shapes.csv").open(encoding="utf-8-sig") as f:
        brace=next(r for r in csv.DictReader(f) if r["Label"]==brace_section)
    area=float(brace["A_si_mm2"])
    zp=float(brace["Zpz_mm3"])
    # Capacity-protected splice plates are developed independently of the
    # frame demands, from expected yield of the selected brace.
    bolt_n=2*math.ceil(area*410*1.2/(2*178000))
    weld_len=math.ceil(area*410*1.2/(4*.8*float(brace["tf_mm"])*240/1.1/math.sqrt(3))/25)*25
    bolt=dict(d_mm=24,grade="8.8",t_mm=14,fu_plate_MPa=410,e_mm=42,p_mm=66,d0_mm=26)
    bolts=dict(bolt,n_bolts=8,nn=2)
    fin=dict(t_plate_mm=36,n_plates=2,h_plate_mm=340,fy_plate_MPa=250,fu_plate_MPa=410,
             bolts=bolts,cjp=dict(t_mm=18,length_mm=340,fy_MPa=250,n_sides=2),
             block_shear_areas=dict(Avg_mm2=8640,Avn_mm2=5364,Atg_mm2=2376,Atn_mm2=1908))
    # Two gussets, paired field splice. Scale the net/gross steel areas to
    # the expected brace strength; dimensions follow from the selected stock.
    gt=math.ceil((area/6500)*22/5)*5
    br_d=30; br_hole=33; br_pitch=80; br_edge=58
    nlong=min(8,math.ceil(math.sqrt(bolt_n*1.4))); nwide=math.ceil(bolt_n/nlong)
    gwidth=max(450,(nwide-1)*br_pitch+2*br_edge); glength=max(720,(nlong-1)*br_pitch+2*br_edge)
    gusset=dict(t_mm=gt,fy_MPa=230,fu_MPa=410,w_start_mm=gwidth,L_conn_mm=glength,
                L_unbraced_mm=200,K=1,Avg_mm2=2*glength*gt,Avn_mm2=2*(glength-(nlong-.5)*br_hole)*gt,
                Atg_mm2=gwidth*gt,Atn_mm2=(gwidth-(nwide-.5)*br_hole)*gt)
    base=dict(B_mm=1600,L_mm=1600,t_plate_mm=150,fy_plate_MPa=230,fck_MPa=30,fixed=True,
              anchors=dict(n_total=24,n_tension=12,d_mm=36,grade="8.8",f_mm=650,
                           f_y_mm=650,n_tension_y=12,pitch_mm=90,edge_mm=60,n_per_row=6,d0_mm=40,
                           x_mm=[-740,-650,-560,560,650,740],y_mm=[-705,-595,595,705],
                           embedment=dict(method="bond",tau_bd_MPa=1.8,bar="plain",L_mm=2600,
                               source="Declared foundation performance assumption; verify grouted bond and full anchor load path",
                               cite="Project input to IS 456 development-length bond model; VERIFY with foundation designer")),
              stiffeners=dict(layout="cross",n_per_side=3,n_per_side_y=3,t_mm=55,h_mm=650,
                              fy_MPa=230,weld_column=dict(type="cjp"),weld_plate=dict(type="cjp")),
              shear_key=dict(t_mm=160,fy_MPa=230,grade="E250",capacity_N=min(900*350*13.5,900*160*230/(math.sqrt(3)*1.1),900*160**2/6*230/1.1/175),
                             source="Project 900 x 350 x 160 mm lug each axis; verify local concrete breakout and restraint",
                             cite="Minimum of provisional concrete bearing 13.5 MPa, IS 800 steel shear and elastic bending"),
              plate_grade="E250 B0")
    return dict(beam_shear={"default":dict(fin,bolt_type="HSFG",weld_type="cjp",slip_surface="sand_blasted",mu_f=.48)},
                beam_column={"default":dict(type="welded_cover_plate",weld_type="cjp",bolt_type="HSFG",shear=fin,continuity_plates=True,
                       cover_plate=dict(plate_b_mm=260,plate_t_mm=55,fy_plate_MPa=230,plate_grade="E250",
                                        weld=dict(size_mm=14,length_mm=3200,fu_MPa=410,site=False)),
                       continuity_plate_t_mm=40,doubler_t_mm=90)},
                column_base={"default":base},column_splice={"default":dict(type="cjp",
                     weld=dict(matching_electrode=True,electrode="matched IS 814 certified consumable",type="cjp"))},
                brace_end={"default":dict(weld_type="cjp",bolt_type="HSFG",
                    welds=dict(cjp=dict(t_mm=float(brace["tf_mm"]),fy_MPa=240),length_mm=weld_len,n_sides=4),
                    bolts=dict(bolt,n_bolts=bolt_n,d_mm=br_d,d0_mm=br_hole,p_mm=br_pitch,e_mm=br_edge,t_mm=gt,
                               mu_f=0.45,n_e=2),gusset=gusset,detailing=dict(nlong=nlong,nwide=nwide),
                    An_mm2=area, # field bolts through twin splice plates; full welded brace section
                    moment_capacity_Nmm=zp*250/1.10,
                    slip_surface="sand_blasted",mu_f=.48,
                    bolts_and_welds_share=False)})


def beam(section="auto", **values):
    spec=dict(section=section,bearing_mm=100,deflection_limit_ratio=240,deflection_cite=DEFLECT,
              bracing=dict(type="sag_rods",lines=3,min_rod_dia_mm=16,rod_dia_mm=20,members_per_line=5))
    if section=="auto":
        spec["auto_select"]=dict(family="IS811_CLR")
    spec.update(values)
    return spec


def make_config(b, corpus, job):
    n=b.number
    hits,vb,z,k2=retrieve(corpus,job,b)
    nx,ny=len(b.x)-1,len(b.y)-1
    bx=max(v-u for u,v in zip(b.x,b.x[1:]))
    by=max(v-u for u,v in zip(b.y,b.y[1:]))
    belt=n in (1,5,13)
    site=dict(city=b.site,zone=b.zone,Z=z,soil=b.soil,Vb=vb,Vb_source="Annex A",zone_source="Annex E",
              terrain_category=terrain_category(b),k1=1,k3=1,k2_table=k2,Kc=1,Kd=1 if belt else .9,cyclone_belt=belt,
              cyclone_belt_cite="IS 875-3:2015 cl. 6.3.4; city-centre location, check project coastline distance",
              wind_structure_class="industrial" if n in (1,2,3,4) else "other")
    if n==14:
        site.update(Vb_source="site_proxy",zone_source="derived_from_map",lat=28.54,long=77.39,
                    Vb_site_proxy=dict(proxy_town="Delhi",distance_km=20,basis="same isotach, Fig. 1 per brief",
                                       verify=True,annex_found=False,corpus_status="not_tabulated"))
    roof_pitch=math.degrees(math.atan2({1:1.5,2:1.0,3:1.4,4:1.2,8:1,9:1.25,11:1.6}.get(n,0),{1:9,2:10.5,3:6,4:12,8:7,9:8,11:9.5}.get(n,1)))
    # Project envelopes used uniformly where the native frame accepts a single floor load.
    imposed={3:8.0,4:4.0,6:5.0,9:4.0,11:4.0,13:4.0,15:4.0}.get(n,3.0)
    roof_dead=(0.60 if n in (1,3,4) else 0.90 if n==2 else 1.35 if n==13 else 1.0)
    floor_dead=1.65
    s0=1.624*(4-0.5)*(1+(1585/2677)**2) if n==2 else 0.0
    snow=.8*s0
    loads=dict(D_floor=floor_dead,D_roof=roof_dead,L_floor=imposed,
               Lr=4.0 if n==11 else max(.4,.75-.02*max(0,roof_pitch-10)),clad=.35,
               partition_design_kNm2=1.0,partition_seismic_kNm2=1.0,snow=snow,
               cite="IS 875-1:2026 project build-up; IS 875-2:1987 Tables 1 and 2; IS 1893:2016 7.3.6")
    sf=dict(applicable=bool(snow),s0_kPa=s0,roof_snow_kNm2=snow,source="IS 875-4 Annex A-3; Figure 1 zone requires confirmation" if snow else "Outside snow region in brief")
    plan=dict(jurisdiction="india",design_basis="IS801_WSM",lateral_frame_basis="IS800_LSD",
              combinations="auto",cfs_combinations="auto",retrieval=hits,snow_summary=sf)
    L=len(b.heights)
    occupancy=dict(use=b.use,area_m2=sum(b.area(k) for k in range(1,L+1)),educational=False,hospital=False,food_storage=n==2)
    if n==4: occupancy["persons"]=90
    if n==7: occupancy["persons"]=64
    geo=dict(plan_x_m=b.x[-1],plan_y_m=b.y[-1],heights_m=b.heights,opening_ratio=.32 if n==4 else .04,
             floor_area_m2={str(k):b.area(k) for k in range(1,L+1)})
    if n in (1,2,3,4,8,9,11):
        geo["roof_pitch_deg"]=roof_pitch
    cm=dict(Fy_MPa=250,grade_cite=COLD,coating="Hot-dip galvanize after forming; repair cut edges. Verify coating exposure and compatibility.")
    if n>=4:
        # No manufacturer stiffness or fastener test certificate is supplied.
        # Design non-bearing studs over their full unbraced height.
        cm["studs"]=dict(section="auto",auto_select=dict(family="IS811_CLR"),spacing_mm=400,
                         bearing=False,cladding_kNm2=.35,zone="all")
        cm["joists"]=beam(spacing_mm=400,span_mm=by*1000,compression_flange_restrained=True,
                          deflection_limit_ratio=360,L_kNm2=imposed,L_cite="IS 875-2 Table 1 project occupancy envelope")
    if n==9:
        cm["headers"]=beam("CLR140X60X20X3.15",n_ply=2,span_mm=1500,w_dead_kN_per_m=.65,w_live_kN_per_m=0,
                load_cite="1.35 m cladding at 0.35 kN/m² plus 0.18 kN/m lintel, glazing trim and jamb reaction allowance",
                deflection_limit_ratio=360)
    span=(5 if n==3 else bx)*1000
    cm["purlins"]=beam(spacing_mm=1000 if n==2 else 1500,span_mm=span,
                          roof_pitch_deg=roof_pitch,compression_flange_restrained=True,zone="all")
    if n in (11,14,15):
        cm["purlins"].update(n_ply=2,spacing_mm=1000)
    if n in (1,2,3,4,5,13):
        cm["girts"]=beam(spacing_mm=400 if n in (5,13) else 1500,span_mm=span,zone="all")
        if n==2:
            cm["purlins"].update(n_ply=2,point_loads=[dict(P_kN=1.5,a_m=bx/2,kind="D",
                cite="Refrigeration layout allowance, verify actual suspended evaporator reactions")])
    if n in (1,2,3):
        eave_force=.6*vb**2/1000*(1.15 if n==1 else 1)**2*max(1,float(k2['10']))**2*1.6*(sum(b.heights)+1)*({1:18,2:21,3:24}[n])/2*1000
        cm["eave_struts"]=beam("CLR250X80X25X5",n_ply=2,span_mm=(5 if n==3 else bx)*1000,
                             P_N=eave_force,P_cite="Upper envelope of full gable force, two side collectors; net coefficient 1.6, no area or direction reduction",
                             L_unbraced_mm=1200)
    cfg=dict(name=f"IN_CFS_Ex{n}",jurisdiction="india",units="m",design_basis="IS801_WSM",site=site,
             occupancy=occupancy,geometry=geo,loads=loads,load_plan=plan,cfs_members=cm,drift_limit=.004,
             eor_inputs=[dict(item="Soil profile and terrain",value=f"{b.soil}; terrain {terrain_category(b)}",
                              source="Brief when stated, otherwise project assumption; confirm geotechnical report and upwind exposure",verify=True),
                         dict(item="Sheathing and fastening certificates",value="pending",
                              source="Confirm actual tested assembly; non-bearing studs calculated without sheathing restraint",verify=True),
                         dict(item="Concrete grade and anchorage",value="M30 provisional",
                              source="Verify project foundation and bond assumptions, pedestal reinforcement and group breakout",verify=True)],
             delegated_design=[dict(item="Concrete breakout and pedestal design",responsible="foundation engineer",
                       criteria="Verify group cone, edge distances, spacing, pedestal reinforcement and shear transfer against concurrent reactions; verify grout bond input.",
                       interface_forces="Concurrent column N, M, V and individual anchor tension/shear from the native base checks; include IS 800 12.12 and IS 18168 9.3 capacity-design cases.")])
    if n==7:
        performance="Both faces, fasteners at 200 mm, per-face minimum Kw 60 N/mm, allowable lateral resistance 1.0 kN per fastener. Verify assembly test and coating compatibility."
        cfg["eor_inputs"][1].update(value=performance,source="Project performance specification for the two-face sheathing required by the Delhi brief. VERIFY supplier test results.")
        cm["studs"]["sheathing"]=dict(both_faces=True,a_mm=200,Kw_N_per_mm=60,fastener_lateral_capacity_N=1000,
                                     source=performance,fastener_source=performance)
    cleat=dict(bolts=dict(n=3,d_mm=16,**{"class":"8.8"},edge_mm=30,pitch_mm=48),
               cleat=dict(t_mm=14,fy_MPa=250,width_mm=160,bolt_height_mm=55,weld_mm=6),roof_pitch_deg=roof_pitch)
    if cm.get("purlins"):
        cfg["cfs_connections_spec"]={"purlin_cleat":cleat}
    if n==3:
        return portal(cfg,b)
    tall=L>=5
    col="WPB650X300X293.39" if n==1 else "WPB400X400X239.62"
    girder="WPB450X300X171.12" if n in (1,2) else "WPB400X300X155.26" if tall else "WPB360X300X163"
    brace="WPB250X250X117.58"
    if n==1: brace="WPB300X300X117.03"
    if n==4: brace="WPB400X400X239.62"
    if n==2:
        col="WPB800X300X317.36";girder="WPB650X300X293.39";brace="WPB300X300X237.92"
    if n==14:
        col="WPB800X300X317.36";girder="WPB600X300X285.48";brace="WPB300X300X237.92"
    dirs={str(k):b.braces(k) for k in range(1,L+1)}
    if n==7:
        for k in dirs:
            dirs[k]=[v for v in dirs[k] if not (v[0]=="X" and v[1]==1)]+[["Y",1,0],["Y",1,1]]
    if n==14:
        for k in (1,2):
            dirs[str(k)]=[list(br) for br in sorted(set(map(tuple,dirs[str(k)]+dirs["3"])))]
        # Distributed bracing in wing/return lines reduces axial overturning
        # at individual podium columns. Carry every added brace to the foundations.
        for k in range(1,L+1):
            nodes=b.nodes(3)
            additional=[]
            for i,j in sorted(nodes):
                if (i+1,j) in nodes and j in (0,2,4,6,8): additional.append(("X",i,j))
                if (i,j+1) in nodes and i in (0,1,2,6,7,8): additional.append(("Y",i,j))
            dirs[str(k)]=[list(br) for br in sorted(set(map(tuple,dirs[str(k)]))|set(additional))]
    present={str(k):sorted(b.nodes(k)) for k in range(1,L+1)}
    if n==4:
        present["0"]=sorted(b.nodes(2))
    moments=[["Y",i] for i in range(nx+1)] if n in (1,2) else []
    system={1:"SCBF+SMF",2:"EBF+SMF",4:"OCBF",5:"OCBF",12:"OCBF"}.get(n,"SCBF")
    gold=dict(xcoords_m=b.x,ycoords_m=b.y,present=present,plan_area_m2=geo["floor_area_m2"],
              xbays=dirs,moment_lines=moments,gravity_base="fixed",sfrs_base="fixed",default_strong="X")
    if n==6:
        shelf=sorted(b.nodes(2)-b.nodes(1))
        gold.update(stepped_bases={"1":shelf},omit_beams_at={"1":shelf},free_nodes={"1":shelf})
    if n==9:
        gold["roof_regions"]={"3":[list(c) for c in sorted(b.cells(3)-b.cells(4))]}
    if n==15:
        tiers={"1-3":col,"4-6":"WPB300X300X237.92","7-8":"WPB250X250X117.58"}
        gold["col_sec"]={"lateral":tiers,"gravity":tiers}
    if n in (1,2):
        gold["roof_planes"]=[dict(axis="Y",eave_coords_m=[0,b.y[-1]],ridge_coord_m=b.y[-1]/2,
                         eave_z_m=b.heights[-1],ridge_z_m=b.heights[-1]+(1.5 if n==1 else 1),
                         lines=list(range(nx+1)),rafter_sec=girder,ridge_sec="NPB400X180X57.38")]
    if n in (4,8,9,11):
        strips={4:[(0,30,0,24,1.2)],8:[(0,43,26,40,1),(14.5,28.5,0,26,1.5)],9:[(0,40,4,20,1.25)],11:[(0,55,27,46,1.6)]}[n]
        gold["roof_planes"]=[dict(axis="Y",eave_coords_m=[y,Y],ridge_coord_m=(y+Y)/2,
              eave_z_m=b.elevations[-1],ridge_z_m=b.elevations[-1]+rise,
              lines=[i for i,v in enumerate(b.x) if x<=v<=X],rafter_sec=girder,ridge_sec=girder)
              for x,X,y,Y,rise in strips]
    if n==2:
        gold.update(xbays={},ebf_bays=dirs,e_link_mm=650,ebf_beam_column_pinned=True,ebf_beam_sec={"X":{"1":"WPB400X400X239.62"}},
                    ebf_link_sec={"X":{"1":"WPB400X400X239.62"}},ebf_brace_sec={"1":brace})
    lf=dict(system=system,NX=nx,NY=ny,bay_x_m=bx,bay_y_m=by,col=col,beam=girder,brace=brace,
            steel_grade="E250 C" if n==2 else "E250 B0",brace_grade="E250 C" if n==2 else "E250 B0",brace_process="hot-rolled",
            braced_bays=dirs["1"],moment_lines=moments,base="fixed",deck_span="Y",diaphragm="rigid",
            connections=joint_specs(brace),gold=gold,custom_build_module="india_cfs_frame_build",
            d_x_m=b.x[-1],d_y_m=b.y[-1],LLT_sag_mm=1500,LLT_hog_mm=1500)
    if n>=4:
        # These are specified performance minima of the benchmark assembly,
        # not source test results. Actual construction requires certification.
        lf["diaphragm_stiffness"]=dict(type="custom",Gd_kN_per_m=3600,source="Preliminary project performance specification, VERIFY by full assembly test",
                                      cite="18 mm board equivalent shear modulus 200 MPa incl. joint slip; IS 1893 Table 5(ii) sensitivity")
        required=24 if n in (11,13,14) else 12
        cfg["diaphragm_capacity"]=dict(v_allow_kN_per_m=required,allowable_increase=1.0,basis="EOR_input",
                source="Specified minimum for preliminary benchmark; verify tested configuration and fastening pattern",
                cite="Project performance specification; IS 801 cl. 9.1.4 product test required")
        cfg["eor_inputs"].append(dict(item="Floor diaphragm proposed performance",value=f"Gd 3600 kN/m, allowable shear {required} kN/m",
                              source="Specified performance only; verify tested shear and in-plane stiffness, including slip",verify=True))
        if n in (4,5,8,9,11,14):
            lf["diaphragm_stiffness"]["mesh"]=1
            cfg["eor_inputs"].append(dict(item="Membrane discretisation",value="One membrane cell per real structural bay",
                        source="Check against the refined two-by-two response and the IS 1893 modal mass requirement",verify=True))
        if n==14:
            lf["hr_cfg_extra"]={"D_by_level":{"1":4.5,"2":5.0},"L_by_level":{"1":4.0,"2":5.0}}
            lf["diaphragm_stiffness"]["by_level"]={"1-2":dict(type="metal_deck",topping_t_mm=100,fck_MPa=30,
                    source="Design requirement: composite podium with 100 mm structural M30 concrete topping; confirm deck supplier",
                    cite="Preliminary IS 456 concrete modulus, verify deck and shear connection")}
    if n in (1,2,4):
        lf["hr_cfg_extra"]={"beam_lateral_bracing":dict(near_end_mm=900,elsewhere_mm=1500,
                basis="Both compression flanges restrained by purlin/secondary and 60 x 60 x 6 fly stays at the declared spacing; verify local attachment capacity.")}
        lf.update(system_x={1:"SCBF",2:"EBF",4:"OCBF"}[n],system_y="SMF" if n<4 else "OCBF",
                  R_x={1:4.5,2:5,4:4}[n],R_y=5 if n<4 else 4)
    if n in (1,2,4,8,9,11):
        lf["custom_build_module"]=str(Path(__file__).with_name("brief_frame.py").resolve())
        gold["benchmark_geometry"]={1:"shed",2:"cold_shed",4:"high_bay",8:"wing_truss",9:"west_truss",11:"wing_truss"}[n]
    if n in (1,2):
        # Roof sheets on purlins (insulated/sliding clips at Srinagar) do
        # not establish a rigid membrane. Native H3 envelopes tributary line
        # shears with all available analysed steel-frame reactions.
        lf["diaphragm"]="flexible"
        restraint=b.heights[0]*500
        lf["hr_cfg_extra"]["member_overrides"]={"col:"+col:dict(Ly_mm=restraint)}
        cfg["eor_inputs"].append(dict(item="Longitudinal column restraint at midheight",value=f"{restraint:g} mm",
            source="Provide positive restraint from both column flanges to the continuous sidewall girt and braced bays; verify attachment forces.",verify=True))
        # Preliminary roof-plane rod/brace diaphragm resistance per metre.
        # Use elastic Euler compression / 4 and gross working yield / 2 as
        # conservative caps. The native IS 800 member and connection checks
        # independently govern if either strength is lower. Use the weaker
        # axis projection of compression-capable crossed steel members.
        import csv,india_cfs_env
        roof_shape=brace if n==1 else "ISA200X200X20"
        with (Path(india_cfs_env.__file__).parent/"hr_vendor/is808_shapes.csv").open(encoding="utf-8-sig") as f:
            row=next(r for r in csv.DictReader(f) if r["Label"]==roof_shape)
        rise=1.5 if n==1 else 1/3; half=b.y[-1]/(2 if n==1 else 6)
        ld=math.sqrt(bx**2+half**2+rise**2)
        pred=min(math.pi**2*200000*float(row["Iyy_si_mm4"] if n==1 else row["Ivv_mm4"])/(1000*ld)**2/4,
                 float(row["A_si_mm2"])*230/2)
        bays=4
        flow=2*bays*pred/1000*min(bx,half)/ld/max(b.x[-1],b.y[-1])
        cfg["diaphragm_capacity"]=dict(v_allow_kN_per_m=flow,allowable_increase=1.,basis="EOR_input",
            source=f"{bays} braced bays per side, two compression-capable crossed rolled members per bay. Multiply min(Euler/4, Ag*230/2) by {2*bays}, project on weaker axis and divide by longest transfer edge. No sheet strength credited.",
            cite="IS 800 steel-brace member and connection verification; separately calculated conservative allowable shear as project input")
        cfg["eor_inputs"].append(dict(item="Longitudinal roof X-bracing flow",value=f"{flow:.3f} kN/m, brace length {ld:.3f} m",
                source="Computed from actual section and geometry; verify collector paths and full-scale bracing connections",verify=True))
    if n in (2,4,8,9,11):
        if n==9: gold["roof_planes"][0]["rafter_sec"]="NPB240X120X34.32"
        lf.setdefault("hr_cfg_extra",{})["truss_connections"]=dict(default=dict(n_bolts=6,d_mm=24,d0_mm=26,grade="8.8",pitch_mm=70,
            end_mm=48,gauge_mm=65,gusset_t_mm=28,gusset_grade="E250",gusset_edge_mm=55,edge="rolled",fixity="hinged",gusset_K=1.0,gusset_free_mm=120),
            heel=dict(n_bolts=4,d_mm=20,d0_mm=22,grade="8.8",pitch_mm=60,end_mm=40,t_plate_mm=20,fu_plate_MPa=410,nn=1,ns=0))
        if n==2:
            lf["hr_cfg_extra"]["snow_partial"]={"axis":"Y"}
            fin=lf["connections"]["beam_column"]["default"]["shear"].copy()
            fin.update(t_plate_mm=40,h_plate_mm=490,bolts=dict(n_bolts=16,d_mm=30,grade="8.8",t_mm=40,
                    fu_plate_MPa=410,e_mm=55,p_mm=80,d0_mm=33,nn=2),
                    cjp=dict(t_mm=25,length_mm=490,fy_MPa=250,n_sides=2),
                    block_shear_areas=dict(Avg_mm2=2*295*40,Avn_mm2=2*(295-3.5*33)*40,
                                           Atg_mm2=240*40,Atn_mm2=(240-2.5*33)*40))
            lf["connections"]["beam_column"]["default"]["shear"]=fin
    cfg["lateral_frame"]=lf
    if n==2:
        cfg["eor_inputs"].append(dict(item="Figure 1 snow zone",value=4,source="Brief high-side sensitivity; requires site map confirmation",verify=True))
        aux=beam("CLR250X80X25X5",n_ply=2)
        cfg["lean_to"]=dict(name="Airlock",width_m=4,depth_m=3,roof_z_m=3.6,upper_roof_z_m=8,
            upper_roof_length_m=21,upper_roof_pitch_deg=roof_pitch,D_roof_kNm2=.9,
            wall_kNm2=.35,joists=dict(aux,spacing_mm=400),front_wall_height_m=3.5,
            door=dict(width_m=2,height_m=2.4,header=aux,jambs=aux),back_studs=dict(aux,spacing_mm=400))
        cfg["roof_platforms"]=[dict(name="Condenser",frames=[2,3],eave_line=0,span_m=bx,posts_from_column_m=[2,4],
            beam_trib_m=1.0,deck_kNm2=.65,units=[dict(P_kN=5,a_m=bx/2)],unit_cite="Provisional equipment reaction; verify supplier",
            height_above_roof_m=.6,snow_on_platform=True,beams=dict(aux,deck_restrains_top=True),
            posts=dict(aux,height_mm=600))]
    return cfg


def portal(cfg,b):
    cm=cfg["cfs_members"]
    # The paired IS 811 rolled outline stays fixed. For this elastic portal
    # specify a higher minimum yield and keep procurement verification visible.
    cm.update(Fy_MPa=345,grade_cite="Specify sheet minimum Fy 345 MPa; IS 801 Table 2 allowable stress band; obtain certified yield, ductility and formed-member coupon records.")
    cfg["eor_inputs"].append(dict(item="Portal coil procurement",value="minimum Fy 345 MPa",
            source="Project material specification, verify sheet grade, elongation and formed-section certificates",verify=True))
    import is811_sections as S
    candidates=[S.props(s) for s in S.list_labels() if s.startswith(("CLR","CLS"))]
    heavy=max(candidates,key=lambda s:s["Ix"])["label"]
    pair=dict(section=heavy,n_ply=2,connector_spacing_mm=180,L_unbraced_mm=1200)
    cfg.update(all_cfs_portal=True,portal=dict(spans_m=[12,12],eave_m=7,apex_m=8.4,spacing_m=5,
        length_m=30,n_frames=7,girt_spacing_m=1.4,purlin_spacing_m=1.25,base="fixed",opening_ratio=.04,
        seismic_basis="elastic_R1",knee_brace=dict(col_below_eave_m=3.5,raf_from_knee_m=3.4)))
    cm.update(columns=pair,rafters=pair,knee_braces=dict(section=heavy,n_ply=2),
              joists=beam("CLR200X80X25X4",span_mm=3000,spacing_mm=400,compression_flange_restrained=True,
                         deflection_limit_ratio=360,D_kNm2=1.65,L_kNm2=12.0,partition_kNm2=0,
                         L_cite="IS 875-2 Table 1 viii(a). Envelop the 8 kPa stock load and 7 kN concentrated load on one 3 m joist at 0.4 m spacing: 2P/(L s) = 11.67 kPa, adopt 12.0. Covers end reaction, midspan moment and 0.7 m edge cantilever moment."))
    cfg["mezzanine"]=dict(span_index=0,height_m=3.5,depth_m=8,support="independent_posts",lateral="own_bracing",
        D_kNm2=1.65,L_kNm2=8.0,L_cite="IS 875-2 Table 1 viii(a), 7.5 kPa minimum. Proposed goods up to 3 m high and total contents up to 8 kPa, verify inventory and loading equipment.",
        posts=dict(pair,trib_m2=12),beams=dict(pair,span_mm=4000,trib_width_mm=2650,bearing_mm=120,
                     compression_flange_restrained=True,deflection_limit_ratio=360,deflection_cite=DEFLECT),
        bracing=dict(section="EA60X60X4",bay_m=3,n_braced_bays_x=2,n_braced_bays_y=2,tension_only=True))
    cfg["eor_inputs"].append(dict(item="Mezzanine inventory",value="8 kPa storage, 3 m maximum stacking, 7 kN single concentrated load",
             source="IS 875-2 Table 1 viii(a), PDF p. 13. Verify goods density, operating weight, local deck patch resistance and handling equipment prior to use.",verify=True))
    cfg["longitudinal_bracing"]=dict(section="CLR100X50X15X2",n_braced_bays=2,tension_only=True)
    bolts=dict(rows=3,cols=5,pitch_mm=65,gauge_mm=65,d_mm=20,edge_mm=35,bolt_class="8.8")
    base=dict(B_mm=650,L_mm=650,t_plate_mm=60,fy_plate_MPa=230,bearing_permissible_MPa=3.0,
              bearing_cite="Proposed project permissible bearing 3.0 MPa on specified M30 pedestal; foundation designer to VERIFY",
              anchors=dict(n_total=8,n_tension=4,d_mm=30,grade="8.8",f_mm=250,edge_mm=60,
                     embedment=dict(method="bond",tau_bd_MPa=.6,bar="plain",L_mm=850,
                         source="Project stress limit for plain grouted anchor, VERIFY actual pedestal and bond",
                         cite="Preliminary IS 456 working-stress bond input, verify anchorage and edge/group breakout")))
    cfg["eor_inputs"].append(dict(item="Working-stress base assumptions",value="3 MPa permissible bearing, plain anchor 850 mm at bond 0.6 MPa",
                              source="Proposed performance requirements for the benchmark, verify with foundation design",verify=True))
    cfg["cfs_connections_spec"].update(knee=bolts,apex=bolts,base=base)
    return cfg
