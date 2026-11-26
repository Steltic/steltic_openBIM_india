"""Fit the sloping roof to its real primary rafters, incl. both sides of every fold."""
from collections import defaultdict
import math
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree
from steltic_openbim_india.geometry import dot, frame, plane, sub
from bearings import Sections, shift


def offset(point,direction,distance):
    return [round(a+b*distance,5) for a,b in zip(point,direction)]


def move_parts(joint,direction,distance):
    joint["at"]=offset(joint["at"],direction,distance)
    for part in joint.get("parts",[]):
        for name in ("start","end"):
            if name in part:part[name]=offset(part[name],direction,distance)
        if "outline" in part:part["outline"]=[offset(p,direction,distance) for p in part["outline"]]
        if "openings" in part:part["openings"]=[[offset(p,direction,distance) for p in r] for r in part["openings"]]


def rectangles(a,b,width,outer):
    return [offset(a,width,-outer),offset(b,width,-outer),offset(b,width,outer),offset(a,width,outer)]


def installed(model,pkg,case):
    sections=Sections(model,pkg);faces=[];footprints=[]
    for p in model["panels"]:
        if p["role"]!="Pitched roof":continue
        if plane(p["outline"])[3][2]<0:p["outline"].reverse()
        faces.append(p);footprints.append(Polygon([v[:2] for v in p["outline"]]))
    tree=STRtree(footprints)
    axes=[plane(p["outline"]) for p in faces]
    links=defaultdict(list);girders=defaultdict(list)
    for j in model["connections"]:
        if j["type"]=="Purlin cleat":links[j["members"][0]].append(j)
    for m in model["members"]:
        if m["role"] not in ("beam","rafter","Truss upper chord","truss top chord"):continue
        a,b=m["start"],m["end"]
        if abs(a[2]-b[2])<.1:continue
        c=0 if abs(a[0]-b[0])>abs(a[1]-b[1]) else 1
        girders[c,round(a[1-c])].append((min(a[c],b[c]),max(a[c],b[c]),m))
    data=[];groups=defaultdict(list);moved=[]
    for m in model["members"]:
        if m["role"]!="purlin":continue
        a,b=m["start"],m["end"];w,n,u=frame(a,b,m.get("ref_direction"))
        mid=[(x+y)/2 for x,y in zip(a,b)];point=Point(mid[:2])
        ids=[int(i) for i in tree.query(point) if footprints[int(i)].covers(point)
             and dot(n,axes[int(i)][3])>.99999 and abs(dot(sub(mid,axes[int(i)][0]),n))<.2]
        if not ids:continue  # separately fitted flat roof
        c=1 if abs(u[0])>.95 else 0
        li=links[m["id"]]
        if len(li)!=2:raise ValueError(f'{m["id"]} requires a seat at each supported end')
        supports=[]
        for q,to in ((a,b),(b,a)):
            matches=[]
            for lo,hi,h in girders[c,round(q[1-c])]:
                if not lo-.15<=q[c]<=hi+.15:continue
                v,hb=h["start"],h["end"]
                interpolated=v[2]+(hb[2]-v[2])*(q[c]-v[c])/(hb[c]-v[c])
                if abs(interpolated-q[2])<.16:
                    matches.append((abs(interpolated-q[2]),h,lo,hi))
            if not matches:raise ValueError(f'{m["id"]} positioned at {q} has no pitched receiving steel')
            err,host,lo,hi=min(matches,key=lambda v:v[0])
            j=min(li,key=lambda v:math.dist(v["at"],q));seat=next(p for p in reversed(j["parts"]) if p["kind"]=="plate")
            supports.append((q,to,host,j,seat,sections.limits(host,n)[1],lo,hi))
        bottom,top=sections.limits(m,n)
        k=(tuple(round(v,4) for v in n), round(dot(mid,n)/100),round(top-bottom,1))
        groups[k].extend(s[5]+s[4]["thickness_mm"] for s in supports)
        data.append((m,w,n,u,ids,k,supports,bottom,top,c))
    samples={};stats=defaultdict(list); heights=defaultdict(list)
    if case==2:
        model["materials"]["Thermal break"]={"grade":"8 mm structural thermal isolation strip","standard":"Project selection; verify tested cold-store clip, compression and creep"}
        model["materials"]["Insulated panel"]={"grade":"100 mm insulated cold-store roof sandwich panel","standard":"Supplier span, thermal, fire and cold-service certification required"}
        model["checks"].append(dict(id="layout:thermal-isolation",status="review",description="Confirm cold-service thermal clips, 8 mm isolation strip retained thickness, creep, roof panel spanning, fasteners, fire and envelope seals at -23 C.",reference="Srinagar brief; sandwich-panel and thermal-clip supplier"))
        for p in faces:p.update(thickness_mm=100,material="Insulated panel")
    for m,w,n,u,ids,key,supports,bottom,top,c in data:
        a,b=m["start"],m["end"]
        sf=max(groups[key]);lift=sf-bottom
        m["analysis_workpoints_mm"]=[a,b]
        m["start"],m["end"]=offset(a,n,lift),offset(b,n,lift)
        extra=8 if case==2 else 0
        skin_lift=lift+top+extra
        for i in ids:heights[i].append(skin_lift)
        thermal=None
        if case==2:
            thermal=f'TB-{m["id"]}';start,end=[offset(p,n,top) for p in (m["start"],m["end"])]
            outline=rectangles(start,end,w,25)
            if dot(plane(outline)[3],n)<0:outline.reverse()
            model["connections"].append(dict(id=thermal,type="Cold-store thermal clip strip",at=offset(start,u,100),
                 members=[m["id"]],checks=["layout:thermal-isolation"],parts=[dict(id=thermal+"-1",kind="plate",material="Thermal break",outline=outline,thickness_mm=8)],
                 description="Continuous 50 x 8 mm thermal bearing strip. Proprietary thermal clips and panel fasteners are subject to cold-service supplier specification. No diaphragm credit."))
        for q,to,host,j,seat,ht,lo,hi in supports:
            j["members"].append(host["id"]);move_parts(j,n,lift)
            delta=sf-seat["thickness_mm"]-ht
            if delta>.16:raise ValueError(f'{m["id"]} needs {delta:.2f} mm of support packing on {host["id"]}')
            sign=1 if dot(sub(to,q),u)>0 else -1
            station=offset(offset(offset(q,n,sf),u,40*sign),w,12)
            # Sample away from ridge/eave cut faces, where sheets from two
            # slopes meet and have an independent closure detail.
            center=Point(station[:2]);options=[i for i in ids if footprints[i].covers(center)]
            if not options:continue
            i=options[0];chain=[host["id"],seat["id"],m["id"]]
            if thermal:chain.append(thermal+"-1")
            chain.append(faces[i]["id"])
            typ="Pitched roof "+"/".join(f"{v:.4f}" for v in n)+f" / {sections.profile(host)[0]} / {sections.profile(m)[0]}"
            rank=min(q[c]-lo,hi-q[c])
            stats[typ].append(skin_lift)
            if typ not in samples or rank>samples[typ][0]:
                samples[typ]=(rank,dict(id=typ,chain=chain,normal=list(n),stations_mm=[station],
                   expected_gaps_mm=[0.]*(len(chain)-1),tolerance_mm=1.,structural_datum="Original sloping primary workplane",
                   panel_underside_normal_offset_mm=round(skin_lift,3),vertical_plane_offset_mm=round(skin_lift/n[2],3)))
        moved.append((m,a,b,lift,n,bottom))
    for i,p in enumerate(faces):
        zout=heights[i]
        if not zout or max(zout)-min(zout)>.16:raise ValueError(f'{p["id"]} purlin/skin offsets disagree: {set(zout)}')
        dz=max(zout)/axes[i][3][2];p["analysis_plane_mm"]=p["outline"]
        p["outline"]=[shift(q,dz) for q in p["outline"]]
    if case in (1,2,3):fit_stays(model,moved)
    if case==3:check_stays(model,pkg)
    model["assumptions"].append("Pitched purlins sit on the modeled seats, with 75 mm workpoint setbacks on both sides of roof folds. Roof surfaces retain the architectural ridge and eave plan coordinates. Supplier flashing, ridge and valley closures, roof and gable transition, screw patterns, waterproofing and tolerances require coordination.")
    return [v[1] for v in samples.values()],{k:dict(measured_workline_conditions=len(v),min_normal_skin_offset_mm=round(min(v),3),max_normal_skin_offset_mm=round(max(v),3)) for k,v in stats.items()}


def fit_stays(model,moved):
    if not moved:return
    purlins=defaultdict(list);hardware=defaultdict(list)
    for m,a,b,lift,n,bottom in moved:
        along=0 if abs(b[0]-a[0])>abs(b[1]-a[1]) else 1
        purlins[along,round(a[1-along],2),round(a[2],2)].append((min(a[along],b[along]),max(a[along],b[along]),m,lift,n,bottom))
    for j in model["connections"]:
        if j["type"]=="Fly-stay attachment":hardware[j["members"][0]].append(j)
        if j["type"]=="Back-to-back web stitches":
            m=j["members"][0]
            for mem,a,b,lift,n,bottom in moved:
                if mem["id"]==m:move_parts(j,n,lift);break
    for s in model["members"]:
        if s["role"] not in ("Rafter fly stay","Flange fly stay"):continue
        q=s["end"]
        found=None
        for along in (0,1):
            peers=purlins.get((along,round(q[1-along],2),round(q[2],2)),[])
            found=next((v for v in peers if v[0]<q[along]<v[1]),None)
            if found:break
        if found:
            lo,hi,mem,lift,n,bottom=found
            # Keep a short, shallow stay: attach to the purlin's lower
            # flange, directly at the seated support datum.
            s["end"]=offset(q,n,lift+bottom)
            for j in hardware[s["id"]]:
                if math.dist(j["at"],q)<.01:
                    move_parts(j,n,lift+bottom);j["members"].append(mem["id"])


def check_stays(model,pkg):
    import is801_members as M
    import is811_sections as S
    stays=[m for m in model["members"] if m["role"]=="Flange fly stay"]
    length=max(math.dist(m["start"],m["end"]) for m in stays)
    cosine=min(abs(m["end"][1]-m["start"][1])/math.dist(m["start"],m["end"]) for m in stays)
    selected=[row for row in pkg["cfs_members"] if row["role"] in ("column","rafter")]
    demand=max(abs(c["M_Nmm"])/220+abs(c.get("P_N",0)) for row in selected for c in row["checks"] if "M_Nmm" in c)
    force=max(15000,.025*demand)/cosine
    fy=selected[0]["Fy_MPa"];sec=S.props("CLR100X50X15X2")
    buckle=M.compression_allowable(sec,fy,length,length)["Pa_N"]
    local=M.bolted_connection_75(fy,2,16,force/2,2,30,90,T_member_N=force,bolt_class="8.8")
    rail=M.compression_allowable(S.built_up("CLR250X80X25X5",2),fy,5000,5000)["Pa_N"]
    for c in model["checks"]:
        if c["id"]=="restraint:stay":
            dc=max(force/buckle,local["dc"])
            desc=f"Actual longest fitted stay {length:.1f} mm, smallest longitudinal direction cosine {cosine:.4f}. Larger of 15 kN and 2.5% of native flange force gives {force/1000:.2f} kN along stay. Two M16 bolts per end."
        elif c["id"]=="restraint:rail":
            dc=4*force/rail;desc=f"Four simultaneous fitted stay forces {4*force/1000:.2f} kN. Five-metre paired restraint rail permissible compression {rail/1000:.2f} kN."
        else:continue
        c.update(utilization=dc,description=desc,status="pass" if dc<=1 else "fail")
