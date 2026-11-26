"""Publish the checked drawing/model revisions and their building index."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
FILES = ("drawings.pdf","model.ifc","drawing_register.json","certificate.json")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path):
    return json.loads(path.read_bytes())


def archive(path, entries):
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(path,"w") as z:
        for name,raw in entries:
            info=ZipInfo(name, date_time=(2000,1,1,0,0,0))
            info.compress_type=ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            z.writestr(info,raw,compress_type=ZIP_DEFLATED,compresslevel=6)
    with ZipFile(path) as z:
        if bad:=z.testzip():
            raise ValueError(f"{path.name}: unreadable entry {bad}")


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
        raw=handoff.read_bytes()
        raw=gzip.decompress(raw) if handoff.suffix==".gz" else raw
        if sha(raw)!=row.get("handoff_sha256") or row["artifact_status"]!="pass":
            raise ValueError(f"{case}: regenerate the changed or failing delivery")
        source=json.loads(raw)
        details=build/row["delivery"]
        cert=record(details/"certificate.json")
        parts={name:(details/name).read_bytes() for name in FILES}
        if any(sha(parts[name])!=cert["sha256"][name] for name in FILES if name!="certificate.json"):
            raise ValueError(f"{case}: changed artifact bytes")
        comp=[r for r in comparison if r["id"]==case]
        if not comp or any(r["handoff_sha256"]!=sha(raw) for r in comp):
            raise ValueError(f"{case}: stale design comparison")
        bundle=dest/"deliveries"/f"{case}.zip"
        archive(bundle,parts.items())
        with ZipFile(bundle) as z:
            if any(sha(z.read(k))!=sha(v) for k,v in parts.items()):
                raise ValueError(f"{case}: failed archive readback")
        evidence=base/("evidence.json" if family=="hr" else "result.json")
        ev=record(evidence)
        if ev["handoff_sha256"]!=sha(raw):
            raise ValueError(f"{case}: stale design evidence")
        native={u["unit"]:u["fresh"]["native_status"] for u in comp}
        open_checks=[{"id":r["id"],"status":r["status"],"description":r["description"],"utilization":r.get("utilization")}
                     for r in source.get("checks",[]) if r["status"]!="pass"]
        cases.append(dict(id=case,module=row["module"],number=row["number"],name=source["project"]["name"],
                          handoff=handoff.relative_to(dest).as_posix(),native_evidence=evidence.relative_to(dest).as_posix(),
                          native=native,coordination=cert["design_status"],artifact=cert["artifact_status"],
                          sheets=row["sheets"],members=row["members"],parts=row["parts"],
                          geometry_controls=row["brief_geometry"],design_check_counts=cert["source_check_counts"],
                          located_joints_without_parts=cert["located_joints_without_parts"],outstanding_checks=open_checks,
                          measured_joints=cert["readback"]["ifc"]["independently_measured_gaps"],
                          pdf_readback=cert["readback"]["pdf"],sha256=cert["sha256"],archive=bundle.relative_to(dest).as_posix(),
                          archive_sha256=sha(bundle.read_bytes())))
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
           "[Numerical results and open items](acceptance.json) · [Worked-example revision checklist](revision-checklist.md) · [Comparison with all published unit reports](comparison.json) · [Specification manifest](corpus-verification.json)","",
           "| Building | Native decision | Coordination | Brief | Sheets | Members | Files |","| --- | --- | --- | --- | ---: | ---: | --- |"]
    for r in cases:
        states=", ".join((k+" " if len(r["native"])>1 else "")+str(v) for k,v in r["native"].items())
        lines.append(f"| {r['id']} · {r['name']} | {states} | {r['coordination']} | {r['geometry_controls']['status']} | {r['sheets']} | {r['members']:,} | [PDF and IFC]({r['archive']}) · [Design evidence]({r['native_evidence']}) |")
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
        archive(args.output, [(r[key],(dest/r[key]).read_bytes()) for r in cases for key in ("archive","native_evidence","handoff")]+
                [(name,(dest/name).read_bytes()) for name in ("README.md","acceptance.json","revision-checklist.md","comparison.json","corpus-verification.json")])
    print(json.dumps(summary["totals"]))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build",required=True,type=Path)
    parser.add_argument("--output",type=Path,help="Optional combined downloadable archive")
    package(parser.parse_args())
