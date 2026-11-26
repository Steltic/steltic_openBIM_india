"""Build the plates and flange restraints belonging to actual native EBF links."""
from collections import defaultdict
from functools import lru_cache
from math import ceil, dist, sqrt

import engine3d
import hr_autosize
import india_connections as joints
import india_is800 as design
import sections
from native_joint_parts import flange_frame, location, plate, steel
from steltic_openbim_india.geometry import cross, dot, sub, unit


UP = (0, 0, 1)
STAYS = ("CHS114.3X5.4", "CHS139.7X5.4", "CHS168.3X6.3", "CHS193.7X8",
         "CHS219.1X10", "CHS244.5X10", "CHS273X12", "CHS323.9X12")


def reverse(axis):
    return tuple(-v for v in axis)


def status(model, name, message, dc, reference):
    from handoff import check
    return check(model.data["checks"], model.pre+name, message,
                 "review" if dc is None else "pass" if dc <= 1 else "fail", dc, reference)


def weld(key, a, b, leg, face):
    return dict(id=key, kind="weld", material="WELD410", start=a, end=b,
                leg_mm=leg, ref_direction=list(face))


def select_fillet(demand, length, plate_t):
    """Two shop fillets; reserve the two end lengths per IS 800 10.5.4.1."""
    for leg in (6, 8, 10, 12, 14, 16, 18, 20, 22, 25):
        if leg > plate_t-1.5 or length <= 2*leg:
            continue
        result = joints.fillet_weld_capacity_is800_N(size_mm=leg, length_mm=length-2*leg,
                        fu_MPa=410, n_sides=2, site=False, demand_N=demand)
        if result["check"]["dc"] <= 1:
            return leg, result["check"]["dc"]
    raise ValueError(f"Two fillets on {plate_t:g} mm x {length:g} mm cannot develop {demand/1000:g} kN")


def stiffeners(model, link, native):
    p = sections.props(link["profile"])
    w, v, run = flange_frame(link)
    end = native["end_stiffeners"]
    t = 2*ceil(end["t_mm"]/2)
    b = end["width_mm"]/2
    depth = p["d"]-2*p["tf"]
    clip = ceil(p.get("R1", 0)+2)
    strength = hr_autosize.plate_fy(t)*t*b
    web_leg, web_dc = select_fillet(strength, depth-2*clip, t)
    flange_leg, flange_dc = select_fillet(strength/4, b-clip, t)
    length = dist(link["start"], link["end"])
    bays = ceil(length/native["intermediate_stiffener_spacing_mm"])
    key = link["id"]+"-ST"
    check_id = status(model, key[len(model.pre):], f'{link["id"]} transverse stiffeners and welds. '
        f'Two {b:g} x {t:g} mm plates with {clip:g} mm root clips at {length/bays:g} mm intervals. '
        f'Web weld demand {strength/1000:.1f} kN per plate, flange weld demand {strength/4000:.1f} kN per flange.',
        max(web_dc, flange_dc, (length/bays)/native["intermediate_stiffener_spacing_mm"]),
        "IS 18168 11.4–11.4.2 and IS 800 10.5.4.1/10.5.7")
    row = dict(id=key, type="shear link stiffeners", members=[link["id"]], at=location(link["start"],(run,length/2)),
        level=link["level"], unit=model.u.name, checks=[check_id], parts=[], parameters={
        "stiffener_pairs":bays+1, "plate_width_mm":b,"plate_thickness_mm":t,"root_clip_mm":clip,
        "intermediate_spacing_mm":length/bays,"native_spacing_limit_mm":native["intermediate_stiffener_spacing_mm"],
        "web_fillet_leg_mm":web_leg,"flange_fillet_leg_mm":flange_leg},
        description="Full-depth stiffener plates at both brace ends and intermediate stations. "
                    "Clip each internal root and shop-weld both plate faces to web and flanges.")
    model.materials.setdefault("WELD410", {"grade":"410 MPa matching consumable","standard":"IS 814 / IS 800 10.5"})
    mat=steel(model,"E250B0")
    for i in range(bays+1):
        at=location(link["start"], (run,i*length/bays-t/2))
        for side in (-1,1):
            across=w if side==1 else reverse(w)
            def point(x,y,z=0):
                return location(at,(across,p["tw"]/2+x),(v,y),(run,z))
            h=depth/2
            # Reverse the negative-side ordering so both plates extrude in +run.
            outline=[point(*q) for q in ((clip,-h),(b,-h),(b,h),(clip,h),(0,h-clip),(0,-h+clip))]
            if side<0:outline.reverse()
            name=key+f'-{i+1}'+('R' if side>0 else 'L')
            row["parts"].append(dict(id=name,kind="plate",material=mat,outline=outline,thickness_mm=t))
            for face, offset in ((0,0),(1,t)):
                flank=reverse(run) if face==0 else run
                row["parts"].append(weld(name+f'-W{face}',point(0,-h+clip,offset),point(0,h-clip,offset),web_leg,flank))
                for tag, y in (("T",h),("B",-h)):
                    row["parts"].append(weld(name+f'-{tag}{face}',point(clip,y,offset),point(b,y,offset),flange_leg,flank))
    model.data["connections"].append(row)
    return check_id


def anchor_beam(source, end, peers, occupied):
    """Find actual peer steel in this storey by projecting onto measured beam segments."""
    normal, _, along=flange_frame(source)
    options=[]
    for host in peers:
        a,b=host["start"],host["end"]
        direction=unit(sub(b,a))
        length=dist(a,b)
        if length<700: continue
        for sign in (-1,1):
            target=location(end,(normal,sign*2300))
            projected=dot(sub(target,a),direction)
            # Separate the physical seats of both flanges and the adjoining
            # link end. The largest longitudinal seat is 750 mm long.
            for shift in (0,-800,800,-1600,1600,-2400,2400):
                station=max(400,min(length-400,projected+shift))
                if any(abs(station-s)<800 for s in occupied[host["id"]]):continue
                point=location(a,(direction,station))
                delta=sub(point,end)
                separation=sign*dot(delta,normal)
                if separation < 1050 or separation > 5500 or abs(dot(delta,along)) > .72*separation:
                    continue
                options.append((dist(point,target),host["id"],sign,station,point,host))
    if not options:
        raise ValueError(f'{source["id"]} has no receiving beam near link end {end}')
    _,_,sign,station,point,host=min(options,key=lambda item:item[:4])
    occupied[host["id"]].append(station)
    return sign,point,host


@lru_cache(maxsize=4096)
def choose_stay(length, cosine, demand, stiffness,minimum=0):
    for label in STAYS[minimum:]:
        p=sections.props(label)
        # The stock catalogue supplies the tube dimensions. Order the actual
        # seismic restraint from IS 2062 E250 B0 plate with a full-strength
        # longitudinal seam and use the cold-formed hollow-section curve.
        compression=design.compression_capacity(p,250,KLz_mm=length,KLy_mm=length,process="COLD_FORMED")
        section_capacity=compression.get("Pd_N")
        if not section_capacity: continue
        k=200000*p["A"]/length*cosine**2
        dc=demand/(cosine*section_capacity)
        if dc<=.92 and k>=2*stiffness:
            return label,dc,k
    raise ValueError(f"No E250 B0 circular stay for {length:g} mm, {demand/1e3:g} kN and {stiffness:g} N/mm")


class SeatFitError(ValueError):
    """A strength-compliant stay may still need a larger net section at its slot."""


def bracket(model,row,prefix,host,at,away,upper,tube,force):
    """Standing CJP blade and longitudinal seat at the inboard flange face."""
    hp=sections.props(host["profile"])
    _,_,axis=flange_frame(host)
    saddle_axis=unit((axis[0],axis[1],0))
    side=unit(cross(UP,saddle_axis))
    # The cap is entirely on one flange outstand, beyond its root radius.
    hf=hp["tw"]/2+hp.get("R1",0)+3
    outer=hp["bf"]/2-2
    capwidth=outer-hf
    if capwidth<=20:raise ValueError(f'{host["id"]}: insufficient receiving flange outstand for welded seat')
    horizontal=unit((away[0],away[1],0))
    longitudinal=abs(dot(saddle_axis,horizontal)); transverse=abs(dot(side,horizontal))
    # A groove root lies entirely over the physical seat. Its actual length
    # depends on the arrival angle and the width of the flange outstand.
    root_dc=None
    for caplen in (350.,450.,600.,750.):
        for cap_t in (20.,25.,32.,40.,50.,56.,63.,71.,80.,90.):
            for tab_t in (16.,20.,25.,32.,40.,50.,56.,63.,71.,80.):
                if tab_t>tube["d"]*.70 or capwidth<tab_t*longitudinal+5:
                    continue
                r=min((caplen-4-tab_t*transverse)/max(longitudinal,.001),
                      (capwidth-4-tab_t*longitudinal)/max(transverse,.001))
                if r<=20:continue
                root_t=min(cap_t,tab_t)
                weld_yield=hr_autosize.plate_fy(max(cap_t,tab_t))/(1.5*sqrt(3))
                # Linear interaction. Blade plane moment arises from the 100 mm
                # workline minus the seat thickness. Check the complete CJP.
                blade_dc=(force/(root_t*r)+6*force*max(0,100-cap_t)/(root_t*r*r))/weld_yield
                parental=min(hp["tf"],cap_t)
                weld_shear=hr_autosize.plate_fy(max(hp["tf"],cap_t))/(1.5*sqrt(3))
                seam=force*sqrt(.25+(100*transverse/capwidth+300*longitudinal/caplen)**2)
                seat_dc=seam/(parental*caplen*weld_shear)
                net=tube["A"]-2*(tab_t+2)*tube["tw"]
                net_dc=force/(.9*410*net/1.25) if net>0 else 100.
                if max(blade_dc,seat_dc,net_dc)<=.97:
                    root_dc=max(blade_dc,seat_dc,net_dc)
                    break
            if root_dc is not None:break
        if root_dc is not None:break
    if root_dc is None:
        raise SeatFitError(f'{prefix} {host["profile"]} seat cannot take {force/1e3:.1f} kN, {capwidth:g} mm outstand')
    cap_origin=location(at,(side,-capwidth/2),(saddle_axis,-caplen/2))
    slab_side=reverse(UP) if upper else UP
    cap_ax=saddle_axis if dot(cross(saddle_axis,side),slab_side)>0 else reverse(saddle_axis)
    if cap_ax!=saddle_axis:cap_origin=location(cap_origin,(saddle_axis,caplen))
    row["parts"].append(plate(prefix+"-SEAT",cap_origin,cap_ax,side,caplen,capwidth,cap_t,"E250B0"))
    # A vertical plate in the horizontal projection of the CHS workline slots
    # into the tube. Its root meets the underside (or top side) of the seat.
    crossbar=unit(cross(horizontal,slab_side))
    lap=ceil(max(180,force*1.5*sqrt(3)/(4*tube["tw"]*240))/25)*25
    height=max(tube["d"]*.82,100-cap_t+tube["d"]*.35)
    bladebase=location(at,(horizontal,-r/2),(slab_side,cap_t),(crossbar,-tab_t/2))
    row["parts"].append(plate(prefix+"-BLADE",bladebase,horizontal,slab_side,r+lap,height,tab_t,"E250B0"))
    slot=joints.cjp_weld_capacity_N(t_mm=tube["tw"],length_mm=lap,
        fy_MPa=min(250.,hr_autosize.plate_fy(tab_t)),n_sides=4,site=True)["capacity_N"]
    end=prefix.rsplit("-",1)[-1]
    row["parameters"].update({end+"_slot_length_mm":lap,end+"_blade_CJP_root_mm":round(r,2),
        end+"_seat_CJP_per_edge_mm":caplen,end+"_seat_thickness_mm":cap_t,end+"_blade_thickness_mm":tab_t})
    return max(force/slot,root_dc)


def add_stays(model,link,native,peers,occupied,stiff_check):
    p=sections.props(link["profile"])
    transverse,_,_=flange_frame(link)
    fy=hr_autosize.plate_fy(p["tf"],link["material"])
    ry=1.4 if "250" in link["material"] else 1.2
    span=native["e_mm"]
    scale=ry*fy*p["Zx"]/(p["d"]-p["tf"])
    force=.06*scale
    required_k=5*scale/span
    for i,end in enumerate((link["start"],link["end"]),1):
        for upper in (True,False):
            sign,raw,host=anchor_beam(link,end,peers,occupied)
            hp=sections.props(host["profile"])
            host_w,_,_=flange_frame(host)
            inward=transverse if sign>0 else reverse(transverse)
            # Keep the receiving seat below its top flange on the approached outstand.
            approaching=1 if dot(sub(end,raw),host_w)>=0 else -1
            offset=lambda section: (section["tw"]/2+section.get("R1",0)+3+section["bf"]/2-2)/2
            far_root=location(raw,(host_w,approaching*offset(hp)),(UP,hp["d"]/2-hp["tf"]))
            key=link["id"]+f"-F{i}"+("T" if upper else "B")
            # The stay workline runs 100 mm inside each flange face.
            factor=1 if upper else -1
            near_root=location(end,(inward,offset(p)),(UP,factor*(p["d"]/2-p["tf"])))
            a=location(near_root,(UP,-factor*100))
            b=location(far_root,(UP,-100))
            axis=unit(sub(b,a)); cosine=abs(dot(transverse,axis)); length=dist(a,b)
            N=force/cosine
            minimum=0
            while minimum<len(STAYS):
                label,member_dc,k=choose_stay(ceil(length),int(cosine*10000)/10000,round(force,1),round(required_k,1),minimum)
                sp=sections.props(label)
                support={'parts':[],'parameters':{}}
                try:
                    near_dc=bracket(model,support,key+"-A",link,near_root,axis,upper,sp,N)
                    far_dc=bracket(model,support,key+"-B",host,far_root,reverse(axis),True,sp,N)
                except SeatFitError:
                    minimum=STAYS.index(label)+1
                    if minimum==len(STAYS):raise
                else:break
            required_support=1/(1/required_k-1/k)
            ck=status(model,key[len(model.pre):], f'{link["id"]} {"upper" if upper else "lower"} flange at end {i}. '
                f'{label}, pin-ended effective length {length:.0f} mm, transverse resistance demand {force/1000:.1f} kN, '
                f'projected stiffness {k/1000:.1f} kN/mm versus {required_k/1000:.1f}.',max(member_dc,required_k/k),
                "IS 18168 12.3.3.2, 6.3.3 and 6.3.1(b); IS 800 7.1.2")
            loc=lambda q: [q[j]-model.offset[j] for j in range(3)]
            row=model.member("link flange restraint",label,loc(a),loc(b),material="E250B0",checks=[ck],
                             mid=key[len(model.pre):],bind=False)
            row["level"]=link["level"]
            details=dict(id=key+"-J",type="link flange restraint assembly",members=[link["id"],row["id"],host["id"]],
                at=near_root,level=link["level"],unit=model.u.name,checks=[ck,stiff_check],parts=support["parts"],
                parameters={**support['parameters'],"stay_axial_kN":round(N/1000,2),"required_support_kN_mm":round(required_support/1000,3),
                "required_transverse_kN":round(force/1000,2)},
                description="Site CJP blade root and two longitudinal seat-to-flange roots. Slotted CHS has four CJP runs at each end. "
                "Receiver top flange transfers reaction to the deck. Check panel effective shear stiffness, attachment "
                "and local flange spread with the selected floor system. Coordinate weld bevel and notch with the steel detailer.")
            details["checks"].append(status(model,key[len(model.pre):]+"-W",
                f"Slotted-tube weld and support CJP parent strength for {N/1000:.1f} kN.",
                max(near_dc,far_dc),"IS 800 10.5.7.1.2"))
            model.data["connections"].append(details)


def add_link_assemblies(model):
    native=engine3d.build(model.cfg,"Linear")
    source={r["tag"]:r for r in native.get("links",[])}
    if not source:return
    tube_spec=("Form the circular link restraints from certified IS 2062 E250 B0 feedstock with a full-penetration "
               "longitudinal seam. IS 1161 Table 1 supplies finished dimensions. Axial design uses "
               "250 MPa yield, 410 MPa tensile and the cold-formed hollow-section buckling curve.")
    if tube_spec not in model.data.setdefault("assumptions",[]):model.data["assumptions"].append(tube_spec)
    peers=defaultdict(list)
    occupied=defaultdict(list)
    existing=[r for r in model.data["members"] if r["unit"]==model.u.name]
    numeric=defaultdict(dict)
    for item in model.native.get("capacity_design",{}).get("section12",{}).get("checks",[]):
        owner=item.get("member")
        if isinstance(owner,str) and owner.startswith("link-e"):
            numeric[owner][item["id"]]=item
    for member in existing:
        if member["role"] in ("beam","secondary beam") and abs(member["start"][2]-member["end"][2])<.1:
            peers[round(member["start"][2],2)].append(member)
    for member in existing:
        ref=member.get("source_element",{}).get("tag")
        if ref in source:
            native_results=numeric.get(f"link-e{ref}",{})
            for name,code,scale,unit_name in (("shear","12.3.2.1_link_shear",.001,"kN"),
                    ("rotation","12.3.3.1_link_rotation",1.,"rad"),("link length","11.3_link_length",1.,"mm")):
                item=native_results.get(code)
                if item:
                    member.setdefault("checks",[]).append(status(model,f"E{ref}-{name.replace(' ','-')}",
                        f'{member["id"]} native {name} {item["value"]*scale:.5g} {unit_name} '
                        f'of {item["limit"]*scale:.5g} {unit_name}.',item["dc"],item["clause"]))
            over=native_results.get("12.3.2.2_link_overstrength",{})
            if over:
                member["design_values"]={"link_overstrength_kN":round(over["value"]/1000,3),
                    "brace_design_shear_kN":round(over["brace_design_shear_N"]/1000,3)}
            ck=stiffeners(model,member,source[ref])
            add_stays(model,member,source[ref],peers[round(member["start"][2],2)],occupied,ck)
    status(model,"LINK-RECEIVERS",
        "Confirm the receiving floor-beam flange, deck fasteners and total connection/support flexibility for the reaction and minimum support stiffness "
        "listed on every flange-restraint assembly. Resolve the untrimmed tube slots, field CJP groove and link-end deck blockouts.",
        None,"IS 18168 6.3.1(b), 6.3.3 and 12.3.3.2; project deck and steel detailing")
