"""Physical occurrences for the independently declared building layouts.

Uses the completed native primary-frame model. Secondary placements use the
same occupied bay masks, spacing, orientation and supports as the design input.
Coordinates here are metres; the exchange boundary is exclusively mm.
"""
import json
import math
import csv
from pathlib import Path
from connection_parts import base_parts, beam_end_parts, bolt, brace_end_parts, cleat_parts, portal_gusset, truss_end_parts


def grid_line(n):
    s=""
    while n>=0:
        s=chr(65+n%26)+s
        n=n//26-1
    return s


def menu(a,b,spacing,ends=False):
    count=max(1,math.ceil(round((b-a)/spacing,6)))
    return [a+(b-a)*k/count for k in range(0 if ends else 1,count+1 if ends else count)]


def mm(xyz):
    return [round(v*1000,3) for v in xyz]


class Layout:
    def __init__(self,b,cfg,pkg):
        self.b=b
        self.cfg=cfg
        self.pkg=pkg
        self.m=[]
        self.p=[]
        self.c=[]
        self.seen={}
        self.joints={}
        self.cfs={}
        self.primary={}
        self.cleat_ids={}
        self.checks=[dict(id="project:verify",status="review",
             description="Confirm conditional soil, foundations, material certificates, diaphragm behavior and product specifications.",
             reference="Declared benchmark design assumptions and delegated design items")]
        self.profiles={}
        self.elevations=b.elevations[:]
        for plane in cfg.get("lateral_frame",{}).get("gold",{}).get("roof_planes",[]):
            if plane["ridge_z_m"] not in self.elevations:
                self.elevations.append(plane["ridge_z_m"])
        if b.number<=3:
            ridge=[7.5,9,8.4][b.number-1]
            if ridge not in self.elevations: self.elevations.append(ridge)
        if b.number==3:
            self.elevations.append(3.5)
        self.elevations.sort()
        self.levels=[dict(id="G" if i==0 else f"L{i}",elevation_mm=round(z*1000,3)) for i,z in enumerate(self.elevations)]
        for row in pkg["cfs_members"]:
            self.cfs.setdefault(row["role"],[]).append(row)
        for row in pkg["lateral_frame"].get("members") or []:
            self.primary.setdefault(row["section"],[]).append(row)
        self.assumptions=list(b.notes)+[
            "Levels, member axes and all dimensions in the handoff are in millimetres. Verify site soil, opening ratios, terrain, heat numbers and supplier data.",
            "Physical framing uses nominal analytic workpoints and untrimmed member ends. Panels follow structural control planes. Coordinate finish buildups, offsets, coping and weld preparations in fabrication details.",
            "The native design gate and governing member checks travel with this model. Review open primary-frame, concrete, diaphragm and fastening checks before design acceptance.",
            "Any proposed in-plane board stiffness and allowable shear require full assembly test evidence. Concrete pedestal and group breakout design must be verified.",
            "Dead loads are preliminary assembly allowances. No imposed-load reduction is used. Primary member self-weight is computed separately by the solver."]
        self.mat={"HR":dict(grade=cfg.get("lateral_frame",{}).get("steel_grade","E250 B0"),standard="IS 2062"),
                  "BR":dict(grade=cfg.get("lateral_frame",{}).get("brace_grade","E250 B0"),standard="IS 2062"),
                  "CF":dict(grade=f"Sheet Fy {cfg['cfs_members']['Fy_MPa']} MPa",standard="IS 801 / IS 1079 material specification",fy_mpa=cfg["cfs_members"]["Fy_MPa"]),
                  "Plate":dict(grade="E250",standard="IS 2062"),
                  "Bolt":dict(grade="8.8",standard="declared connection schedule"),
                  "Weld":dict(grade="Matching E250 consumable",standard="IS 814 / project welding specification"),
                  "Board":dict(grade="Cement board",standard="project floor build-up; supplier verification required"),
                  "Deck":dict(grade="Coated sheet",standard="project roofing build-up; supplier verification required"),
                  "Slab":dict(grade="Composite floor M30",standard="project podium floor build-up")}

    def level(self,z):
        return self.levels[max(i for i,t in enumerate(self.elevations) if t<=z+.001)]["id"]

    def member(self,role,a,b,*,ref=None,prof=None,material="CF",direction=None,review=None):
        start,end=mm(a),mm(b)
        if math.dist(start,end)<.01: raise ValueError((role,start,end))
        # A centreline can legitimately carry both a collector and another
        # member, but cell shared edges cannot duplicate the same occurrence.
        key=(role,tuple(sorted([tuple(start),tuple(end)])),ref,prof)
        if key in self.seen: return self.seen[key]
        rid=f"M{len(self.m)+1:05}"
        d=dict(id=rid,role=role,start=start,end=end,level=self.level(min(a[2],b[2])),material=material)
        if ref: d["native_ref"]=ref
        if prof: d["profile"]=prof
        if review: d["checks"]=[review]
        if direction: d["ref_direction"]=direction
        self.m.append(d)
        self.seen[key]=rid
        return rid

    def panel(self,role,outline,material,thickness,openings=()):
        item=dict(id=f"P{len(self.p)+1:04}",role=role,outline=[mm(p) for p in outline],
                  level=self.level(min(p[2] for p in outline)),material=material,thickness_mm=thickness)
        if openings: item["openings"]=[[mm(p) for p in ring] for ring in openings]
        self.p.append(item)

    def joint(self,kind,at,mids,ref=None,parts=None,description=None,instance=None,checks=None):
        if not mids: return
        key=(kind,tuple(mm(at)),ref,instance)
        if key in self.joints:
            prior=self.joints[key]
            for mid in mids:
                if mid not in prior["members"]: prior["members"].append(mid)
            return
        row=dict(id=f"J{len(self.c)+1:05}",type=kind,at=mm(at),members=list(dict.fromkeys(mids)))
        if ref: row["native_ref"]=ref
        if checks: row["checks"]=list(checks)
        if description: row["description"]=description
        if parts:
            row["parts"]=[dict(part,id=f"{row['id']}-{k+1}") for k,part in enumerate(parts)]
        self.c.append(row)
        self.joints[key]=row

    def chosen(self,role,k=None):
        rows=self.cfs[role]
        if k is not None:
            return next((r for r in rows if r.get("storey")==k),rows[0])
        return rows[0]

    def cold(self,role,a,b,*,k=None,direction=None):
        native=self.chosen(role,k)
        mid=self.member(role,a,b,ref="cfs:"+native["id"],direction=direction)
        if role=="purlin" and mid not in self.cleat_ids:
            import is811_sections as S
            self.cleat_ids[mid]=True
            sec=S.props(native["section"]); spec=self.cfg["cfs_connections_spec"]["purlin_cleat"]
            orientation=direction or [0,1,0]
            cleat=next(r for r in self.pkg["cfs_connections"] if r["id"].startswith("purlin-cleat-")); ref=cleat["id"]
            # Conservative full cleat reaction at 160 mm, on the 160 mm
            # wide projection. Strength uses IS 800 working plate bending.
            reaction=abs(cleat.get("value") or 0); seat_t=max(16,4*math.ceil(math.sqrt(6*reaction*160/(160*.75*230))/4))
            cid="layout:purlin-seat"
            if not any(c["id"]==cid for c in self.checks):
                dc=6*reaction*160/(160*seat_t**2*.75*230)
                self.checks.append(dict(id=cid,status="pass" if reaction and dc<=1 else "review",utilization=dc,
                       description=f"{seat_t} mm seat plate, 160 mm width. Complete governing native cleat reaction {reaction/1000:.2f} kN at 160 mm maximum projection, design plate stress 0.75 x 230 MPa.",reference="IS 800:2007 11.4.1(c); preliminary support geometry"))
            for end,op in ((a,b),(b,a)):
                # At a shared support the two span ends have distinct seats.
                length=math.dist(end,op)
                pos=tuple(i+.080*(j-i)/length for i,j in zip(end,op))
                parts=cleat_parts(mm(end),mm(op),spec,sec,orientation,int(native.get("n_ply") or 1),seat_t)
                self.joint("Purlin cleat",pos,[mid],"connection:"+ref,parts,
                           f"Three M16 bolts at 48 mm pitch in 18 mm holes and two 6 mm cleat fillets. {seat_t} mm seat on supporting flange with two 8 mm fillets.",checks=[cid])
        return mid

    def primary_frame(self,job):
        from openbim_handoff import _rolled_sections
        viewer=(job/"viewer_3d.html").read_text(encoding="utf-8")
        data=json.JSONDecoder().raw_decode(viewer.split("const DATA = ",1)[1])[0]
        nodes=data["nodes"]
        refs={r["id"] for r in self.pkg["lateral_frame"].get("connections") or []}
        self.hr_sections=_rolled_sections(); records=[]; supports={}
        for el in data["elements"]:
            a,b=[[x/1000 for x in nodes[str(t)]] for t in el["n"]]
            sec=el["sec"]
            kind=el["type"]
            rows=self.primary.get(sec,[])
            if not rows:
                raise ValueError(f"Primary section {sec} has no native design group")
            role=self.element_role[str(el["tag"])]
            row=next(r for r in rows if r["role"]==role)
            dr=([0,1,0] if el.get("wd")=="X" else [1,0,0]) if kind=="column" else None
            label=role.replace("_"," ") if role.startswith("truss_") else kind
            if self.b.number==9 and kind=="beam" and sec=="NPB240X120X34.32" and abs(a[0]-b[0])<.001:
                label="Truss upper chord" if max(a[2],b[2])>self.b.elevations[-1]+.001 else "Truss lower chord"
            if self.b.number in (1,2) and min(a[2],b[2])>=self.b.heights[-1]-.01 and (
                    kind=="brace" or (abs(a[0]-b[0])>1 and abs(a[1]-b[1])>1)):
                label="roof bracing"
            mid=self.member(label,a,b,ref="hr:"+row["id"],material="BR" if kind=="brace" and not role.startswith("truss_") else "HR",direction=dr)
            if kind=="column":
                for tag in el["n"]: supports.setdefault(tag,[]).append((mid,sec,el.get("wd")))
            records.append((el,a,b,sec,kind,mid,row))
        for el,a,b,sec,kind,mid,row in records:
            cr="conn-"+row["id"]
            if cr not in refs: continue
            nr="hr-connection:"+cr
            if kind=="column":
                low=min((a,b),key=lambda p:p[2])
                base_here=abs(low[2])<1e-5 or (self.b.number==6 and low[1]>10.5 and abs(low[2]-3)<1e-5)
                if base_here: self.base(low,mid,nr,sec,el.get("wd"))
            else:
                specs=self.cfg["lateral_frame"]["connections"]
                rowspec=next(c for c in self.pkg["lateral_frame"]["connections"] if c["id"]==cr)
                for node,end,op in ((el["n"][0],a,b),(el["n"][1],b,a)):
                    sup=supports.get(node,[]); linked=[mid,*[s[0] for s in sup]]
                    parts=[]; label="Brace end" if kind=="brace" else "Beam end"
                    detail=f"Native connection group {cr}"
                    if row["role"].startswith("truss_"):
                        sp=self.cfg["lateral_frame"]["hr_cfg_extra"]["truss_connections"]["default"]
                        parts=truss_end_parts(mm(end),mm(op),sp,self.hr_sections[sec]);label="Truss gusset"
                        detail=(f"Single angle bolted through its connected leg to {sp['gusset_t_mm']} mm gusset. {sp['n_bolts']} M{sp['d_mm']} bolts, "
                                f"{sp['pitch_mm']} mm pitch, {sp['gauge_mm']} mm gauge; {sp['gusset_free_mm']} mm maximum free gusset length.")
                    elif kind=="brace":
                        sp=specs["brace_end"]["default"]
                        parts=brace_end_parts(mm(end),mm(op),sp)
                        detail=(f"{sp['bolts']['n_bolts']} M{sp['bolts']['d_mm']} HSFG bolts through twin cheeks and central {sp['gusset']['t_mm']} mm gusset. "
                                f"Four CJP weld runs, effective {sp['welds']['length_mm']} mm each. Verify skewed joint workpoints, crop angles and groove preparation.")
                    if sup and kind=="beam" and row["role"] in ("floor","roof"):
                        _,column,orient=sup[0]; cd=self.hr_sections[column]; ux,uy=(abs(op[i]-end[i]) for i in (0,1)); den=math.hypot(ux,uy)
                        B,D=(float(cd[v]) for v in ("B_mm","D_mm")); cx,cy=(D,B) if orient=="X" else (B,D)
                        face=(cx*ux+cy*uy)/(2*den) if den else 0
                        release=(el.get("rel") or "fixed-fixed").split("-")
                        along="X" if ux>uy else "Y"; coords=self.b.y if along=="X" else self.b.x
                        base_coordinate=end[1] if along=="X" else end[0]
                        is_moment=any(dr==along and abs(coords[line]-base_coordinate)<.001 for dr,line in self.cfg["lateral_frame"]["moment_lines"])
                        if release[0 if node==el["n"][0] else -1]=="pinned": is_moment=False
                        fin=specs["beam_column"]["default"]["shear"] if is_moment else specs["beam_shear"]["default"]
                        cp=specs["beam_column"]["default"].get("cover_plate") if is_moment else None
                        parts=beam_end_parts(mm(end),mm(op),fin,self.hr_sections[sec],face,cp)
                        label="Moment connection" if cp else "Beam shear connection"
                        detail=f"Twin {fin['t_plate_mm']} mm fin plates, {fin['bolts']['n_bolts']} M{fin['bolts']['d_mm']} HSFG bolts, {fin['bolts']['d0_mm']} mm holes. Shop CJP to support on both plates over {fin['cjp']['length_mm']} mm."
                        if cp: detail+=" Cover plates both flanges with 14 mm fillets and CJP at column face."
                    self.joint(label,end,linked,nr,parts,description=detail,instance=mid)

    def base(self,at,mid,ref,section=None,axis=None):
        spec=(self.cfg.get("lateral_frame",{}).get("connections",{}).get("column_base",{}).get("default")
              or self.cfg["cfs_connections_spec"]["base"])
        if section:
            from openbim_handoff import _rolled_sections
            if not hasattr(self,"hr_sections"): self.hr_sections=_rolled_sections()
            row=self.hr_sections[section]
            sec=float(row["B_mm"]),float(row["D_mm"])
        else:
            sec=(160,250)
        an=spec["anchors"]
        self.joint("Column base",at,[mid],ref,parts=base_parts(mm(at),spec,sec,axis),
                   description=f"{spec['B_mm']} x {spec['L_mm']} x {spec['t_plate_mm']} mm plate, {an['n_total']} M{an['d_mm']} anchors, {an['embedment']['L_mm']} mm bonded below plate. Verify concrete cone, group action, grout and pedestal.")

    def portal_frame(self):
        g=self.pkg["portal_frame_geometry"]
        # Reassemble analysis stations into physical sticks at splices, eaves
        # and ridges. A knee is an individual diagonal, never a long polyline.
        raw={}
        for i,j,lab in g["elements"]:
            if "knee" in lab:
                raw[f"knee-{i}-{j}"]=[i,j]
            else:
                raw.setdefault(lab,[]).extend([i,j])
        joint_ends={}; carriers=[]; knees=[]
        for iy in range(g["n_frames"]):
            y=iy*g["spacing_mm"]/1000
            for label,nodes in raw.items():
                points=[g["nodes"][str(i)] for i in set(nodes)]
                a,c=max(((a,c) for a in points for c in points),key=lambda ac:math.dist(*ac))
                a,c=sorted([(a[0]/1000,y,a[1]/1000),(c[0]/1000,y,c[1]/1000)])
                role="column" if label.startswith("col") else "rafter" if label.startswith("raf") else "knee brace"
                mid=self.cold(role,a,c,direction=[0,1,0])
                (knees if role=="knee brace" else carriers).append((mid,a,c))
                if role=="column":
                    self.base(min((a,c),key=lambda p:p[2]),mid,"connection:column-base")
                if role in ("column","rafter"):
                    for p,q in ((a,c),(c,a)):
                        if p[2]<6: continue
                        d=math.dist(p,q)
                        joint_ends.setdefault(tuple(p),[]).append((mid,((q[0]-p[0])/d,(q[2]-p[2])/d)))
        for at,ends in joint_ends.items():
            key="apex" if at[2]>8 else "knee"
            parts=portal_gusset(mm(at),[v for _,v in ends],self.cfg["cfs_connections_spec"][key])
            self.joint(key.title()+" gusset",at,[mid for mid,_ in ends],"connection:"+key+"-bolt-group",parts,
                       "Twin 12 mm gussets, 3 rows by 5 M20 bolts per connected member; pitch and gauge 65 mm, objective edge distance 35 mm. Check shop copes and gusset geometry against the actual channel supply.")
        rc="layout:knee-terminals"
        self.checks.append(dict(id=rc,status="review",description="Verify the separately detailed pin-ended knee-brace terminal group and gusset eccentricity under axial forces.",reference="IS 801 7.5; native portal member axial envelope"))
        for mid,a,c in knees:
            for at,away in ((a,c),(c,a)):
                carrier,lo,hi=next((m,p,q) for m,p,q in carriers if abs(math.dist(p,at)+math.dist(at,q)-math.dist(p,q))<.002)
                axis=((away[0]-at[0])/math.dist(away,at),(away[2]-at[2])/math.dist(away,at))
                u=((hi[0]-lo[0])/math.dist(hi,lo),(hi[2]-lo[2])/math.dist(hi,lo))
                if sum(i*j for i,j in zip(axis,u))>0: u=(-u[0],-u[1])
                parts=portal_gusset(mm(at),[axis,u],dict(rows=1,cols=3,gauge_mm=55,pitch_mm=55,edge_mm=35,d_mm=16))
                self.joint("Knee brace terminal",at,[mid,carrier],parts=parts,checks=[rc],instance=mid,
                           description="Three M16 bolts in each attached end, twin 12 mm plates. Verify local connection force and fabrication clearances.")
        self.mezzanine()

    def mezzanine(self):
        h=3.5; xs=[.7,3.35,6,8.65,11.3]; ys=[.7,4.7,8.7]
        rc="layout:mezzanine-base"
        self.checks.append(dict(id=rc,status="review",description="Verify independent mezzanine base and edge pedestal against concurrent post and bracing reactions.",reference="IS 801 post and X-brace native envelopes; IS 800 working stress base"))
        for x in xs:
            for y in ys:
                mid=self.cold("mezzanine post",(x,y,0),(x,y,h)); spec=self.cfg["cfs_connections_spec"]["base"]
                self.joint("Mezzanine post base",(x,y,0),[mid],parts=base_parts(mm((x,y,0)),spec,(160,250),None),checks=[rc],
                           description="Independent 650 x 650 x 60 mm base; 8 M30 bonded anchors, 850 mm embedment. Verify combined forces at bracing terminals.")
            for a,b in zip(ys,ys[1:]): self.cold("mezzanine beam",(x,a,h),(x,b,h))
        joist_lines=[0,*xs[1:-1],12]
        for x,X in zip(joist_lines,joist_lines[1:]):
            for y in menu(ys[0],ys[-1],.4,True): self.cold("joist",(x,y,h),(X,y,h))
        self.panel("Mezzanine floor",[(0,ys[0],h),(12,ys[0],h),(12,ys[-1],h),(0,ys[-1],h)],"Board",18)
        self.assumptions.append("Mezzanine posts begin 0.7 m inside the portal lines. A 12 m floor plate spans four 2.65 m bays and two 0.7 m end cantilevers. The native design envelopes 3 m joist spans. The independent foundations retain 50 mm clear between adjacent 650 mm plates.")
        for x,y,dx,dy in ((xs[0],ys[0],2.65,0),(xs[-2],ys[-1],2.65,0),(xs[0],ys[0],0,4),(xs[-1],ys[1],0,4)):
            self.supplemental_brace((x,y,0),(x+dx,y+dy,h),"EA60X60X4","mezzanine-bracing")
            self.supplemental_brace((x+dx,y+dy,0),(x,y,h),"EA60X60X4","mezzanine-bracing")

    def supplemental_brace(self,a,b,profile,kind):
        # Native connection records provide tension checks for these diagonal
        # assemblies. They are supplemental physical members, not primary
        # frame elements in the transverse model.
        cid="layout:"+kind
        if cid not in [c["id"] for c in self.checks]:
            self.checks.append(dict(id=cid,description=f"{kind}: confirm terminal restraint, attachments and force transfer",
                                    reference="IS 801 7.3 / 7.5 or hot-rolled brace schedule",status="review"))
        if profile=="EA60X60X4": self.profiles[profile]=dict(family="L",dimensions_mm=dict(d=60,b=60,t=4,r=6))
        elif profile=="CLR100X50X15X2": self.profiles[profile]=dict(family="C",dimensions_mm=dict(d=100,b=50,t=2,lip=15,r=3))
        else: raise ValueError(profile)
        mid=self.member(kind,a,b,prof=profile,review=cid)
        group=kind+("-X" if a[0]!=b[0] else "-Y") if kind=="mezzanine-bracing" else kind
        native=next((r["id"] for r in self.pkg["cfs_connections"] if r["id"].startswith(group+"-")),None)
        if native:
            row=self.m[int(mid[1:])-1]; row["checks"]=list(dict.fromkeys([*row["checks"],"connection:"+native]))
        return mid

    def cold_sheds(self):
        n=self.b.number
        primary_x=n!=3
        length={1:48,2:76,3:30}[n]; half={1:9,2:10.5,3:6}[n]
        he={1:6,2:8,3:7}[n]; rise={1:1.5,2:1,3:1.4}[n]
        stations=self.b.x if primary_x else self.b.y
        width=half*(4 if n==3 else 2)
        def xyz(s,u,h): return (s,u,h) if primary_x else (u,s,h)
        pstep=self.cfg["cfs_members"]["purlins"]["spacing_mm"]/1000
        if n==3: pstep=min(pstep,self.cfg["portal"]["purlin_spacing_m"],1.2)
        transverse=[round(k*half,6) for k in range(round(width/half)+1)]
        for k,(u,v) in enumerate(zip(transverse,transverse[1:])):
            lo=he if k%2==0 else he+rise
            hi=he+rise if k%2==0 else he
            us=menu(u,v,pstep/math.sqrt(1+(rise/half)**2),True)
            if n in (1,2):
                # End-zone stays occur at the purlin stations; add closely
                # spaced stations within two beam depths of every joint.
                for top in (u,v):
                    for delta in (.75,1.5):
                        p=top+delta*(1 if top==u else -1)
                        if u<p<v: us.append(p)
                us=sorted(set(round(value,6) for value in us))
            for s,e in zip(stations,stations[1:]):
                fall=math.atan((hi-lo)/(v-u))
                ref=[0,math.cos(fall),math.sin(fall)] if primary_x else [-math.cos(fall),0,-math.sin(fall)]
                for t in us:
                    height=lo+(t-u)*(hi-lo)/(v-u)
                    self.cold("purlin",xyz(s,t,height),xyz(e,t,height),direction=ref)
                self.panel("Pitched roof",list(map(lambda p:xyz(*p),[(s,u,lo),(e,u,lo),(e,v,hi),(s,v,hi)])),"Deck",.7)
            if n in (1,2):
                cid="layout:fly-stays"
                if not any(a["id"]==cid for a in self.checks):
                    self.checks.append(dict(id=cid,status="review",description="Verify fly-stay force, flange connections and restraint continuity",reference="IS 18168 6.2 / beam lateral restraint schedule"))
                self.profiles["ISA60X60X6"]=dict(family="L",dimensions_mm=dict(d=60,b=60,t=6,r=7,r2=3))
                girder=self.cfg["lateral_frame"]["beam"]; depth=float(self.hr_sections[girder]["D_mm"])/1000
                for si,s in enumerate(stations):
                    for t in us:
                        height=lo+(t-u)*(hi-lo)/(v-u)
                        sign=1 if si==0 else -1 if si==len(stations)-1 else (1 if si%2==0 else -1)
                        self.member("Rafter fly stay",xyz(s,t,height-depth/2),xyz(s+sign*.65,t,height),
                                    prof="ISA60X60X6",material="HR",review=cid)
        gs=self.cfg["cfs_members"]["girts"]["spacing_mm"]/1000
        if n==3: gs=min(gs,1.2)
        for s,e in zip(stations,stations[1:]):
            for at in (0,width):
                self.cold("eave_strut",xyz(s,at,he),xyz(e,at,he))
                for z in menu(0,he,gs):
                    self.cold("girt",xyz(s,at,z),xyz(e,at,z),direction=[0,0,1 if at==0 else -1])
                self.panel("Side wall",[xyz(s,at,0),xyz(e,at,0),xyz(e,at,he),xyz(s,at,he)],"Deck",.7)
                if n in (1,2):
                    self.cold("girt",xyz(s,at,he/2),xyz(e,at,he/2),direction=[0,0,1 if at==0 else -1])
        for station in (stations[0],stations[-1]):
            for k,(u,v) in enumerate(zip(transverse,transverse[1:])):
                hi,lo=(he+rise,he) if k%2==0 else (he,he+rise)
                self.panel("Gable end wall",[xyz(station,u,0),xyz(station,v,0),xyz(station,v,hi),xyz(station,u,lo)],"Deck",.7)
        for idx in (0,len(stations)-2):
            s,e=stations[idx:idx+2]
            for u,v in zip(transverse,transverse[1:]):
                z1=he+rise if round(u/half)%2 else he
                z2=he+rise if round(v/half)%2 else he
                for a,c in ((xyz(s,u,z1),xyz(e,v,z2)),(xyz(e,u,z1),xyz(s,v,z2))):
                    if n==3:
                        self.supplemental_brace(a,c,"CLR100X50X15X2","roof-bracing")
                    elif not self.cfg["lateral_frame"]["gold"].get("benchmark_geometry"):
                        rr=next(r for r in self.pkg["lateral_frame"]["members"] if r["role"]=="brace")
                        check="layout:roof-bracing"
                        if not any(x["id"]==check for x in self.checks):
                            self.checks.append(dict(id=check,status="review",description="Roof-plane brace demand and gussets require verification",reference="IS 800 lateral load path"))
                        self.member("roof bracing",a,c,ref="hr:"+rr["id"],material="BR",review=check)
            if n==3:
                for u in (0,width):
                    for a,c in ((xyz(s,u,0),xyz(e,u,he)),(xyz(e,u,0),xyz(s,u,he))):
                        self.supplemental_brace(a,c,"CLR100X50X15X2","longitudinal-bracing")
        if n==2: self.annexes()

    def portal_restraints(self):
        """Provide real supports for the paired channel's declared 1200 mm unbraced length."""
        import is801_members as M
        import is811_sections as S
        from steltic_openbim_india.geometry import frame

        demand=max(abs(c["M_Nmm"])/220+abs(c.get("P_N",0)) for role in ("column","rafter")
                   for c in self.cfs[role][0]["checks"] if "M_Nmm" in c)
        force=max(15000,.025*demand)/.95
        fy=self.cfg["cfs_members"]["Fy_MPa"]
        sec=S.props("CLR100X50X15X2")
        cap=M.compression_allowable(sec,fy,700,700)["Pa_N"]
        bolt_check=M.bolted_connection_75(fy,2,16,force/2,2,30,90,T_member_N=force,bolt_class="8.8")
        rail_cap=M.compression_allowable(S.built_up("CLR250X80X25X5",2),fy,5000,5000)["Pa_N"]
        checks=[("stay",max(force/cap,bolt_check["dc"]),f"{force/1000:.2f} kN stay force (larger of 15 kN and 2.5% of native flange force, projected). 700 mm compression length. Two M16 at each attachment to 2 mm minimum sheet."),
                ("rail",4*force/rail_cap,f"Five-metre paired longitudinal rail. Accumulate four one-sided restraint forces ({4*force/1000:.2f} kN), permissible compression {rail_cap/1000:.2f} kN.")]
        for key,dc,desc in checks:
            self.checks.append(dict(id="restraint:"+key,status="pass" if dc<=1 else "fail",utilization=dc,
                                    description=desc,reference="Project restraint force envelope; IS 801 6.6 and 7.5"))
        review="restraint:transfer"
        self.checks.append(dict(id=review,status="review",description="Verify restraint rail anchorage and combined secondary bending, local flange transfer and longitudinal bracing under simultaneous restraint and wind. Provide girts and roof sheets continuous to the braced bays.",reference="IS 801 6.6, 6.7 and 7.5"))
        self.assumptions.append("Hyderabad paired-channel flanges have positive restraint at maximum 1200 mm along the analytical member. Interior posts have longitudinal rails and end-bay X-bracing. Apply project restraint reactions to the final cladding support and foundations.")
        def add_stay(a,b,normal):
            mid=self.member("Flange fly stay",a,b,prof="CLR100X50X15X2",review=review)
            self.m[int(mid[1:])-1]["checks"].append("restraint:stay")
            for pt,other in ((a,b),(b,a)):
                at=mm(pt); uv=[(t-s)/math.dist(pt,other) for t,s in zip(other,pt)]
                centers=[[x+d*y for x,y in zip(at,uv)] for d in (30,80)]
                parts=[bolt([p-12*v for p,v in zip(c,normal)],[p+12*v for p,v in zip(c,normal)],16) for c in centers]
                self.joint("Fly-stay attachment",pt,[mid],parts=parts,checks=["restraint:stay",review],instance=mid,
                           description="Two M16 8.8 at 50 mm pitch and 30 mm end distance. Confirm actual flange and rail connection planes before fabrication.")
        stations=self.b.y; levels=menu(0,7,1.2,True)[1:]; valley=12.0
        for s,e in zip(stations,stations[1:]):
            for z in levels[:-1]:
                rail=self.member("Centre column restraint rail",(valley,s,z),(valley,e,z),prof="2xCLR250X80X25X5",review=review)
                self.m[int(rail[1:])-1]["checks"].append("restraint:rail")
            if s in (stations[0],stations[-2]):
                for z,Z in zip([0,*levels[:-1]],levels):
                    for a,b in (((valley,s,z),(valley,e,Z)),((valley,e,z),(valley,s,Z))):
                        self.member("Centre column restraint X brace",a,b,prof="2xCLR250X80X25X5",review=review)
        def yoff(i):return .65 if i==0 or (i%2==0 and i<len(stations)-1) else -.65
        for i,s in enumerate(stations):
            for x in (0,valley,24):
                for z in levels[:-1]:
                    add_stay((x+(.125 if x!=24 else -.125),s,z),(x,s+yoff(i),z),[0,0,1])
        purlin_ends=set(tuple(p) for x in self.m if x["role"]=="purlin" for p in (x["start"],x["end"]))
        for x,y,z in sorted(purlin_ends):
            X,Y,Z=x/1000,y/1000,z/1000
            add_stay((X,Y,Z-.125),(X,Y+yoff(stations.index(Y)),Z),[1,0,0])
        # Stitch the two webs at the checked 180 mm maximum spacing. The
        # analytical portion between portal joints forms one physical stick.
        by_id={"cfs:"+r["id"]:r for r in self.pkg["cfs_members"]}
        for item in self.m:
            record=by_id.get(item.get("native_ref"),{})
            if record.get("n_ply")!=2 and not item.get("profile","").startswith("2x"): continue
            a,b=item["start"],item["end"]
            width,depth,axis=frame(a,b,item.get("ref_direction")); length=math.dist(a,b)
            count=max(2,math.ceil((length-120)/180)+1); parts=[]
            for k in range(count):
                dist=60+(length-120)*k/(count-1)
                for off in (-55,55):
                    center=[v+dist*u+off*w for v,u,w in zip(a,axis,depth)]
                    parts.append(bolt([v-11*u for v,u in zip(center,width)],[v+11*u for v,u in zip(center,width)],12))
            at=[(u+v)/2000 for u,v in zip(a,b)]
            self.joint("Back-to-back web stitches",at,[item["id"]],parts=parts,checks=[review],instance=item["id"],
                       description="Two rows of M12 at 110 mm gauge and 180 mm maximum longitudinal spacing. Confirm combined torsional shear and local web net section before manufacture.")

    def annexes(self):
        # Vestibule on west gable; platform frames 2 and 3, two post lines.
        for y in menu(6,10,.4,True):
            self.cold("lean-to roof joist",(-3,y,3.5),(0,y,3.6))
            self.cold("back-wall stud",(0,y,0),(0,y,3.6))
        for y in (7,9): self.cold("door jamb",(-3,y,0),(-3,y,2.4))
        self.cold("door header",(-3,7,2.4),(-3,9,2.4))
        self.panel("Airlock roof",[(-3,6,3.5),(0,6,3.6),(0,10,3.6),(-3,10,3.5)],"Deck",.7)
        xa,xb=self.b.x[2:4]
        for y in (2,4):
            zb=8+y/10.5
            for x in (xa,xb): self.cold("platform post",(x,y,zb),(x,y,zb+.6))
            self.cold("platform beam",(xa,y,zb+.6),(xb,y,zb+.6))
        self.panel("Condenser platform",[(xa,2,8.6+2/10.5),(xb,2,8.6+2/10.5),
                  (xb,4,8.6+4/10.5),(xa,4,8.6+4/10.5)],"Deck",4)

    def secondary_building(self):
        b=self.b; L=len(b.heights)
        planes=self.cfg.get("lateral_frame",{}).get("gold",{}).get("roof_planes",[])
        for k in range(1,L+1):
            low,high=b.elevations[k-1:k+1]
            now=b.cells(k); upper=b.cells(k+1) if k<L else set()
            for i,j in sorted(now):
                x,X=b.x[i:i+2]; y,Y=b.y[j:j+2]
                exposed=(i,j) not in upper
                podium=b.number==14 and k<=2
                if exposed and not podium:
                    plane=next((p for p in planes if abs(p["eave_z_m"]-high)<1e-6 and i in p["lines"] and i+1 in p["lines"]
                                and p["eave_coords_m"][0]<=y and Y<=p["eave_coords_m"][1]),None)
                    breaks=[y,Y]; height=lambda v:high
                    if plane:
                        lo,hi=plane["eave_coords_m"]; rd=plane["ridge_coord_m"]; rise=plane["ridge_z_m"]-high
                        height=lambda v:high+rise*((v-lo)/(rd-lo) if v<=rd else (hi-v)/(hi-rd))
                        if y<rd<Y: breaks.insert(1,rd)
                        self.panel("Ceiling diaphragm",[(x,y,high),(X,y,high),(X,Y,high),(x,Y,high)],"Deck",.8)
                    spacing=self.cfg["cfs_members"]["purlins"]["spacing_mm"]/1000
                    for ya,yb in zip(breaks,breaks[1:]):
                        za,zb=height(ya),height(yb)
                        theta=math.atan2(zb-za,yb-ya)
                        for t in menu(ya,yb,spacing*math.cos(theta),True):
                            self.cold("purlin",(x,t,height(t)),(X,t,height(t)),direction=[0,math.cos(theta),math.sin(theta)])
                        self.panel("Pitched roof" if plane else "Amenity deck" if b.number==11 else "Roof",
                                    [(x,ya,za),(X,ya,za),(X,yb,zb),(x,yb,zb)],"Deck",.7)
                else:
                    if not podium:
                        for t in menu(x,X,.4,True): self.cold("joist",(t,y,high),(t,Y,high))
                    if b.number==5 and (j==0 or (i==0 and y>=10)):
                        if j==0:
                            patches=[("Exterior walkway",x,y,X,y+1.5),("Floor",x,y+1.5,X,Y)]
                        else:
                            patches=[("Exterior walkway",x,y,x+1.5,Y),("Floor",x+1.5,y,X,Y)]
                    else: patches=[("Podium floor" if podium else "Floor",x,y,X,Y)]
                    for name,xa,ya,xb,yb in patches:
                        self.panel(name,[(xa,ya,high),(xb,ya,high),(xb,yb,high),(xa,yb,high)],"Slab" if podium else "Board",140 if podium else 18)
            if b.number==14 and k<=2: continue
            # High-bay external walls use girts; the office wing uses nonbearing studs.
            for side,(i,j),(I,J) in b.boundary(k):
                x,y=b.x[i],b.y[j]; X,Y=b.x[I],b.y[J]
                along_x=j==J
                highbay=b.number==4 and k==2 and (y<24 or Y<24 or (y==Y==24 and X<=6))
                if b.number==4 and k==2 and side=="S" and y==0: continue
                if b.number==5 and k==1 and side in ("S","N") and 18<=(x+X)/2<=27: continue
                if b.number==5 and side=="S" and y==0: y+=1.5; Y+=1.5
                if b.number==5 and side=="W" and y>=10: x+=1.5; X+=1.5
                if highbay:
                    for z in menu(0,high,1.5): self.cold("girt",(x,y,z),(X,Y,z),direction=[0,0,1])
                    self.panel("High bay wall",[(x,y,0),(X,Y,0),(X,Y,high),(x,y,high)],"Deck",.7)
                    continue
                D=math.hypot(X-x,Y-y); direction={"S":[-1,0,0],"N":[1,0,0],"W":[0,1,0],"E":[0,-1,0]}[side]
                def wallpoint(t,z): return (x+t,y,z) if along_x else (x,y+t,z)
                openings=[]
                window=b.number==9 and D>=3.5
                cut=((D-1.5)/2,(D+1.5)/2); sill=low+.9; head=low+2.1
                if window:
                    openings.append([wallpoint(cut[0],sill),wallpoint(cut[1],sill),wallpoint(cut[1],head),wallpoint(cut[0],head)])
                    for t in cut: self.cold("stud",wallpoint(t,low),wallpoint(t,high),k=k,direction=direction)
                    for zh in (sill,head): self.cold("header",wallpoint(cut[0],zh),wallpoint(cut[1],zh))
                self.panel("Exterior wall",[wallpoint(0,low),wallpoint(D,low),wallpoint(D,high),wallpoint(0,high)],"Deck",.7,openings)
                for t in menu(0,D,.4,True):
                    px,py=(x+t,y) if along_x else (x,y+t)
                    spans=((low,sill),(head,high)) if window and cut[0]<t<cut[1] else ((low,high),)
                    for z1,z2 in spans: self.cold("stud",(px,py,z1),(px,py,z2),k=k,direction=direction)
                if "girt" in self.cfs:
                    for z in menu(low,high,self.cfg["cfs_members"]["girts"]["spacing_mm"]/1000):
                        self.cold("girt",(x,y,z),(X,Y,z),direction=[0,0,1])

    def complete(self,job):
        if self.b.number==3:
            self.portal_frame()
        else:
            schedule=job/"lateral"/(self.pkg["building"]+"_lateral")/"design"/"member_schedule.csv"
            with schedule.open(encoding="utf-8-sig",newline="") as f:
                self.element_role={row["ele_tag"]:row["role"] for row in csv.DictReader(f)}
            # The native viewer provides physical node coordinates, element
            # tags, section and column major-axis orientation.
            self.primary_frame(job)
        if self.b.number<=3: self.cold_sheds()
        else: self.secondary_building()
        if self.b.number==3: self.portal_restraints()
        return dict(schema_version="1.0",project=dict(id=self.pkg["building"],name=f"{self.b.site} — {self.b.use}",
                    module="CFS",units="mm",design_status="review" if self.pkg["design_status"]["status"]!="complete" else "pass",
                    design_basis=["IS 801:1975 / IS 811:1987","IS 875 Parts 1–5","IS 1893 (Part 1):2016"]+
                        ([] if self.b.number==3 else ["IS 800:2007 / IS 18168:2023"])),
                    levels=self.levels,grids=dict(x=[dict(id=grid_line(i),coordinate_mm=round(x*1000,3)) for i,x in enumerate(self.b.x)],
                                               y=[dict(id=str(i+1),coordinate_mm=round(y*1000,3)) for i,y in enumerate(self.b.y)]),
                    materials=self.mat,profiles=self.profiles,members=self.m,panels=self.p,connections=self.c,checks=self.checks,assumptions=self.assumptions)
