import copy
import gzip
import hashlib
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.placement
import ifcopenshell.validate
import pytest

from steltic_openbim_india.composite import clearances, plate_clashes
from steltic_openbim_india.delivery import deliver
from steltic_openbim_india.model import load, validate, verify_source_files
from steltic_openbim_india.profiles import section_polygons


FIXTURE=Path(__file__).parent/"fixtures"/"metric_frame.json"


def fixture():
    return load(FIXTURE)[0]


def test_complete_penetration_groove_on_paper_and_in_step(tmp_path):
    import pymupdf
    from shapely.geometry import Polygon
    from steltic_openbim_india.audit import audit

    data=fixture()
    joint=data["connections"][0]
    weld=dict(kind="weld",weld_type="cjp",start=[0,-10,0],end=[0,-10,150],
              ref_direction=[1,0,0],material="E250",throat_mm=10)
    joint["parts"].extend([dict(weld,id="G1",width_mm=16),dict(weld,id="G2")])
    handoff=tmp_path/"groove.json"
    handoff.write_text(json.dumps(data),encoding="utf-8")
    folder=tmp_path/"issued"
    cert=deliver(handoff,folder)
    assert cert["artifact_status"]=="pass",cert["findings"]
    model=ifcopenshell.open(str(folder/"model.ifc"))
    welds={p.Tag:p for p in model.by_type("IfcFastener") if p.PredefinedType=="WELD"}
    def section(tag):
        return welds[tag].Representation.Representations[0].Items[0].SweptArea.OuterCurve
    def area(tag):
        return Polygon([p.Coordinates for p in section(tag).Points])
    assert area("G1").bounds==(-8,-5,8,5) and area("G1").area==160
    assert area("G2").bounds==(-5,-5,5,5) and area("G2").area==100
    assert area("WELD1").area==18
    with pymupdf.open(folder/"drawings.pdf") as doc:
        paper=" ".join(" ".join(p.get_text().split()) for p in doc)
    assert "CJP throat 10 x width 16 mm" in paper
    assert "CJP throat 10 x width 10 mm" in paper
    assert "leg 6 mm" in paper
    # Replace the saved body with a real fillet, preserving the declared source and IFC properties.
    welds["G1"].Representation.Representations[0].Items[0].SweptArea=(
        welds["WELD1"].Representation.Representations[0].Items[0].SweptArea)
    model.write(str(folder/"model.ifc"))
    result=audit(handoff,folder)
    assert result["artifact_status"]=="fail" and "CJP effective groove section" in result["finding_counts"]
    for bad in (dict(throat_mm=0),dict(width_mm=-1),dict(leg_mm=5),dict(weld_type="unknown")):
        invalid=copy.deepcopy(data)
        invalid["connections"][0]["parts"][-1].update(bad)
        with pytest.raises(ValueError):
            validate(invalid)


def test_flange_stays_keep_their_bracing_class_in_ifc(tmp_path):
    data=fixture()
    first=dict(data["members"][0], id="COLUMN-STAY",role="column flange brace",start=[-150,0,100],end=[0,300,300])
    second=dict(first,id="RAFTER-STAY",role="rafter flange brace",start=[0,300,300],end=[450,300,200])
    data["members"].extend([first,second])
    path=tmp_path/"braced.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    cert=deliver(path,tmp_path/"building")
    assert cert["artifact_status"]=="pass",cert["findings"]
    model=ifcopenshell.open(str(tmp_path/"building/model.ifc"))
    assert {"COLUMN-STAY","RAFTER-STAY"}<={r.Tag for r in model.by_type("IfcMember")}


def test_member_body_ends_bores_and_slots_are_cut_and_printed(tmp_path):
    data=fixture()
    member=next(r for r in data["members"] if r["id"]=="COL-2")
    member["end_cutbacks_mm"]=[35,50]
    member["member_voids"]=[
        dict(id="WEB-HOLE",kind="bore",start=[5990,0,250],end=[6010,0,250],diameter_mm=22),
        dict(id="WEB-SLOT",kind="slot",outline=[[5990,-9,3685],[5990,9,3685],[5990,9,3760],[5990,-9,3760]],thickness_mm=20)]
    source=tmp_path/"features.json"
    source.write_text(json.dumps(data),encoding="utf-8")
    delivered=deliver(source,tmp_path/"steel")
    assert delivered["artifact_status"]=="pass",delivered["findings"]
    assert delivered["readback"]["ifc"]["member_voids"]==2
    assert delivered["readback"]["ifc"]["cutback_members"]==1
    assert delivered["readback"]["pdf"]["sheet_types"]["machining"]==1
    member["member_voids"][0].update(start=[6090,0,250],end=[6110,0,250])
    source.write_text(json.dumps(data),encoding="utf-8")
    bad=deliver(source,tmp_path/"missed-web")
    assert bad["artifact_status"]=="fail"
    assert "specified cut removes actual parent steel" in bad["finding_counts"]


def test_metric_delivery_with_native_taper_and_opening(tmp_path):
    output=tmp_path/"delivery"
    result=deliver(FIXTURE,output)
    assert result["artifact_status"]=="pass",result["findings"]
    assert result["design_status"]=="review"
    m=ifcopenshell.open(str(output/"model.ifc"))
    log=ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(m,log,express_rules=True)
    assert log.statements==[]
    rs=m.by_type("IfcExtrudedAreaSolidTapered")
    assert len(rs)==1
    assert (rs[0].SweptArea.OverallDepth,rs[0].EndSweptArea.OverallDepth)==(450.,300.)
    assert len(m.by_type("IfcRelVoidsElement"))==2
    assert result["readback"]["ifc"]["bolt_plate_fit"]["clear_pairs"]==1
    assert len(m.by_type("IfcRelConnectsElements"))==3
    register=json.loads((output/"drawing_register.json").read_text(encoding="utf8"))
    assert register["design_status"]=="review"
    assert register["source_sha256"]==hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert len(register["sheets"])==len({s["number"] for s in register["sheets"]})
    with pytest.raises(ValueError,match="new or empty"):
        deliver(FIXTURE,output,candidate_only=True)


def test_invalid_handoffs_preserve_output(tmp_path):
    bad=fixture()
    bad["members"][0]["profile"]="unknown"
    f=tmp_path/"bad.json"
    f.write_text(json.dumps(bad),encoding="utf8")
    with pytest.raises(ValueError,match="unknown profile"):
        deliver(f,tmp_path/"delivery")
    assert not (tmp_path/"delivery").exists()
    bad=fixture()
    bad["members"][0]["ref_direction"]=[0,0,1]
    with pytest.raises(ValueError,match="parallel"):
        validate(bad)
    bad=fixture()
    bad["panels"][0]["openings"][0][0][1]=20
    with pytest.raises(ValueError,match="plane"):
        validate(bad)


def test_undrilled_anchor_fails_on_paper_and_in_reopened_ifc(tmp_path):
    data=fixture()
    data["connections"][0]["parts"][0].pop("openings")
    handoff=tmp_path/"undrilled.json"
    handoff.write_text(json.dumps(data),encoding="utf-8")
    folder=tmp_path/"drawing-set"
    cert=deliver(handoff,folder)
    assert cert["artifact_status"]=="pass" and cert["design_status"]=="fail"
    fit=cert["readback"]["ifc"]["bolt_plate_fit"]
    assert fit["interferences"][0]["plate"]=="P1" and fit["interferences"][0]["bolt"]=="A1"
    sheets=json.loads((folder/"drawing_register.json").read_bytes())["sheets"]
    assert any(s["kind"]=="bolt_fit" for s in sheets)


def test_fingerprint_verification(tmp_path):
    (tmp_path/"report.html").write_bytes(b"native report")
    data={"source_evidence":{"files":{"report.html":hashlib.sha256(b"native report").hexdigest()}}}
    assert verify_source_files(data,tmp_path)==data["source_evidence"]["files"]
    (tmp_path/"report.html").write_bytes(b"changed report")
    with pytest.raises(ValueError,match="mismatch"):
        verify_source_files(data,tmp_path)
    data["source_evidence"]["files"]={"../escape.txt":"0"*64}
    with pytest.raises(ValueError,match="relative"):
        verify_source_files(data,tmp_path)
    compressed=tmp_path/"handoff.json.gz"
    compressed.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    assert load(compressed)==load(FIXTURE)


def test_composite_placements_and_physical_clearance(tmp_path):
    data=fixture()
    data["units"]=[{"id":"A","name":"West","origin_mm":[-100,0,-100],"levels":["Ground","Eaves"]},
                   {"id":"B","name":"East","origin_mm":[500,0,200],"levels":["Ground","Eaves"]}]
    data["members"]=[dict(data["members"][0],unit="A",id="C1"),
                     dict(data["members"][0],unit="B",id="C2",start=[500,0,0],end=[500,0,3800])]
    plate={"kind":"plate","material":"E250","thickness_mm":20}
    data["connections"]=[]
    for unit,centre,col in (("A",0,"C1"),("B",500,"C2")):
        outline=[[centre-300,-100,-20],[centre+300,-100,-20],[centre+300,100,-20],[centre-300,100,-20]]
        data["connections"].append(dict(id="J"+unit,type="base",unit=unit,members=[col],at=[centre,0,0],
                                        parts=[dict(plate,id="P"+unit,outline=outline)]))
    data["panels"]=[]
    data["separation_joints"]=[dict(id="GAP",units=["A","B"],axis="x",declared_gap_mm=500,declared_basis="workline")]
    validate(data)
    clashes=plate_clashes(data)
    assert len(clashes)==1 and clashes[0]["overlap_volume_mm3"]==pytest.approx(100*200*20)
    gap=clearances(data,clashes)[0]
    assert gap["status"]=="fail" and gap["measured_gap_mm"]==pytest.approx(-100)
    path=tmp_path/"job.json"; path.write_text(json.dumps(data),encoding="utf8")
    output=tmp_path/"delivery"
    deliver(path,output,candidate_only=True)
    m=ifcopenshell.open(str(output/"model.ifc"))
    buildings={b.Name:b for b in m.by_type("IfcBuilding")}
    assert set(buildings)=={"A","B"}
    matrix=ifcopenshell.util.placement.get_local_placement
    for u in data["units"]:
        assert list(matrix(buildings[u["id"]].ObjectPlacement)[:3,3])==u["origin_mm"]
    for original in data["members"]:
        obj=next(c for c in m.by_type("IfcColumn") if c.Name==original["id"])
        assert list(matrix(obj.ObjectPlacement)[:3,3])==original["start"]
    register=json.loads((output/"drawing_register.json").read_text(encoding="utf8"))
    assert register["design_status"]=="fail"
    assert "plate_clashes" in {s["kind"] for s in register["sheets"]}
    joints=copy.deepcopy(data)
    joints["connections"][1]["parts"][0]["outline"]=[[x,y+250,z] for x,y,z in joints["connections"][1]["parts"][0]["outline"]]
    assert plate_clashes(joints)==[]
    assert clearances(joints)[0]["status"]=="review"


@pytest.mark.parametrize(("family","dims","width","depth"),[
    ("C",{"d":150,"b":60,"t":2,"lip":15,"r":3},60,150),
    ("C",{"d":150,"b":60,"t":2,"r":3},60,150),
    ("Z",{"d":150,"b":60,"t":2,"lip":15,"r":3},118,150),
    ("C",{"d":175,"b":75,"tw":7,"tf":11,"r":7,"slope_deg":5},75,175),
    ("RHS",{"d":220,"b":140,"tw":8,"tf":12},140,220),
])
def test_section_outside_dimensions(family,dims,width,depth):
    shape=section_polygons({"family":family,"dimensions_mm":dims})[0]
    x0,y0,x1,y1=shape.bounds
    assert (x1-x0,y1-y0)==pytest.approx((width,depth))
