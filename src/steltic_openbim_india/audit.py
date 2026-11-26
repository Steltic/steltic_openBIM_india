"""Detached certificate for a saved design handoff, PDF, sheet register and IFC4."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from .audit_ifc import audit_ifc
from .audit_pdf import audit_pdf


def digest(path):
    with path.open("rb") as stream:
        h = hashlib.sha256()
        for block in iter(lambda:stream.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(handoff, delivery):
    handoff, folder = Path(handoff), Path(delivery)
    raw = gzip.decompress(handoff.read_bytes()) if handoff.suffix.lower()==".gz" else handoff.read_bytes()
    source = json.loads(raw)
    hashes = {"handoff.json": hashlib.sha256(raw).hexdigest()}
    counts, findings = Counter(), []
    def expect(passed, check, subject):
        if not passed:
            counts[check] += 1
            if len(findings)<100:
                findings.append({"check":check, "subject":str(subject)})
    paths = {name:folder/name for name in ("model.ifc","drawings.pdf","drawing_register.json")}
    for name,p in paths.items():
        expect(p.is_file(),"artifact exists",name)
        if p.is_file():
            hashes[name] = digest(p)
    details = {}
    def examine(label, check):
        try:
            details[label] = check()
        except Exception as error:
            expect(False, label + " read-back", f"{type(error).__name__}: {error}")
    if paths["model.ifc"].is_file():
        examine("ifc", lambda: audit_ifc(source,paths["model.ifc"],hashes["handoff.json"],expect))
    if paths["drawing_register.json"].is_file() and paths["drawings.pdf"].is_file():
        def pdf():
            register = json.loads(paths["drawing_register.json"].read_text(encoding="utf-8"))
            for field,name in [("source_sha256","handoff.json"),("drawings_pdf_sha256","drawings.pdf"),("model_ifc_sha256","model.ifc")]:
                expect(register.get(field)==hashes.get(name),"revision binding",name)
            details["declared_design_status"]=register.get("design_status")
            details["separation_joints"]=register.get("separation_joints",[])
            details["interunit_plate_clashes"]=register.get("interunit_plate_clashes",[])
            return audit_pdf(source,paths["drawings.pdf"],register,expect)
        examine("pdf",pdf)
    checks = Counter(r.get("status","review") for r in source.get("checks", []))
    unresolved_joints = sum(not c.get("parts") for c in source.get("connections",[]))
    ifc=details.get("ifc",{})
    gap_states={x.get("status","review") for x in ifc.get("separation_joints",[])}
    states=set(checks) | gap_states | {source["project"].get("design_status","pass")}
    design = "fail" if "fail" in states or ifc.get("interunit_horizontal_plate_overlaps") else "review" if (
        not checks or "review" in states or not source.get("connections") or unresolved_joints) else "pass"
    if "pdf" in details and ifc:
        expect(details["declared_design_status"]==ifc.get("declared_design_status")==design, "drawing/IFC engineering status",source["project"]["id"])
        expect(details.get("separation_joints")==ifc.get("separation_joints"),"drawing/IFC separation schedule",source["project"]["id"])
        expect(details.get("interunit_plate_clashes")==ifc.get("declared_plate_clashes"),"drawing/IFC clash schedule",source["project"]["id"])
    return {"certificate_version":"1.0", "project":source["project"]["id"], "artifact_status":"fail" if counts else "pass",
            "design_status":design, "source_check_counts":dict(checks), "located_joints_without_parts":unresolved_joints,
            "scope":"Source-to-output agreement. Design status summarizes supplied checks and outstanding connection geometry. "
                    "Acceptance against the building brief is recorded separately in the case validation.",
            "sha256":hashes, "readback":details, "finding_counts":dict(counts), "findings":findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff",type=Path)
    parser.add_argument("delivery",type=Path)
    args = parser.parse_args()
    report = audit(args.handoff,args.delivery)
    (args.delivery/"certificate.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(f"{report['project']}: artifacts {report['artifact_status']}, design {report['design_status']}")
    return int(report["artifact_status"] != "pass")


if __name__=="__main__":
    raise SystemExit(main())
