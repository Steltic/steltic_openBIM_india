"""Pune's capacity-protected EBF and physical link detailing for the HR examples."""
from math import ceil


def revise(case, unit, cfg, refinement, ground):
    """Select continuous links, surrounding beams, braces, and bolted/CJP joints."""
    import frame_build
    import hr_autosize as size
    from joint_iteration import SHEAR_KEYS

    link = "WPB400X400X239.62"
    brace = "WPB400X400X219.67"
    gold = cfg["gold"]
    stories = [str(k) for k in range(1, len(unit.heights) + 1)]
    for role in ("ebf_link_sec", "ebf_beam_sec"):
        gold[role] = {d: {k: link for k in stories} for d in ("X", "Y")}
    gold["ebf_brace_sec"] = {k: brace for k in stories}
    cfg["column_imposed_load_reduction"] = True
    # Native floor masses include the analysis members. Secondary joists, link
    # restraints and their detail steel are physical additions to that list.
    cfg["extra_mass_floors"] = dict(enumerate((.9,.9,.9,.9,.75,1.,1.,.60),1))
    frame_build.attach_gold(cfg, gold)
    # True one-way X secondary spans deliver the tributary to Y girders.
    # The native concurrent shear at this family reached 375.8 kN.
    floor_girder="WPB800X300X171.52"
    end=size.design_fin_plate(floor_girder,500_000,template={"slip_surface":"sand_blasted"},
                              V_service_N=335_000,margin=.90,n_frac=.12)
    if end is None:raise ValueError("Pune one-way floor girder has no adequate end connection")
    cfg["connections"]["beam_shear"][floor_girder]=end
    for section in (link, "WPB700X300X240.51"):
        member = size.props(section)
        detail = size.cover_plate_joint_spec(section, factor=1.70,
            continuity_t=max(30, 5 * ceil(member["tf"] / 5)), doubler_t=30)
        web = size.design_fin_plate(section, 500_000, template={"slip_surface": "sand_blasted"}, margin=.94)
        if web is None:
            raise ValueError(f"No 500 kN web connection fits {section}")
        detail["shear"] = {k: v for k, v in web.items() if k in SHEAR_KEYS}
        detail["doubler_grade"] = "E250"
        cfg["connections"]["beam_column"][section] = detail
        if section == link:
            # The complete secondary-steel takeoff raised the native concurrent
            # collector actions to 1.979034 MN axial and 77.872 kN shear.
            import india_connections as joints
            import india_connection_design as checked_joints
            rows, lines, gauge, thickness = 3, 5, 75., 50.
            collector = size.double_fin(size.fin_plate_spec(section, rows, 24, thickness,
                {"slip_surface": "sand_blasted"}, n_lines=lines, gauge=gauge), section)
            collector["bolts"]["n_e"] = 2
            steel = collector["bolts"]
            holes = steel["d0_mm"]
            run = steel["e_mm"] + (lines - 1) * gauge
            width = (rows - 1) * steel["p_mm"]
            web_t = member["tw"]
            path = dict(Avg_mm2=2*run*web_t, Avn_mm2=2*(run-(lines-.5)*holes)*web_t,
                        Atg_mm2=width*web_t, Atn_mm2=(width-(rows-1)*holes)*web_t)
            web_block = joints.block_shear(**path, fy_MPa=size.plate_fy(web_t), fu_MPa=410, demand_N=2_000_000)
            plate = joints.fin_plate_shear_checks(V_N=2_000_000, V_shear_N=80_000, N_axial_N=1_999_000,
                **{k:v for k,v in collector.items() if k in SHEAR_KEYS})
            slip = checked_joints.hsfg_slip_checks(steel, collector["bolt_type"], 2_000_000/1.5,
                                                   2_000_000, slip_surface=collector["slip_surface"])
            if not size.fin_plate_fits(section,rows,24) or max(web_block["check"]["dc"], plate["dc"],
                    *(r["dc"] for r in slip.values() if r.get("dc") is not None)) > .97:
                raise ValueError("Outside-link collector steel, bolt slip or geometry fails")
            collector["detail"] = (f"Paired {thickness:g} mm fins, five longitudinal lines of three M24 HSFG "
                f"bolts, 75 mm pitch and gauge, two slip planes. Parent web block shear D/C "
                f"{web_block['check']['dc']:.3f} at 2.000 MN.")
            cfg["connections"]["beam_shear"][section] = collector
            detail["shear"]={k:v for k,v in collector.items() if k in SHEAR_KEYS}
    if brace not in cfg["connections"]["brace_end"]:
        raise ValueError(f"Missing capacity-protected brace-end design for {brace}")
    roof_beam="NPB600X220X107.57"
    roof_fin=size.design_fin_plate(roof_beam,310_000,template={"slip_surface":"sand_blasted"},margin=.90)
    if roof_fin is None:raise ValueError("Missing 310 kN roof beam web connection")
    cfg["connections"]["beam_shear"][roof_beam]=roof_fin
    splices=cfg["connections"]["column_splice"]
    for h,minimum in (("BOX450X450X22",40),("BOX400X400X32",40)):
        splice=splices[h]
        thickness=max(minimum,splice["transition"]["t_mm"])
        splice["transition"]["t_mm"]=thickness
        splice["note"]=f"Both shafts CJP to a {thickness:g} mm E250 B0 division plate, with full UT."
    stem = "IS_18168_2023"
    for page, clause, match in ((9, "6.3.1", r"6\.3\.1"), (10, "6.3.3", r"6\.3\.3"),
            (15, "11.2 and 11.4.1", r"11\.4\.1"), (16, "11.4.2", r"11\.4\.2"),
            (21, "12.3.2.2 and 12.3.3", r"12\.3\.2\.2"), (22, "12.3.4.4 and 12.3.4.5", r"12\.3\.4\.4")):
        ground.page(stem, match, "IS 18168, " + clause, pages=[page],
                    inputs={"link_section": link, "brace_section": brace, "centre_link_length_mm": 900})
    ground.page("IS_875_Part_2_1987", r"3\.2\.1", "IS 875 Part 2, 3.2.1 and exceptions",
                pages=[14], inputs={"office_floor_imposed_kNm2": 4, "partition_allowance_kNm2": 1,
                                     "column_imposed_load_reduction": True})


def draw_links(model):
    """Link plates and brace-to-secondary restraints are modeled after the native analysis."""
    from physical_ebf import add_link_assemblies
    add_link_assemblies(model)
    if model.case.number == 15:
        from json import loads
        from handoff import check
        summary=loads((model.folder/"pune_full_imposed.json").read_text(encoding="utf-8"))
        if summary["parent_calc_sha256"] != _digest(model.folder/"design"/"calc_package.json"):
            raise ValueError("Pune full-imposed companion belongs to another native analysis")
        verified_companion(model.folder,summary["calc_sha256"])
        check(model.data["checks"],model.pre+"FULL-IMPOSED",
              f"All eight-storey and five-storey wing columns also checked with 100% imposed load. "
              f'{summary["columns"]} native column groups, governing {summary["governing_column"]}.',
              "pass" if summary["status"]=="complete" else "fail",summary["column_max_dc"],
              "IS 875 Part 2 3.2.1, stepped floor combinations. Companion calculation SHA-256 "+summary["calc_sha256"])
        model.data["assumptions"].append("Secondary joists, link flange restraints and connection steel are added to the "
            "primary model as 0.90 kN/m² at levels 1–4, 0.75 at level 5, 1.00 at levels 6–7 and 0.60 at the upper roof. "
            "The complete 100%-imposed companion envelopes floor-count differences "
            "at the five-storey leg and adjoining eight-storey column stacks.")


def validate_detail_weight(model):
    """Reconcile the measured exchange steel with the native additional gravity and mass."""
    from collections import defaultdict
    from math import dist,hypot,pi
    from briefs import floor_cells
    from handoff import check
    from steltic_openbim_india.profiles import section_polygons
    from steltic_openbim_india.geometry import cross,sub

    def area(ring):
        vector=[0.,0.,0.]
        for a,b in zip(ring,ring[1:]+ring[:1]):
            for i,v in enumerate(cross(sub(a,ring[0]),sub(b,ring[0]))):vector[i]+=v
        return hypot(*vector)/2
    mass=defaultdict(float)
    areas={}
    for row in model.data["members"]:
        if row["unit"]!=model.u.name or row.get("source_element") or row.get("source_elements"):continue
        key=row["profile"]
        if key not in areas:areas[key]=sum(p.area for p in section_polygons(model.data["profiles"][key]))
        mass[row["level"]]+=areas[key]*dist(row["start"],row["end"])*7.85e-6
    for joint in model.data["connections"]:
        if joint["unit"]!=model.u.name:continue
        for p in joint.get("parts",()):
            if p["kind"]=="plate":
                volume=(area(p["outline"])-sum(area(h) for h in p.get("openings",[])))*p["thickness_mm"]
            elif p["kind"]=="bolt":volume=pi*p["diameter_mm"]**2/4*dist(p["start"],p["end"])
            elif p["kind"]=="weld":
                if p.get("weld_type")=="cjp":
                    area_mm2=p["throat_mm"]*p.get("width_mm",p["throat_mm"])
                else:
                    area_mm2=.5*p["leg_mm"]**2
                volume=area_mm2*dist(p["start"],p["end"])
            else:raise ValueError("Unclassified detail steel on "+joint["id"])
            mass[joint["level"]]+=volume*7.85e-6
    for k,z in enumerate(model.datums[1:],1):
        level=model.level(z)
        plan=len(floor_cells(model.u,k))*model.u.sx*model.u.sy
        selected=model.cfg["extra_mass_floors"][k]
        actual=mass[level]*9.81/(1000*plan)
        check(model.data["checks"],model.pre+f"STEEL-MASS-{k}",
              f"Storey {k} supplementary steel weighs {actual:.3f} kN/m² over {plan:g} m². "
              f"Gravity and seismic allowance {selected:.2f} kN/m².",
              "pass" if actual<=selected else "fail",actual/selected,"IS 875 Part 1 and IS 1893 Part 1 7.3; source IFC quantities")


def _digest(path):
    from hashlib import sha256
    return sha256(path.read_bytes()).hexdigest()


def verified_companion(jobdir,expected):
    import gzip
    from hashlib import sha256
    private=jobdir/"design"/"full_imposed_calc.json.gz"
    if private.is_file() and sha256(gzip.decompress(private.read_bytes())).hexdigest()==expected:return
    raw=(jobdir.parent/(jobdir.name+"-FULL-IMPOSED")/"design"/"calc_package.json").read_bytes()
    if sha256(raw).hexdigest()!=expected:raise ValueError("Pune companion file failed its SHA-256 verification")
    temp=private.with_suffix(".tmp")
    temp.write_bytes(gzip.compress(raw,compresslevel=6,mtime=0))
    temp.replace(private)


def verify_full_imposed(name,cfg,jobdir):
    """Guard the engine's global storey-count reduction at Pune's stepped roof."""
    import json
    import pipeline
    from shutil import copytree
    from static_model import imposed_load_reduction_321

    audit_name=name+"-FULL-IMPOSED"
    full=dict(cfg, column_imposed_load_reduction=False)
    copytree(jobdir/"rag",jobdir.parent/audit_name/"rag",dirs_exist_ok=True)
    result=pipeline.design_and_report(audit_name,full)
    if result.get("blocked") or result.get("error"):
        raise ValueError("Pune unreduced imposed-load companion encountered a native analysis error")
    calc=jobdir.parent/audit_name/"design"/"calc_package.json"
    data=json.loads(calc.read_bytes())
    columns=[r for r in data["members"] if r["inputs"].get("role","").endswith("_col")]
    if not columns:raise ValueError("Pune companion has no checked native column groups")
    control=max(columns,key=lambda row:row["DC"])
    summary=dict(status=data["design_status"]["status"],calc_sha256=_digest(calc),
        parent_calc_sha256=_digest(jobdir/"design"/"calc_package.json"), columns=len(columns),
        column_max_dc=control["DC"],governing_column=control["id"],
        available_reductions_by_storey={str(n):[imposed_load_reduction_321(n-k+1) for k in range(1,n+1)]
                                       for n in (5,8)})
    verified_companion(jobdir,summary["calc_sha256"])
    (jobdir/"pune_full_imposed.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
