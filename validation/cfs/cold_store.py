"""Srinagar's airlock roof, thermal bearings and raised condenser grating."""
from connection_parts import plate
from shapely.geometry import Polygon, box
from bearings import Sections
from pitched_bearings import offset,rectangles
from steltic_openbim_india.geometry import frame,plane,dot


def install(model,pkg):
    import is801_members as M
    import is811_sections as S
    geo=Sections(model,pkg)
    members=model["members"];byrole=lambda role:[m for m in members if m["role"]==role]
    up=[0.,0.,1.];out=[]
    reviews="annex:project"
    model["checks"].append(dict(id=reviews,status="review",description="Verify equipment foot reactions and dunnage, cold-store thermal-clip fixings, stud tracks, positive attachment of seats/caps, airlock lateral anchorage and concrete bases with supplier and foundation EOR.",reference="Srinagar project inputs; IS 801 7, cold-service assembly specification"))
    def sample(name,chain,normal,station,**basis):
        if not any(s["id"]==name for s in out):out.append(dict(id=name,chain=chain,normal=normal,
              stations_mm=[station],expected_gaps_mm=[0.]*(len(chain)-1),tolerance_mm=1.,**basis))
    def part_member(id,role,pts,profile,direction=None,checks=None):
        level=max((l for l in model["levels"] if l["elevation_mm"]<=min(p[2] for p in pts)),key=lambda l:l["elevation_mm"])
        row=dict(id=id,role=role,start=pts[0],end=pts[1],profile=profile,material="Plate",level=level["id"],checks=checks or [reviews])
        if direction:row["ref_direction"]=direction
        members.append(row);return row
    def joint(id,kind,at,mids,parts,check=reviews):
        model["connections"].append(dict(id=id,type=kind,at=at,members=mids,checks=[check,reviews] if check!=reviews else [reviews],
                       parts=[dict(p,id=id+"-"+str(i)) for i,p in enumerate(parts,1)]))
    def wedge(name,profile,halfspan,depths,points,ref):
        model["profiles"][profile]=dict(family="POLYGON",contours_mm=[[[-halfspan,depths[0]],[halfspan,depths[1]],
                   [halfspan,depths[2]],[-halfspan,depths[3]]]])
        return part_member(name,"Machined bearing wedge",points,profile,ref)
    def nr(m):
        ref=m.get("native_ref");return next(x for x in pkg["cfs_members"] if ref=="cfs:"+x["id"])
    def add_like(id,role,original,a,b,direction):
        row=dict(id=id,role=role,start=a,end=b,native_ref=original["native_ref"],material="CF",level=original["level"],ref_direction=direction,checks=[reviews])
        members.append(row);return row
    air=next(p for p in model["panels"] if p["role"]=="Airlock roof")
    air["analysis_plane_mm"]=air["outline"];normal=plane(air["outline"])[3]
    D=250;thermal=8;skin=100;slope=1/30;nz=normal[2]
    air["outline"]=[[x,y,round(z-skin/nz,5)] for x,y,z in air["outline"]];air.update(material="Insulated panel",thickness_mm=skin)
    route=lambda x:3500+(x+3000)*slope
    lower=lambda x:route(x)-(skin+thermal+D)/nz
    tracks={};pad_depth=7;half=65
    header=byrole("door header")[0];stud=byrole("back-wall stud")[0];jambs=byrole("door jamb")
    for side,x in (("front",-2950),("back",-50)):
        track_top=lower(x)-half*slope-pad_depth
        track=add_like("AIR-"+side.upper()+"-RIM","Airlock continuous rim",header,
              [x,5875,track_top-D/2],[x,10125,track_top-D/2],[-1,0,0])
        tracks[side]=(x,track_top,track)
    front,zt,_=tracks["front"];back,zb,_=tracks["back"]
    header.update(start=[front,6840,2525],end=[front,9160,2525],ref_direction=[-1,0,0])
    for index,m in enumerate(jambs):
        y=(6920,9080)[index];m.update(start=[front,y,0],end=[front,y,2400],ref_direction=[0,1,0])
    for m in byrole("back-wall stud"):
        y=m["start"][1];m.update(start=[back,y,0],end=[back,y,zb-D],ref_direction=[0,1,0])
    for i in range(11):
        y=6000+i*400
        low=2650 if 6920<y<9080 else 0
        add_like(f"AIR-FRONT-{i+1}","Airlock front stud" if not low else "Airlock door cripple",stud,
                [front,y,low],[front,y,zt-D],[0,1,0])
    for m in byrole("lean-to roof joist"):
        a,b=m["start"],m["end"];y=a[1];m["analysis_workpoints_mm"]=[a,b]
        dz=(skin+thermal+D/2)/nz
        m["start"],m["end"]=[[p[0],p[1],p[2]-dz] for p in (a,b)]
        w,n,axis=frame(m["start"],m["end"]);ta,tb=[offset(p,n,D/2) for p in (m["start"],m["end"])]
        outline=rectangles(ta,tb,w,25)
        if dot(plane(outline)[3],n)<0:outline.reverse()
        jid="AIR-THERM-"+m["id"];joint(jid,"Airlock thermal clip strip",ta,[m["id"]],
                            [dict(plate(outline,thermal),material="Thermal break")])
        if 6200<y<9800:
            q=offset(offset(ta,axis,600),w,12)
            sample("Airlock joist / thermal strip / insulated roof",[m["id"],jid+"-1",air["id"]],list(n),q,
                   structural_datum="Native top of airlock, 3500 to 3600 mm",normal_skin_underside_offset_mm=-skin)
        for side,(x,track_top,track) in tracks.items():
            h0=pad_depth;h1=h0+2*half*slope
            wid="AIR-"+side.upper()+"-WEDGE-"+m["id"]
            wedge(wid,"AIR-SLOPING-PACK",half,[0,0,h1,h0],[[x,y+55,track_top],[x,y-55,track_top]],[1,0,0])
            if 6200<y<9800:
                sample("Airlock "+side+" rim / bevel seat / joist",[track["id"],wid,m["id"]],up,[x+35,y+30,track_top],
                    minimum_seat_mm=7,seat_length_mm=130)
    model["materials"]["Grating"]={"grade":"Hot-dip galvanized structural steel, Fy 250 MPa","standard":"IS 2062. Verify welded bar-grating slip resistance, corrosion and equipment layout."}
    platform=next(p for p in model["panels"] if p["role"]=="Condenser platform");platform["analysis_plane_mm"]=platform["outline"]
    outer=platform["outline"];xs=[p[0] for p in outer];ys=[p[1] for p in outer];xl,xr=min(xs),max(xs);yl,yr=min(ys),max(ys)
    building_skin=next(p for p in model["panels"] if p["role"]=="Pitched roof" and
                   min(q[0] for q in p["outline"])<=xl+1<max(q[0] for q in p["outline"])
                   and min(q[1] for q in p["outline"])<yr<max(q[1] for q in p["outline"]))
    bp,_,_,n=plane(building_skin["outline"])
    roof_top=bp[2]-(n[0]*(xl-bp[0])+n[1]*(yr-bp[1]))/n[2]+building_skin["thickness_mm"]/n[2]
    top=roof_top+600;bar_d=50;plate_z=top-bar_d
    # 4 x 50 flat bearing bars at 25 mm; 4 mm band at each end,
    # 5 x 5 cross ties at 100 mm. No fictitious solid 50 mm deck.
    ring=lambda x,y,X,Y,z:[[x,y,z],[X,y,z],[X,Y,z],[x,Y,z]]
    platform.update(outline=ring(xl,yl,xr,yr,plate_z),material="Grating",thickness_mm=bar_d)
    platform["openings"]=[ring(x+2,yl+4,x+23,yr-4,plate_z) for x in range(round(xl),round(xr),25)]
    model["profiles"]["GRATING-TIE-5X5"]=dict(family="PLATE",dimensions_mm=dict(b=5,d=5))
    for idx in range(1,20):
        y=yl+100*idx
        part_member(f"GRATING-TIE-{idx}","Platform grating transverse tie",[[xl,y,top-2.5],[xr,y,top-2.5]],"GRATING-TIE-5X5",
                   checks=["annex:grating",reviews])
    snow=pkg["roof_platforms"][0]["snow_kNm2"];q=(snow+.65)*25/1000
    span=yr-yl;I=4*bar_d**3/12;stress=max(q*span**2/8,1500/4*span/4)/(I/(bar_d/2))
    defl=max(5*q*span**4/(384*200000*I),(1500/4)*span**3/(48*200000*I))
    dead=(bar_d*((4/25)+(1-4/25)*8/span)+25/100)*7850*9.81/1e6
    dc=max(stress/(.6*250),defl/(span/240),dead/.65)
    model["checks"].append(dict(id="annex:grating",status="pass" if dc<=1 else "fail",utilization=dc,
             description=f"Two-metre grating span, 4 x 50 bearing bars at 25 mm, 5 x 5 cross ties at 100 mm. Dead {dead:.3f} kPa vs 0.65; snow {snow:.3f} kPa or maintenance foot 1.5 kN across four welded bars. Bend {stress:.1f} MPa / 150, deflection {defl:.2f} mm / L/240. Five-kN condenser bears separately on the two beams.",
             reference="IS 800 11.3, 11.4 and serviceability; IS 875 Part 4 5.2.6; verify commercial grating point-load distribution"))
    role="platform post";posts=byrole(role);platform_beams=byrole("platform beam")
    member=nr(posts[0]);sec=S.built_up(member["section"],member["n_ply"]);fy=member["Fy_MPa"]
    P=max(abs(c.get("P_N",0) or 0) for c in member["checks"]);lengths=[]
    raw_rafter=[m for m in byrole("beam") if abs(m["start"][1]-m["end"][1])>1 and abs(m["start"][2]-m["end"][2])>1]
    for m in platform_beams:
        a,b=m["start"],m["end"];m["analysis_workpoints_mm"]=[a,b]
        m["start"],m["end"]=[[p[0],p[1],plate_z-D/2] for p in (a,b)]
    for m in posts:
        x,y,_=m["start"];host=next(h for h in raw_rafter if abs(h["start"][0]-x)<.1 and
                   min(h["start"][1],h["end"][1])-.01<=y<=max(h["start"][1],h["end"][1])+.01)
        a,b=host["start"],host["end"];sl=(b[2]-a[2])/(b[1]-a[1])
        rz=a[2]+(y-a[1])*sl+geo.limits(host,n)[1]/n[2]
        half=105;cap_top=rz+abs(sl)*half+12;cap_bot=plate_z-D-12
        wid="PLATFORM-BASE-"+m["id"];profile=wid+"-PROFILE"
        wedge(wid,profile,half,[-sl*half,sl*half,cap_top-rz,cap_top-rz],
                     [[x-140,y,rz],[x+140,y,rz]],[0,1,0])
        m["analysis_workpoints_mm"]=[m["start"],m["end"]];m["start"]=[x,y,cap_top];m["end"]=[x,y,cap_bot]
        m["ref_direction"]=[0,1,0]
        lengths.append(cap_bot-cap_top)
        jid="PLATFORM-CAP-"+m["id"]
        beam=next(h for h in platform_beams if h["start"][1]==y)
        joint(jid,"Condenser post headplate",[x,y,cap_bot],[m["id"],beam["id"]],[plate(ring(x-140,y-100,x+140,y+100,cap_bot),12)])
        # x chooses a physical grating bar; 12 mm is inside the C flanges.
        sign=1 if x==xl else -1
        sample("Condenser level beam / load-bearing grating bar",[beam["id"],platform["id"]],up,[x+50*sign,y+(12 if y==yl else -12),plate_z],
              minimum_clearance_to_roof_top_mm=600)
        sample("Rafter / machined condenser shoe",[host["id"],wid],list(n),[x+25*sign,y+25,rz+25*sl],
               structural_datum="Actual sloping rafter flange",minimum_wedge_edge_mm=12)
        sample("Condenser post cap / platform beam",[jid+"-1",beam["id"]],up,[x+30*sign,y+12,cap_bot],plate_thickness_mm=12)
        sample("Condenser bearing stack",[wid,m["id"],jid+"-1",beam["id"],platform["id"]],up,
               [x+123.8*sign,y+(30 if y==yl else -30),cap_top],minimum_cap_plate_mm=12)
    platforms=[(m["start"][0],m["start"][1]) for m in posts]
    for panel in (p for p in model["panels"] if p["role"]=="Pitched roof"):
        base,_,_,vec=plane(panel["outline"])
        local=lambda x,y:[round(x,4),round(y,4),round(base[2]-(vec[0]*(x-base[0])+vec[1]*(y-base[1]))/vec[2],5)]
        native=Polygon([p[:2] for p in panel["outline"]]);fitted=native
        for x,y in platforms:fitted=fitted.difference(box(x-142,y-99,x+142,y+99))
        if fitted.equals(native):continue
        if fitted.geom_type!="Polygon":raise ValueError("Unexpected split of a roof panel by platform posts")
        from shapely.geometry.polygon import orient
        fitted=orient(fitted,sign=1.)
        panel["outline"]=[local(x,y) for x,y in list(fitted.exterior.coords)[:-1]]
        if fitted.interiors:panel["openings"]=[[local(x,y) for x,y in list(r.coords)[:-1]] for r in fitted.interiors]
    height_max=.60+(yr-yl)*(abs(n[1])/n[2])/1000
    snow_ratio=2*height_max/pkg["roof_platforms"][0]["drift"]["s0_kPa"]
    if snow_ratio>=.8:raise ValueError("Installed obstruction requires a new snow-drift load map")
    model["checks"].append(dict(id="annex:snow",status="pass",utilization=snow_ratio/.8,
        description=f"Level platform obstruction 0.600 to {height_max:.3f} m above the insulated roof; 2h/s0={snow_ratio:.3f} remains below the 0.8 snow shape lower bound across the platform.",
        reference="IS 875 Part 4 5.2.6; native Srinagar cold-roof snow map"))
    maxL=max(lengths);cap=M.compression_allowable(sec,fy,maxL,maxL)["Pa_N"];ratio=P/cap
    model["checks"].append(dict(id="annex:post",status="pass" if ratio<=1 else "fail",utilization=ratio,
        description=f"Installed condenser post length {min(lengths):.1f}–{maxL:.1f} mm. Governing native axial reaction {P/1000:.2f} kN, paired section allowable {cap/1000:.2f} kN with full installed length unbraced.",
        reference="IS 801 6.6 and 7.3; native cold-store condenser load map"))
    for m in posts:m["checks"]=[*m.get("checks",[]),"annex:post",reviews]
    if dc>1 or ratio>1:raise ValueError("Installed cold-store platform steel check fails")
    model["assumptions"].append("Srinagar airlock outer roof rises from 3500 to 3600 mm. Its native paired joists bear on tapered seats over continuous front/back rims. The level steel condenser grating is at least 600 mm above the insulated roof. Machine-cut shoes fit onto actual pitched rafter flanges. The 5 kN equipment load bears on the main platform beams; verify equipment foot placement and cross-bar point-load distribution.")
    return out,{k["id"]:{field:value for field,value in k.items() if field not in ("id","chain","normal","stations_mm","expected_gaps_mm","tolerance_mm")} for k in out}
