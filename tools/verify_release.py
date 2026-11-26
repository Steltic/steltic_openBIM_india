"""Verify the downloadable India building files against their evidence and native handoffs."""
import gzip
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from package_examples import FILES, ROOT, file_sha, hash_stream, record


def verify(directory):
    accepted=record(directory/"acceptance.json")
    references=record(directory/"comparison.json")
    reviews={r["id"]:r for r in record(directory/"visual-review.json")}
    cfs_replays={r["case"]:r for r in record(directory/"cfs/replay-results.json")["cases"]}
    expected={f"IN_{prefix}Ex{n}" for prefix,count in (("",21),("CFS_",15)) for n in range(1,count+1)}
    if {r["id"] for r in accepted["cases"]}!=expected or len(accepted["cases"])!=36 or reviews.keys()!=expected:
        raise ValueError("Incomplete issued building or visual review inventory")
    if len(references)!=40 or len({(r["id"],r["unit"]) for r in references})!=40:
        raise ValueError("Incomplete or repeated independent unit comparison")
    if set(cfs_replays)!={f"IN_CFS_Ex{n}" for n in range(1,16)}:
        raise ValueError("Incomplete independent CFS design replay inventory")
    if record(directory/"roof-link-verification.json")["status"]!="pass" or record(directory/"workflow-verification.json")["status"]!="pass":
        raise ValueError("Incomplete native roof or installed workflow tests")
    sheets=0
    native=Counter()
    for case in accepted["cases"]:
        key=case["id"]
        bundle=directory/case["archive"]
        if file_sha(bundle)!=case["archive_sha256"]:
            raise ValueError(f"{key}: archive SHA-256 mismatch")
        evidence=record(directory/case["native_evidence"])
        handoff=directory/case["handoff"]
        with (gzip.open if handoff.suffix==".gz" else open)(handoff,"rb") as stream:
            source=hash_stream(stream)
        comparison=[r for r in references if r["id"]==key]
        if case["module"]=="CFS":
            repeated=cfs_replays[key]
            if not repeated["passed"] or repeated["issued_handoff_sha256"]!=source or repeated["native_source_files_rehashed"]<1:
                raise ValueError(f"{key}: independent native replay no longer identifies the issued job")
        if (source!=case["sha256"]["handoff.json"] or source!=evidence["handoff_sha256"] or
            set(case["native"])!={r["unit"] for r in comparison} or any(source!=r["handoff_sha256"] for r in comparison)):
            raise ValueError(f"{key}: stale handoff, unit comparison or native evidence")
        geometry=case["geometry_controls"]
        if geometry["bearing_interfaces"]["status"]!="pass" or not geometry["bearing_interfaces"]["samples"]:
            raise ValueError(f"{key}: incomplete bearing verification")
        if case["module"]=="HR" and case["number"]<=5 and geometry["portal_contact_area"]["status"]!="pass":
            raise ValueError(f"{key}: incomplete portal contact areas")
        if case["module"]=="HR" and case["number"] in (6,7,8,9,10,21):
            eaves=geometry["eave_weld_faces"]
            if eaves["status"]!="pass" or eaves["ifc_sha256"]!=case["sha256"]["model.ifc"] or eaves["handoff_sha256"]!=source:
                raise ValueError(f"{key}: incomplete eave weld and sheet-edge verification")
        if any(not (directory/p).is_file() for p in case["supplements"]):
            raise ValueError(f"{key}: missing supplement")
        with ZipFile(bundle) as archive:
            if sorted(archive.namelist())!=sorted(FILES):
                raise ValueError(f"{key}: incomplete or duplicate archive entries")
            cert=json.loads(archive.read("certificate.json"))
            reg=json.loads(archive.read("drawing_register.json"))
            if (cert["sha256"]!=case["sha256"] or cert["artifact_status"]!=case["artifact"] or case["artifact"]!="pass" or
                reg["source_sha256"]!=source or case["geometry_controls"]["status"]!="pass"):
                raise ValueError(f"{key}: inconsistent acceptance certificate")
            for name in FILES:
                if name=="certificate.json":
                    continue
                with archive.open(name) as file:
                    if hash_stream(file)!=cert["sha256"][name]:
                        raise ValueError(f"{key}: changed file {name}")
            sheet_index={r["number"]:(r["page"],r["kind"]) for r in reg["sheets"]}
            review=reviews[key]
            if (len(sheet_index)!=case["sheets"] or cert["readback"]["pdf"]["rasterized_pages"]!=len(sheet_index) or
                review["pdf_sha256"]!=cert["sha256"]["drawings.pdf"] or
                {s["kind"] for s in review["poppler_samples"]}!={"plan","elevation","details"} or
                any(sheet_index.get(s["sheet"])!=(s["page"],s["kind"]) for s in review["poppler_samples"])):
                raise ValueError(f"{key}: stale drawing register or visual review")
        sheets+=len(sheet_index)
        native.update(case["native"].values())
    if sheets!=accepted["totals"]["sheets"] or dict(native)!=accepted["totals"]["native_units"]:
        raise ValueError("Incorrect published totals")
    return {"buildings":len(expected),"design_units":sum(native.values()),"sheets":sheets}


if __name__=="__main__":
    print(json.dumps(verify(ROOT/"validation")))
