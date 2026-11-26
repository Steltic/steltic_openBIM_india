"""Generate and independently audit the numbered India HR/CFS acceptance cases."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from brief_controls import run as check_brief


ROOT = Path(__file__).resolve().parents[1]
CASES = {"hr":21, "cfs":15}


def case_id(family, number):
    return f"IN_{'CFS_' if family=='cfs' else ''}Ex{number}"


def pipeline_fingerprint():
    digest = hashlib.sha256()
    for p in sorted((ROOT/"src/steltic_openbim_india").glob("*.py")):
        digest.update(p.name.encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


def run_case(family, number, output, pipeline, resume):
    from steltic_openbim_india.delivery import deliver
    from steltic_openbim_india.audit import digest
    import ifcopenshell
    import pymupdf
    import reportlab
    sid = case_id(family, number)
    base = ROOT/"validation"/family/sid
    candidate = next((p for p in (base/"handoff.json.gz",base/"handoff.json") if p.is_file()), None)
    row = {"id":sid, "module":family.upper(), "number":number, "artifact_status":"fail", "design_status":"unknown"}
    if candidate is None:
        return {**row,"reason":"No frozen design handoff"}
    raw = gzip.decompress(candidate.read_bytes()) if candidate.suffix==".gz" else candidate.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    directory = output/family/sid
    directory.mkdir(parents=True,exist_ok=True)
    version_key = f"{pipeline}/{ifcopenshell.version}/{pymupdf.VersionBind}/{reportlab.Version}"
    key = hashlib.sha256(f"{version_key}/{sha}".encode()).hexdigest()[:20]
    delivery = directory/key
    row.update(handoff_sha256=sha, delivery=delivery.relative_to(output).as_posix())
    try:
        if resume and (delivery/"certificate.json").is_file():
            cert = json.loads((delivery/"certificate.json").read_bytes())
            if cert["sha256"].get("handoff.json") != sha or any(
                digest(delivery/name)!=value for name,value in cert["sha256"].items() if name!="handoff.json"
            ):
                raise ValueError("A prior revision has changed on disk")
        else:
            with TemporaryDirectory(dir=directory) as tmp:
                handoff = Path(tmp)/"handoff.json"
                handoff.write_bytes(raw)
                cert = deliver(handoff,delivery)
        row.update(artifact_status=cert["artifact_status"],design_status=cert["design_status"],
                   sheets=cert["readback"].get("pdf",{}).get("sheets",0),
                   members=cert["readback"].get("ifc",{}).get("members",0),
                   parts=cert["readback"].get("ifc",{}).get("parts",0),
                   checks=cert["source_check_counts"],finding_counts=cert["finding_counts"])
        row["brief_geometry"] = check_brief(family,number,cert["readback"].get("ifc",{}).get("building_geometry",{}))
        if cert["findings"]:
            row["first_finding"]=cert["findings"][0]
    except Exception as error:
        row["reason"]=f"{type(error).__name__}: {error}"
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True,help="Private or release build directory")
    parser.add_argument("--case",action="append",help="E.g. hr:1 or cfs:15. Default is the full inventory.")
    parser.add_argument("--workers",type=int,default=1,help="Separate processes, default one")
    parser.add_argument("--require-design-pass",action="store_true",help="Also return nonzero on engineering review/fail")
    args=parser.parse_args()
    tasks=[(family,n) for family,total in CASES.items() for n in range(1,total+1)]
    if args.case:
        selected=set()
        for selection in args.case:
            match=re.fullmatch(r"(hr|cfs):([1-9]\d*)",selection.lower())
            if not match or int(match[2])>CASES[match[1]]:
                parser.error(f"Unknown case {selection}")
            selected.add((match[1],int(match[2])))
        tasks=[task for task in tasks if task in selected]
    if args.workers<1:
        parser.error("--workers must be at least 1")
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    rows=[]
    pipeline=pipeline_fingerprint()
    def report(row):
        rows.append(row)
        print(f"{row['id']}: artifacts {row['artifact_status']}, design {row['design_status']}; "
              f"{row.get('sheets',0)} sheets, {row.get('members',0)} members. "
              f"{row.get('reason', row.get('first_finding',''))}",flush=True)
    if args.workers==1:
        for family,n in tasks:
            report(run_case(family,n,output,pipeline,True))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            tasks_by_future={pool.submit(run_case,f,n,output,pipeline,True):(f,n) for f,n in tasks}
            for future in as_completed(tasks_by_future):
                f,n=tasks_by_future[future]
                try:
                    report(future.result())
                except Exception as error:
                    report(dict(id=case_id(f,n),module=f.upper(),number=n,artifact_status="fail",design_status="unknown",reason=str(error)))
    rows.sort(key=lambda r:(r["module"]!="HR",r["number"]))
    summary={"expected_cases":len(tasks),"pipeline_sha256":pipeline,"cases":rows}
    # A single-case diagnostic never overwrites the full sweep's manifest.
    selection = ",".join(r["id"] for r in rows)
    suffix = rows[0]["id"] if len(rows)==1 else hashlib.sha256(selection.encode()).hexdigest()[:12]
    name="validation.json" if len(tasks)==sum(CASES.values()) else f"validation-{suffix}.json"
    (output/name).write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    return int(any(r["artifact_status"]!="pass" or r.get("brief_geometry",{}).get("status")!="pass" or
                   (args.require_design_pass and r["design_status"]!="pass") for r in rows))


if __name__=="__main__":
    raise SystemExit(main())
