"""Resolve one completed native CFS job, emit its exchange and portable results."""
import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from buildings import all_buildings
from grounding import dump
from layout import Layout


def grouped_checks(package):
    """Retain the governing native numeric row for each limit state and group."""
    results=[]
    for group,rows in (("cfs_member",package["cfs_members"]),("cfs_connection",package["cfs_connections"])):
        for row in rows:
            by_check={}
            for c in row.get("checks") or []:
                if not isinstance(c,dict) or c.get("informational"): continue
                key=c.get("check") or c.get("clause") or "check"
                prior=by_check.get(key)
                dc=c.get("dc")
                score=(2 if c.get("ok") is False else 1 if c.get("ok") is None else 0,
                       dc if isinstance(dc,(int,float)) and math.isfinite(dc) else -1)
                if prior is None or score>prior[0]:
                    by_check[key]=(score,{k:c[k] for k in ("value","limit","dc","ok","combo","clause","capacity_basis","allowable_increase") if k in c})
            for name,(_,record) in by_check.items():
                results.append(dict(group=group,member=row["id"],check=name,**record))
    return results


def add_lateral_evidence(summary,package,job):
    plan=json.loads((job/"load_plan.json").read_text(encoding="utf-8"))
    wind=plan.get("wind_summary") or {}
    summary["wind"]={k:wind[k] for k in ("Vb_mps","terrain_category","k1","k3","k4","Kd","Ka_X","Ka_Y","Cpe_X","Cpe_Y","VB_x_kN","VB_y_kN") if k in wind}
    collectors=package["lateral_frame"].get("collectors") or {}
    by_line={}
    for row in collectors.get("rows") or []:
        if row.get("N_N") is None: continue
        key=(row["level"],row["dir"],row.get("line"),row["role"],row["kind"])
        if key in by_line and abs(by_line[key]["N_kN"])>=abs(row["N_N"]/1000): continue
        by_line[key]=dict(level=row["level"],direction=row["dir"],line_m=row["line"]/1000 if row.get("line") is not None else None,
                           role=row["role"],action=row["kind"],N_kN=round(row["N_N"]/1000,5),native_element=row["beam"])
    if by_line:
        summary["native_lateral"]["collector_envelopes"]=dict(applied_to_member_checks=collectors["applied_to_member_checks"],
                   force_basis="Largest absolute axial force per collector line and direction for unit wind or earthquake. Chords are enveloped per level and direction. Positive is compression. Native IS 800 beam checks combine axial force with flexure.",
                   rows=list(by_line.values()))


def export(b,engine,job,target):
    from openbim_handoff import write_handoff
    cfg=json.loads((job/"independent-input.json").read_text(encoding="utf-8"))
    package=json.loads((job/"design/calc_package_cfs.json").read_text(encoding="utf-8"))
    layout=Layout(b,cfg,package).complete(job)
    samples=[];bearing={}
    if b.number in (5,6,7,10,12,13,14,15):
        from bearings import install_flat
        samples,bearing=install_flat(layout,package)
    handoff=write_handoff(job,layout)
    raw=handoff.read_bytes()
    model=json.loads(raw)
    target.mkdir(parents=True,exist_ok=True)
    (target/"handoff.json.gz").write_bytes(gzip.compress(raw,compresslevel=9,mtime=0))
    native=package["lateral_frame"]
    brief=next((engine/"test_buildings").glob(f"IN_CFS_Ex{b.number}_*.txt"))
    status=package["design_status"]
    snow=cfg["load_plan"]["snow_summary"]
    gov=cfg["loads"]
    evidence=[]
    for hit in cfg["load_plan"]["retrieval"]:
        row={k:hit[k] for k in ("stem","query","found","cite","purpose","source","verify","value") if k in hit}
        if hit.get("file"):
            r=json.loads((job/hit["file"]).read_text(encoding="utf-8"))
            row.update(source_file=r["source_file"],source_sha256=r["source_sha256"])
        evidence.append(row)
    # Reproducible public record contains locators and original calculations;
    # native reports, source PDFs, retrieval quotes and hit files stay local.
    summary=dict(case=cfg["name"],city=b.site,occupancy=b.use,source_brief=brief.name,
        source_brief_sha256=hashlib.sha256(brief.read_bytes()).hexdigest(),
        upstream="Steltic/steltic_CFS_india",upstream_design_commit="6e43e5839a84358a6a23356b2de4d59ab914a38b",
        producer_sha256=hashlib.sha256((engine/"steel_engine/openbim_handoff.py").read_bytes()).hexdigest(),
        authored_input_sha256=hashlib.sha256((job/"independent-input.json").read_bytes()).hexdigest(),
        dimensions=dict(x_m=b.x[-1],y_m=b.y[-1],storey_heights_m=b.heights,
                        floor_plan_area_m2=[round(b.area(i),3) for i in range(1,len(b.heights)+1)]),
        design_status=status["status"],authority=status["authority"],
        reasons=status["reasons"],site={k:cfg["site"][k] for k in ("city","zone","Z","Vb","soil","terrain_category","Kd","cyclone_belt","wind_structure_class")},
        occupancy_basis=cfg["occupancy"],gravity=gov,snow=snow,
        dead_load_build_up_kNm2={"roof":({"insulated_panels":.32,"services":.38,"secondary_and_miscellaneous":.20} if b.number==2
            else {"sheets_and_accessories":.17,"services":.25,"secondary_and_miscellaneous":.18} if b.number in (1,3,4)
            else {"deck_and_finishes":.55,"services_and_miscellaneous":round(gov["D_roof"]-.55,3)}),
            "floor":{"board_and_finishes":.95,"ceiling_and_services":.45,"secondary_and_miscellaneous":.25},
            **({"podium_L1":{"slab_and_deck":3.55,"services_and_finishes":.95},
                "podium_L2":{"slab_and_deck":3.55,"court_finishes_services":1.45}} if b.number==14 else {})},
        eor_inputs=cfg["eor_inputs"],assumptions=model["assumptions"],
        combined_load_sets=len(package.get("cfs_combinations") or []),cfs_check_groups=grouped_checks(package),
        native_member_groups=[{k:m[k] for k in ("id","role","section","n_ply","DC","ok","length_mm","storey","Fy_MPa") if k in m} for m in package["cfs_members"]],
        native_lateral=dict(system=native.get("system"),R=native.get("R"),R_x=native.get("R_x"),R_y=native.get("R_y"),
            method=(native.get("seismic_analysis") or {}).get("method"),drift=native.get("drift_table"),
            seismic={k:v for k,v in (native.get("seismic_summary") or {}).items()
                     if k in ("zone","Z","I","R","R_x","R_y","soil","Ta","T","Ta_s","Ta_x_s","Ta_y_s","Sa_g","Ah","VB_kN","VB_frame_kN","W_kN","W_frame_kN","W_mezzanine_total_kN","VB_mezzanine_kN")},
            members=native.get("members"),connections=native.get("connections"),wind_vs_eq=native.get("wind_vs_eq"),
            irregularity=native.get("irregularity"),flexible_diaphragm_run=(native.get("seismic_analysis") or {}).get("flexible_diaphragm_run"),
            diaphragm=[{key:row[key] for key in ("storey","dir","F_EQ_N","F_W_N","governing","v_unit_kN_per_m","chord_force_kN","dc","ok","demand_evaluated") if key in row} for row in package.get("diaphragm",[])]),
        physical_layout=dict(roles=dict(Counter(m["role"] for m in model["members"])),panel_roles=dict(Counter(p["role"] for p in model["panels"])),
            part_counts=dict(Counter(q["kind"] for c in model["connections"] for q in c.get("parts",[]))),
            joint_types=dict(Counter(c["type"] for c in model["connections"])),panel_openings=sum(len(p.get("openings",[])) for p in model["panels"]),
            member_workpoint_top_mm=max(max(m["start"][2],m["end"][2]) for m in model["members"]),
            declared_roof_planes=(cfg.get("lateral_frame",{}).get("gold",{}).get("roof_planes") or []),
            floor_footprints_m=[dict(level=i,occupied_rectangles=region) for i,region in enumerate(b.regions,1)]),
        grounding=evidence,physical_member_count=len(model["members"]),physical_panel_count=len(model["panels"]),
        connection_occurrences=len(model["connections"]),profile_count=len(model["profiles"]),
        handoff_sha256=hashlib.sha256(raw).hexdigest(),native_files=model["source_evidence"]["files"])
    if b.number==14:
        extra=cfg["lateral_frame"]["hr_cfg_extra"]
        summary["gravity_by_level_kNm2"]={k:{"permanent":extra["D_by_level"][k],"imposed":extra["L_by_level"][k]} for k in extra["D_by_level"]}
    add_lateral_evidence(summary,package,job)
    if samples:
        dump(target/"bearing-samples.json",samples)
        summary["installed_bearings"]=bearing
    dump(target/"result.json",summary)
    print(cfg["name"],status["status"],len(model["members"]),"members",summary["handoff_sha256"][:12],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case",type=int,choices=range(1,16))
    parser.add_argument("--engine",type=Path,required=True)
    parser.add_argument("--jobs",type=Path,required=True)
    parser.add_argument("--target",type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    sys.path.insert(0,str(args.engine.resolve()/"steel_engine"))
    b=all_buildings()[args.case-1]
    label=f"IN_CFS_Ex{b.number}"
    export(b,args.engine.resolve(),args.jobs.resolve()/label,args.target.resolve()/label)


if __name__=="__main__":
    main()
