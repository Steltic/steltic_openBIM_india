"""Compare a newly recalculated job with its issued engineering and physical evidence."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


def load(path):
    opener=gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",encoding="utf-8") as stream:return json.load(stream)


def same(first,other):
    if isinstance(first,dict) and isinstance(other,dict):
        return first.keys()==other.keys() and all(same(v,other[k]) for k,v in first.items())
    if isinstance(first,list) and isinstance(other,list):
        return len(first)==len(other) and all(same(a,b) for a,b in zip(first,other))
    if isinstance(first,(int,float)) and isinstance(other,(int,float)) and not any(isinstance(x,bool) for x in (first,other)):
        return math.isclose(first,other,rel_tol=1e-8,abs_tol=1e-5)
    return type(first)==type(other) and first==other


def digest(path,compressed=False):
    reader=gzip.open if compressed else open
    h=hashlib.sha256()
    with reader(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def verify(baseline,replay,job):
    current=load(replay/"result.json");original=load(baseline/"result.json")
    source=load(replay/"handoff.json.gz");previous=load(baseline/"handoff.json.gz")
    physical=("schema_version","project","levels","grids","materials","profiles","members","panels","connections","checks","assumptions")
    engineering=("case","source_brief_sha256","dimensions","design_status","native_warnings","reasons","site","occupancy_basis","gravity",
                 "dead_load_build_up_kNm2","native_member_groups","cfs_check_groups","native_lateral","installed_bearings")
    fields={k:same(source.get(k),previous.get(k)) for k in physical}
    evidence={k:same(current.get(k),original.get(k)) for k in engineering}
    samples=same(load(replay/"bearing-samples.json"),load(baseline/"bearing-samples.json"))
    source_files=source["source_evidence"]["files"]
    digests={name:digest(job/name)==expected for name,expected in source_files.items()}
    actual=digest(replay/"handoff.json.gz",compressed=True)
    sidecar=digest(job/"design/openbim_handoff.json")
    matched=(actual==sidecar==current["handoff_sha256"])
    clean=current["design_status"]=="complete" and current["reasons"]==[] and all(c["status"]!="fail" for c in source["checks"])
    return dict(case=current["case"],passed=clean and samples and matched and all((*fields.values(),*evidence.values(),*digests.values())),
                source_status_complete=clean,semantic_geometry=fields,native_and_design_evidence=evidence,
                bearing_samples=samples,native_files=digests,replay_sidecar_matches_portable=matched,
                issued_handoff_sha256=original["handoff_sha256"],replay_handoff_sha256=actual)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("case",type=int,choices=range(1,16))
    parser.add_argument("--reference",type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument("--replay",type=Path,required=True,help="Output root passed to export_case.py")
    parser.add_argument("--jobs",type=Path,required=True,help="Private reanalysis jobs root");args=parser.parse_args()
    case=f"IN_CFS_Ex{args.case}";receipt=verify(args.reference/case,args.replay/case,args.jobs/case)
    print(json.dumps(receipt,indent=2,ensure_ascii=False))
    raise SystemExit(0 if receipt["passed"] else 1)
