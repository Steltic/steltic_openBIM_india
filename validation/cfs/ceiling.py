"""Gravity support of the horizontal roof diaphragm beneath a pitched roof."""
from collections import defaultdict
import math
from bearings import Sections
from connection_parts import bolt, circ, plate
from openbim_handoff import _profile
from steltic_openbim_india.profiles import section_polygons


def install(model,pkg):
    import is801_members as M
    import is811_sections as S
    panels=[p for p in model["panels"] if p["role"]=="Ceiling diaphragm"]
    if not panels:return [],{}
    sections=Sections(model,pkg);down=(0,0,-1)
    hosts=defaultdict(list)
    for m in model["members"]:
        a,b=m["start"],m["end"]
        if m["role"] not in ("beam","Truss lower chord") or abs(a[2]-b[2])>.1 or abs(a[0]-b[0])>.1:continue
        hosts[round(a[0]),round(a[2])].append((min(a[1],b[1]),max(a[1],b[1]),m))
    FY=model["materials"]["CF"]["fy_mpa"]
    cap={};conditions={};counts=defaultdict(int)
    code="CLR180X80X25X4";source=S.props(code);nom="Ceiling-"+code
    model["profiles"][nom]=_profile(code,1,{},section_polygons);depth=source["h"]
    model["materials"]["Stud anchor"]={"grade":"Weldable low-carbon threaded stud, minimum Fy 235 MPa",
        "standard":"Project benchmark unit; 2.5 kN minimum tested working tension per complete stud and weld"}
    verify="layout:ceiling-fixing"
    model["checks"].append(dict(id=verify,status="review",description="Verify certified 2.5 kN working tension per welded stud, installation quality, diaphragm fastener slip and full tested sheeting capacity under in-plane actions.",reference="IS 801 7 and 8; structural diaphragm product testing"))
    for p in panels:
        xs=[q[0] for q in p["outline"]];ys=[q[1] for q in p["outline"]];z=p["outline"][0][2]
        x,X=min(xs),max(xs);y,Y=min(ys),max(ys);span=X-x;count=math.ceil((Y-y)/800)
        spacing=(Y-y)/count
        load=.25*spacing/1000+source["mass_kg_m"]*9.81/1000
        action=load*span**2/8;reaction=load*span/2
        label=f"ceiling:{span:.1f}:{spacing:.1f}"
        if label not in cap:
            bending=M.bending_allowable(source,FY,span,compression_flange_restrained=False)
            shear=M.web_shear_64(source,FY,reaction)
            inertia=bending["Sx_eff_cm3"]*1000*depth/2
            defl=5*load*span**4/(384*200000*inertia)
            dc=max(action/bending["Ma_Nmm"],shear["dc"],defl/(span/360),reaction/(2*2500))
            cap[label]=dc
            model["checks"].append(dict(id=label,status="pass" if dc<=1 else "fail",utilization=dc,
              description=f"Unbraced CFS ceiling joist {span:.0f} mm span at {spacing:.0f} mm. Ceiling lining/services 0.25 kPa plus joist {source['mass_kg_m']:.2f} kg/m; M={action/1e6:.3f} kNm, R={reaction/1000:.3f} kN, deflection {defl:.2f} mm. Two studs per end, 2.5 kN tested allowable each.",
              reference="IS 801 5.2.1.1, 6.1–6.4; L/360 service criterion"))
            if dc>1:raise ValueError(f"Ceiling joist {label} fails with D/C {dc:g}")
        underside=None
        for i in range(count):
            by=y+(i+.5)*spacing
            peers=[]
            for hx in (x,X):
                row=next((m for lo,hi,m in hosts[round(hx),round(z)] if lo-.1<=by<=hi+.1),None)
                if row is None:raise ValueError(f'Missing ceiling supporting chord beneath {p["id"]} at {hx,by,z}')
                peers.append(row)
            heights=[sections.limits(h,down)[1] for h in peers]
            if abs(heights[0]-heights[1])>.1:raise ValueError(f'Ceiling {p["id"]} has unequal girder soffits')
            soffit=z-heights[0];cz=soffit-depth/2
            if underside is not None and abs(underside-(soffit-depth))>.1:raise ValueError("Split ceiling support heights")
            underside=soffit-depth;mid=f'{p["id"]}-CJ{i+1}'
            model["members"].append(dict(id=mid,role="Ceiling joist",start=[x,by,cz],end=[X,by,cz],ref_direction=[0,1,0],profile=nom,
                material="CF",level=p["level"],checks=[label,verify]))
            for end,sign,host in ((x,1,peers[0]),(X,-1,peers[1])):
                jid=mid+("-A" if sign==1 else "-B");parts=[]
                for dist in (18,45):
                    cx=end+sign*dist;cy=by+5
                    h=soffit-source["t"]-4
                    pt=lambda u,v:[cx+u,cy+v,h]
                    ring=[pt(-10,-10),pt(10,-10),pt(10,10),pt(-10,10)]
                    parts.append(plate(ring,4,[circ(0,0,5.5,pt)]))
                    parts.append(dict(bolt([cx,cy,h-6],[cx,cy,soffit],10),material="Stud anchor"))
                model["connections"].append(dict(id=jid,type="Ceiling joist suspension",at=[end+32*sign,by,soffit],
                    members=[host["id"],mid],checks=[label,verify],
                    parts=[dict(part,id=jid+"-"+str(j+1)) for j,part in enumerate(parts)],
                    description="Two welded M10 studs and 20 x 20 x 4 mm washers. Shop-punch 11 mm joist flange holes. Verify cold-store or indoor corrosion system and specified tested working tension."))
                typ="Ceiling diaphragm / "+sections.profile(host)[0]+" / "+nom
                counts[typ]+=1
                conditions.setdefault(typ,dict(id=typ,chain=[host["id"],mid,p["id"]],normal=list(down),
                    stations_mm=[[end+sign*35,by-8,soffit]],expected_gaps_mm=[0.,0.],tolerance_mm=1.,
                    structural_datum_mm=z,ceiling_top_below_datum_mm=round(z-underside,3)))
        p["analysis_plane_mm"]=p["outline"]
        p["outline"]=[(qx,qy,round(underside-p["thickness_mm"],4)) for qx,qy,_ in p["outline"]]
    model["assumptions"].append("The nonwalkable horizontal ceiling diaphragm is attached to dedicated unbraced ceiling joists below the primary roof tie beams. Two shop-welded M10 studs per end transfer gravity. Ceiling/services and secondary steel draw on the declared roof allowances. Verify stud working load and tested in-plane diaphragm screw schedule before issue.")
    return list(conditions.values()),{k:{"joist_ends":v,"ceiling_top_below_datum_mm":conditions[k]["ceiling_top_below_datum_mm"]} for k,v in counts.items()}
