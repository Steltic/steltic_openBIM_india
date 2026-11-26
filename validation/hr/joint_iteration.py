"""Size repeatable connection details using the preceding independent native run."""
import argparse
from copy import deepcopy
from functools import lru_cache
import json
import inspect
import math
from pathlib import Path

FILE = Path(__file__).with_name("joint_design_actions.json")
SHEAR_KEYS = {"t_plate_mm","h_plate_mm","fy_plate_MPa","fu_plate_MPa","bolts","block_shear_areas",
              "weld","cjp","n_plates","bolt_lines","gauge_mm","a1_mm","plate_grade"}


def actions(calc,cfg):
    rows = {}
    def record(spec, key, value):
        if isinstance(value,(float,int)):
            spec[key] = max(float(value),spec.get(key,0.))
    for c in calc.get("connections",[]):
        spec = rows.setdefault(c["section"],{})
        demand = c.get("demand",{})
        base_demand = demand.get("base_demands") or {}
        if all(isinstance(base_demand.get(k),(float,int)) for k in ("P_N","Mz_Nmm","My_Nmm","V_N")):
            load = {k:base_demand[k] for k in ("P_N","Mz_Nmm","My_Nmm","V_N")}
            if load not in spec.setdefault("base_combinations",[]):
                spec["base_combinations"].append(load)
        resultant = max(demand.get("V_P_resultant_N") or 0,demand.get("V_N") or 0) if "beam" in c.get("type","") else 0
        if resultant and resultant >= spec.get("collector_N",0):
            spec["collector_N"] = resultant
            spec["axial_fraction"] = min(1.,abs(demand.get("P_end_N") or 0)/resultant)
        for r in c.get("checks",[]):
            name = r.get("name","").lower()
            if "column base" in name:
                base=cfg.get("connections",{}).get("column_base",{}).get(c["section"],{})
                for k in ("B_mm","L_mm","t_plate_mm"):
                    record(spec,"base_"+k,base.get(k))
                for k in ("d_mm","n_per_row"):
                    record(spec,"anchor_"+k,base.get("anchors",{}).get(k))
                if "plate_thickness" in name:
                    record(spec,"plate_dc",r.get("dc"))
                elif "bearing" in name:
                    record(spec,"bearing_dc",r.get("dc"))
                elif "anchor_combined" in name:
                    record(spec,"anchor_dc",math.sqrt(max(0,r.get("dc") or 0)))
                elif "anchor_shear" in name or "anchor_tension" in name:
                    record(spec,"anchor_dc",r.get("dc"))
            for part,key in (("connection_shear","joint_shear_N"),("connection_moment","joint_moment_Nmm"),
                             ("brace_conn_1p2mp","brace_moment_Nmm"),("brace_conn_welds","brace_force_N"),
                             ("division_plate_bending","division_moment_per_mm"),("division_plate_shear","division_shear_per_mm"),
                             ("anchorage_embedment","anchor_tension_N")):
                if part in name:
                    record(spec,key,r.get("value"))
    return {k:v for k,v in rows.items() if v}


@lru_cache(maxsize=1)
def _cases():
    return json.loads(FILE.read_bytes()) if FILE.exists() else {}


def verify_base_trial(section, base, loads):
    """Re-evaluate actual concurrent native load cases as the ring is resized."""
    import hr_autosize as size
    import india_connections as con
    import sections
    props=sections.props(section)
    allowed=set(inspect.signature(con.base_plate_design).parameters)
    for _ in range(14):
        geo={k:v for k,v in base.items() if k in allowed}
        geo.update(col_d_mm=props["d"],col_bf_mm=props["bf"],col_tf_mm=props["tf"])
        failing={}
        corner=0.
        for load in loads:
            result=con.base_plate_design_biaxial(**load,**geo)
            for name,check in result["checks"].items():
                ratio=check.get("dc")
                if ratio is not None and ratio>.98:
                    failing[name]=max(failing.get(name,0.),ratio)
                if name=="anchorage_embedment":
                    corner=max(corner,check.get("value") or 0.)
        if not failing:
            break
        original=base
        base=size.bump_base(base,list(failing.items()),col=section)
        base["fixed"]=original["fixed"]
        a=base["anchors"]
        a["pitch_mm"]=math.floor(10*(min(base["B_mm"],base["L_mm"])-2*a["edge_mm"])/(a["n_per_row"]-1))/10
        if corner and a.get("embedment"):
            length=50*math.ceil(1.15*corner/(math.pi*a["d_mm"]*a["embedment"]["tau_bd_MPa"]*50))
            a["embedment"]["L_mm"]=max(a["embedment"]["L_mm"],length)
        if base==original:
            break
    return base


def revise(case, unit, cfg, refinement):
    if not 6<=case.number<=21:
        return
    import hr_autosize as size
    import sections
    from india_connection_design import beam_column_connection
    stages = _cases().get(str(case.number),{}).get(unit.name,{})
    specs = cfg["connections"]
    def previous(section):
        matched=[stages[k] for k in [section,*[s for s,t in refinement.get("sections",{}).items() if t==section and s!=section]] if k in stages]
        out={k:max(r.get(k,0.) for r in matched) for k in set().union(*matched) if k!="base_combinations"}
        out["base_combinations"]=[v for r in matched for v in r.get("base_combinations",[])]
        if matched:
            out["axial_fraction"]=max(matched,key=lambda r:r.get("collector_N",0.)).get("axial_fraction",0.)
        return out
    def names(tree):
        if isinstance(tree,str):
            yield tree
        elif isinstance(tree,dict):
            for value in tree.values():
                yield from names(value)
    beams = set(specs["beam_column"]) | set(specs["beam_shear"])
    for group in ("beam_sec","beam_sec_by_line","ebf_link_sec","ebf_beam_sec"):
        beams.update(names(cfg["gold"].get(group,{})))
    for section in sorted(s for s in beams if isinstance(s,str)):
        prior=previous(section)
        shear=prior.get("collector_N",0)
        if shear:
            trial=size.design_fin_plate(section,shear,template={"slip_surface":"sand_blasted"},
                                        margin=.94,n_frac=prior.get("axial_fraction",0))
            if trial:
                specs["beam_shear"][section]=trial
        if not any(f in ("OMRF","SMRF","EBF") for f in case.system):
            continue
        member=sections.props(section)
        design_shear=prior.get("joint_shear_N") or min(.5*member["Aw"]*230/(1.1*math.sqrt(3)),
                                                      (case.roof_dead+.75)*unit.sx*unit.sy*750)
        web=size.design_fin_plate(section,design_shear,template={"slip_surface":"sand_blasted"},margin=.94)
        spec=size.cover_plate_joint_spec(section,factor=1.45,continuity_t=max(25,math.ceil(member["tf"]/5)*5),
                                        doubler_t=max(25,math.ceil(member["tw"]/5)*5))
        # A full simple-connection declaration carries bolt/slip metadata in addition
        # to the nested web-plate geometry accepted by the moment-joint calculation.
        if web:
            spec["shear"]={k:v for k,v in web.items() if k in SHEAR_KEYS}
        spec["doubler_grade"]="E250"
        specs["beam_column"][section]=spec
        calculated=beam_column_connection(cfg,{"section":section},member,size.plate_fy(member["tf"],cfg["steel_grade"]))
        if not calculated.get("moment_capacity_Nmm") or not calculated.get("shear_capacity_N"):
            raise ValueError(f"Native connection geometry could not be evaluated for {section}")
    for section,spec in specs["brace_end"].items():
        prior=previous(section)
        props=sections.props(section)
        gusset=spec.get("gusset",{})
        weld=spec.get("welds",{})
        if not gusset or "cjp" not in weld:
            continue
        t=gusset["t_mm"]
        fy=size.plate_fy(t)
        demand=max(prior.get("brace_moment_Nmm",0),1.2*props["Zy"]*size.plate_fy(props["tf"],cfg["steel_grade"]))
        needed=math.sqrt(4*1.1*1.07*demand/(t*fy))
        width=max(gusset["w_start_mm"],math.ceil(needed/25)*25)
        weld["length_mm"]=max(weld["length_mm"],25*math.ceil(1.08*prior.get("brace_force_N",0)*math.sqrt(3)*1.25/
                                                (25*weld["cjp"]["t_mm"]*weld["fy_MPa"]*weld["n_sides"])))
        gusset["plate_width_mm"]=width
        effective=min(width,props["bf"]+2*weld["length_mm"]/math.sqrt(3))
        spec["moment_capacity_Nmm"]=t*effective**2*fy/(4*1.1)
        spec["moment_capacity_cite"]="IS 800 8.2. Gusset in-plane bending on the lesser of detailed plate width and spread from the connected flange."
    for section,spec in specs["column_splice"].items():
        transition=spec.get("transition")
        if not transition:
            continue
        prior=previous(section)
        # Maintain steel-grade thickness bands while solving per-mm bending and shear.
        selected=transition["t_mm"]
        for thickness in range(math.ceil(selected/5)*5,306,5):
            fy=size.plate_fy(thickness,transition.get("grade","E250"))
            if thickness**2*fy/(4*1.1) >= 1.07*prior.get("division_moment_per_mm",0) and (
                    thickness*fy/(math.sqrt(3)*1.1) >= 1.07*prior.get("division_shear_per_mm",0)):
                selected=thickness
                break
        transition["t_mm"]=selected
        spec["note"]=f"Both shafts CJP-welded to {selected:g} mm division plate, matching electrode and full UT. Verify plate availability and through-thickness properties."
    for section,base in specs["column_base"].items():
        prior=previous(section)
        if prior.get("base_t_plate_mm"):
            props=sections.props(section)
            thick=max(base["t_plate_mm"],prior["base_t_plate_mm"]*(math.sqrt(prior["plate_dc"])*1.06 if prior.get("plate_dc",0)>.96 else 1))
            thick=next((t for t in size.BASE_T_MM if t>=thick),5*math.ceil(thick/5))
            scale=math.sqrt(prior["bearing_dc"])*1.09 if prior.get("bearing_dc",0)>.96 else 1
            projection=max((max(base["B_mm"],prior["base_B_mm"]*scale)-props["bf"])/2,
                           (max(base["L_mm"],prior["base_L_mm"]*scale)-props["d"])/2)
            dia=max(int(prior["anchor_d_mm"]),base["anchors"]["d_mm"])
            old=int(prior["anchor_n_per_row"])
            demand_area=old*size.ANCHOR_ANB[int(prior["anchor_d_mm"])]*max(1,1.12*prior.get("anchor_dc",0))
            for trial_d in (d for d in size.ANCHOR_D if d>=dia):
                rows=max(2,math.ceil(demand_area/size.ANCHOR_ANB[trial_d]))
                edge=5*math.ceil(1.7*(trial_d+3)/5)
                if min(props["d"],props["bf"])+2*projection >= 2*edge+(rows-1)*2.5*trial_d:
                    dia=trial_d
                    break
            else:
                dia=size.ANCHOR_D[-1]
                rows=math.ceil(demand_area/size.ANCHOR_ANB[dia])
                projection=max(projection,(2*edge+(rows-1)*2.5*dia-min(props["d"],props["bf"]))/2)
            fixed=base.get("fixed",False)
            base=size.ring_base(section,base,d=dia,n=rows,t=thick,proj=projection)
            base["fixed"]=fixed
            a=base["anchors"]
            a["pitch_mm"]=math.floor(10*(min(base["B_mm"],base["L_mm"])-2*a["edge_mm"])/(a["n_per_row"]-1))/10
            specs["column_base"][section]=base
        anchors=base.get("anchors",{})
        if not anchors or not prior.get("base_combinations") and not prior.get("anchor_tension_N"):
            continue
        diameter=anchors["d_mm"]
        stress=1.2
        development=50*math.ceil(1.25*prior.get("anchor_tension_N",0)/(math.pi*diameter*stress*50))
        old_embedment=base.pop("embedment",None) or anchors.get("embedment") or {}
        anchors["embedment"]={"method":"bond","tau_bd_MPa":stress,"bar":"plain","L_mm":max(20*diameter,development,old_embedment.get("L_mm",0)),
                             "source":"Trial 1.2 MPa design bond for plain threaded steel in the M30 pedestal. Verify bond, group breakout, reinforcement and pedestal geometry.",
                             "cite":"IS 456 26.2.1.1, project-specific foundation design input."}
        if prior["base_combinations"]:
            specs["column_base"][section]=verify_base_trial(section,base,prior["base_combinations"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs",type=Path)
    parser.add_argument("--case",type=int,action="append",help="Update only the indicated case number(s)")
    args=parser.parse_args()
    data = deepcopy(_cases())
    for job in args.jobs.glob("IN_Ex*"):
        n=job.name.split("Ex")[-1]
        if args.case and int(n) not in args.case:
            continue
        for f in job.rglob("calc_package.json"):
            if f.parent.name!="design":
                continue
            label="Main" if f.parent.parent==job else f.parent.parent.name
            cfg=json.loads((f.parent/"cfg_snapshot.json").read_bytes())
            data.setdefault(n,{})[label]=actions(json.loads(f.read_bytes()),cfg)
    FILE.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
