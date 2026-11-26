"""Publish the checked drawing/model revisions and their building index."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
FILES = ("drawings.pdf","model.ifc","drawing_register.json","certificate.json")


def hash_stream(stream):
    hasher=hashlib.sha256()
    for block in iter(lambda:stream.read(1024*1024),b""):
        hasher.update(block)
    return hasher.hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hash_stream(stream)


def record(path):
    return json.loads(path.read_bytes())


def archive(path, entries):
    path.parent.mkdir(parents=True,exist_ok=True)
    with NamedTemporaryFile(dir=path.parent,prefix=".issue-",suffix=".tmp",delete=False) as handle:
        temporary=Path(handle.name)
    try:
        with ZipFile(temporary,"w",compression=ZIP_DEFLATED,compresslevel=6) as z:
            for name,source in entries:
                info=ZipInfo(name,date_time=(2000,1,1,0,0,0))
                info.compress_type=ZIP_DEFLATED
                info.external_attr=0o100644 << 16
                info.file_size=source.stat().st_size
                with source.open("rb") as src,z.open(info,"w") as dst:
                    copyfileobj(src,dst,length=1024*1024)
        with ZipFile(temporary) as z:
            if bad:=z.testzip():
                raise ValueError(f"{path.name}: unreadable entry {bad}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def bundle_matches(path, checksums):
    if not path.is_file():
        return False
    try:
        with ZipFile(path) as z:
            if sorted(z.namelist())!=sorted(checksums):
                return False
            for name,digest in checksums.items():
                with z.open(name) as stream:
                    if hash_stream(stream)!=digest:
                        return False
    except (BadZipFile,OSError):
        return False
    return True


def package(args):
    build=args.build.resolve()
    manifest=record(build/"validation.json")
    dest=ROOT/"validation"
    expected={f"IN_{prefix}Ex{n}" for prefix,total in (("",21),("CFS_",15)) for n in range(1,total+1)}
    if expected!={r["id"] for r in manifest["cases"]} or len(manifest["cases"])!=len(expected):
        raise ValueError("Incomplete building inventory")
    comparison=record(dest/"comparison.json")
    cases=[]
    for row in manifest["cases"]:
        case=row["id"]
        family=row["module"].lower()
        base=dest/family/case
        handoff=next(base.glob("handoff.json*"))
        source_open=gzip.open if handoff.suffix==".gz" else open
        with source_open(handoff,"rb") as stream:
            fingerprint=hash_stream(stream)
        geometry=row.get("brief_geometry",{})
        if (fingerprint!=row.get("handoff_sha256") or row["artifact_status"]!="pass" or geometry.get("status")!="pass" or
            geometry.get("bearing_interfaces",{}).get("status")!="pass" or
            (family=="hr" and row["number"]<=5 and geometry.get("portal_contact_area",{}).get("status")!="pass") or
            (family=="hr" and row["number"] in (6,7,8,9,10,21) and geometry.get("eave_weld_faces",{}).get("status")!="pass")):
            raise ValueError(f"{case}: regenerate the changed or failing delivery")
        with source_open(handoff,"rt",encoding="utf-8-sig") as stream:
            source=json.load(stream)
        name=source["project"]["name"]
        assumptions=source.get("assumptions",[])
        project_decision=source["project"].get("design_status")
        open_checks=[{"id":r["id"],"status":r["status"],"description":r["description"],"utilization":r.get("utilization")}
                     for r in source.get("checks",[]) if r["status"]!="pass"]
        pending_details={}
        for joint in source.get("connections",[]):
            if joint.get("parts"):
                continue
            detail=pending_details.setdefault(joint["type"],{"occurrences":0,"example":joint["id"],
                                             "description":joint.get("description"),"example_parameters":joint.get("parameters",{})})
            detail["occurrences"]+=1
        del source
        details=build/row["delivery"]
        cert=record(details/"certificate.json")
        if sum(group["occurrences"] for group in pending_details.values())!=cert["located_joints_without_parts"]:
            raise ValueError(f"{case}: inconsistent count of connections awaiting detail")
        parts={part:details/part for part in FILES}
        checksums={part:file_sha(path) for part,path in parts.items()}
        if any(checksums[part]!=cert["sha256"][part] for part in FILES if part!="certificate.json"):
            raise ValueError(f"{case}: changed artifact bytes")
        comp=[r for r in comparison if r["id"]==case]
        if not comp or any(r["handoff_sha256"]!=fingerprint for r in comp):
            raise ValueError(f"{case}: stale design comparison")
        bundle=dest/"deliveries"/f"{case}.zip"
        if not bundle_matches(bundle,checksums):
            archive(bundle,parts.items())
            if not bundle_matches(bundle,checksums):
                raise ValueError(f"{case}: issued archive differs from its checked files")
        evidence=base/("evidence.json" if family=="hr" else "result.json")
        ev=record(evidence)
        if ev["handoff_sha256"]!=fingerprint:
            raise ValueError(f"{case}: stale design evidence")
        native={u["unit"]:u["fresh"]["native_status"] for u in comp}
        supplements=[p.relative_to(dest).as_posix() for p in sorted(base.glob("*")) if p.is_file() and
                     p!=evidence and not p.name.startswith("handoff.json")]
        cases.append(dict(id=case,module=row["module"],number=row["number"],name=name,supplements=supplements,
                          handoff=handoff.relative_to(dest).as_posix(),native_evidence=evidence.relative_to(dest).as_posix(),
                          native=native,declared_project_decision=project_decision,declared_assumptions=assumptions,
                          coordination=cert["design_status"],artifact=cert["artifact_status"],
                          sheets=row["sheets"],members=row["members"],parts=row["parts"],
                          geometry_controls=row["brief_geometry"],design_check_counts=cert["source_check_counts"],
                          located_joints_without_parts=cert["located_joints_without_parts"],connections_awaiting_detail=pending_details,
                          outstanding_checks=open_checks,
                          measured_joints=cert["readback"]["ifc"]["independently_measured_gaps"],
                          member_voids=cert["readback"]["ifc"]["member_voids"],cutback_members=cert["readback"]["ifc"]["cutback_members"],
                          bolt_plate_fit=cert["readback"]["ifc"]["bolt_plate_fit"],
                          pdf_readback=cert["readback"]["pdf"],sha256=cert["sha256"],archive=bundle.relative_to(dest).as_posix(),
                          archive_sha256=file_sha(bundle)))
    summary={"cases":cases,"totals":{"cases":len(cases),"sheets":sum(r["sheets"] for r in cases),
             "members":sum(r["members"] for r in cases),"connection_parts":sum(r["parts"] for r in cases),
             "native_units":dict(Counter(s for r in cases for s in r["native"].values())),
             "coordination_status":dict(Counter(r["coordination"] for r in cases)),
             "brief_geometry":dict(Counter(r["geometry_controls"]["status"] for r in cases))},
             "pipeline_sha256":manifest["pipeline_sha256"]}
    (dest/"acceptance.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# Indian steel building validation","",
           f"The 36 numbered briefs produced {summary['totals']['sheets']:,} drawing sheets and 36 IFC4 models. Each archive contains the issued PDF and IFC, the sheet register and its detached certificate. The individual evidence files give the independent inputs and calculations, corpus references and declared assumptions.","",
           "The native column records the engineering engine's decision for each structural unit. Coordination also considers open checks, connection geometry and separation joints. The brief column shows the independent dimensional and roof-footprint controls measured on the reopened IFC. The files remain available for design review wherever a gate is open.","",
           "[Numerical results and open items](acceptance.json) · [Worked-example revision checklist](revision-checklist.md) · [HR engineering review](hr/engineering-review.md) · [CFS engineering review](cfs/engineering-review.md) · [Independent CFS reruns](cfs/replay-results.json) · [Published report comparison](comparison.json) · [Drawing samples reviewed](visual-review.json) · [Specification manifest](corpus-verification.json) · [Installed workflow tests](workflow-verification.json) · [Pitched-roof analysis coupling tests](roof-link-verification.json)","",
           "| Building | Native decision | Coordination | Brief | Sheets | Members | Files |","| --- | --- | --- | --- | ---: | ---: | --- |"]
    for r in cases:
        states=", ".join((k+" " if len(r["native"])>1 else "")+str(v) for k,v in r["native"].items())
        more="".join(f" · [{Path(link).stem}]({link})" for link in r["supplements"])
        lines.append(f"| {r['id']} · {r['name']} | {states} | {r['coordination']} | {r['geometry_controls']['status']} | {r['sheets']} | {r['members']:,} | [PDF and IFC]({r['archive']}) · [Design evidence]({r['native_evidence']}){more} |")
    lines+=["","## Reproduce the native designs","",
            "Use the India HR and CFS repositories with their documented native solver environments. Install the India openBIM package in each design environment. Supply the local unpacked corpus and licensed PDF directory. A private output directory contains the full native calculations, source report, retrieval excerpts and the bound handoff. The published case evidence contains calculated values, input decisions, clause locators and fingerprints.","",
            "Run from the root of the openBIM checkout. Substitute the indicated directories for your local paths. HR uses the CFS design module for its cold-formed secondary checks. HR 5 uses the fresh HR 1 frame as its existing building. Keep the saved section and connection sizing decisions in the validation directory when reproducing the frozen design.","",
            "```shell","python validation/hr/run_case.py 1 5 --phase all --hr INDIA_HR --cfs INDIA_CFS --corpus CORPUS --specs BIS_PDFS --jobs PRIVATE_HR --output NEW_HR_EVIDENCE",
            "python validation/cfs/run_native.py 3 --engine INDIA_CFS --corpus CORPUS --jobs PRIVATE_CFS",
            "python validation/cfs/export_case.py 3 --engine INDIA_CFS --jobs PRIVATE_CFS --target NEW_CFS_EVIDENCE",
            "steltic-openbim-india deliver-job PRIVATE_CFS/IN_CFS_Ex3 --output NEW_CFS_DELIVERY","```","",
            "The HR example numbers run from 1 through 21, and CFS from 1 through 15. The design programs read the active project statements. The comparison utility is a separate, post-freeze operation that reads the published solution reports. The corpus identity and PDF edition checks can be repeated with:","",
            "```shell","python tools/check_local_corpus.py --archive CORPUS_ZIP --corpus CORPUS --pdf-dir BIS_PDFS --output corpus-verification.json","```",""]
    (dest/"README.md").write_text("\n".join(lines),encoding="utf-8")
    if args.output:
        names=[r[key] for r in cases for key in ("archive","native_evidence","handoff")]
        names.extend(s for r in cases for s in r["supplements"])
        names.extend(n for n in ("README.md","acceptance.json","revision-checklist.md","comparison.json","corpus-verification.json",
                                 "visual-review.json","workflow-verification.json","roof-link-verification.json",
                                 "cfs/engineering-review.md","cfs/replay-results.json","hr/engineering-review.md",
                                 "hr/verify_eave_edges.py","hr/verify_peb_bearings.py"))
        archive(args.output,((n,dest/n) for n in names))
    print(json.dumps(summary["totals"]))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build",required=True,type=Path)
    parser.add_argument("--output",type=Path,help="Optional combined downloadable archive")
    package(parser.parse_args())
