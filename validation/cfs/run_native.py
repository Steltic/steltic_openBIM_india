"""Run one native design without consulting a worked fixture. Writes private hits locally."""
import argparse
import os
import sys
import traceback
from pathlib import Path

from buildings import all_buildings
from design import make_config
from grounding import dump


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case",type=int,choices=range(1,16))
    parser.add_argument("--engine",type=Path,required=True,help="steltic_CFS_india checkout")
    parser.add_argument("--corpus",type=Path,required=True,help="unpacked local corpus_fixed")
    parser.add_argument("--jobs",type=Path,required=True,help="private job scratch (outside this repo)")
    args=parser.parse_args()
    engine=args.engine.resolve()
    job=args.jobs.resolve()/f"IN_CFS_Ex{args.case}"
    job.mkdir(parents=True,exist_ok=True)
    os.environ.update(PYTHONUTF8="1",PYTHONIOENCODING="utf-8",MPLBACKEND="Agg",OPENBLAS_NUM_THREADS="1",
                      OMP_NUM_THREADS="1",MKL_NUM_THREADS="1",MPLCONFIGDIR=str(args.jobs.resolve()/"mpl"))
    sys.path.insert(0,str(engine/"steel_engine"))
    from india_cfs_pipeline import design_and_report
    from preflight import check
    b=all_buildings()[args.case-1]
    cfg=make_config(b,args.corpus.resolve(),job)
    brief=next((engine/"test_buildings").glob(f"IN_CFS_Ex{b.number}_*.txt"))
    cfg["brief"]=brief.read_text(encoding="utf-8").splitlines()[0]
    dump(job/"independent-input.json",cfg)
    print("PREFLIGHT:",check(cfg),flush=True)
    result=design_and_report(cfg["name"],cfg,str(job))
    dump(job/"result.json",result)


if __name__=="__main__":
    main()
