"""Reproduce one HR design from its India repository brief and licensed local corpus."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

from briefs import cases


def dump(path,obj):
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def private_retrievals(cfg,corpus,unit_dir):
    """Write local supporting excerpts for the native package, outside the publication tree."""
    rag=unit_dir/'rag'
    rag.mkdir(parents=True,exist_ok=True)
    for i,hit in enumerate(cfg['load_plan']['retrieval'],1):
        if not hit.get('found'): continue
        src=corpus/'documents'/'standards'/hit['source_path']
        lines=src.read_text(encoding='utf-8-sig').splitlines()
        import re
        if src.suffix=='.csv':
            import csv
            with src.open(encoding='utf-8-sig',newline='') as stream: tab=list(csv.reader(stream))
            idx=hit['csv_rows']
            excerpt='\n'.join(' | '.join(tab[j-1]) for j in idx)
        else:
            match=next((j for j,v in enumerate(lines) if hit['query'].lower() in v.lower()),None)
            if match is None:
                phrase=hit.get('search_pattern')
                match=next((j for j,v in enumerate(lines) if phrase and re.search(phrase,v,re.I)),None)
            if match is None:
                match=next((j for j,v in enumerate(lines) if v.startswith('|') and v.count('|')>3),0)
            excerpt='\n'.join(lines[match:match+3])
        file=f'{i:02d}.json'
        record=dict(query=hit['query'],source=hit['source_path'],sha256=hit['sha256'],text=excerpt)
        dump(rag/file,record)
        hit['hit_file']=file
        hit['quote']=next(v.strip() for v in excerpt.splitlines() if v.strip())


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('numbers',type=int,nargs='+')
    ap.add_argument('--hr',type=Path,required=True)
    ap.add_argument('--corpus',type=Path,required=True)
    ap.add_argument('--jobs',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--cfs',type=Path,help='India CFS checkout. Defaults to cfs beside the HR checkout.')
    ap.add_argument('--specs',type=Path,help='Directory containing local licensed BIS PDFs.')
    ap.add_argument('--phase',choices=['all','native','audit','preflight'],default='all')
    args=ap.parse_args()
    args.hr=args.hr.resolve(); args.corpus=args.corpus.resolve(); args.jobs=args.jobs.resolve(); args.output=args.output.resolve()
    sys.path.insert(0,str(args.hr/'steel_engine'))
    args.cfs=(args.cfs or args.hr.parent/'cfs').resolve()
    args.specs=(args.specs or args.corpus.parent/'specs'/'INDIA_STEEL'/'pdfs').resolve()
    os.environ['STEEL_BUILDER_JOBS']=str(args.jobs)
    from design import make
    import pipeline
    import preflight
    unsuccessful=[]
    for number in args.numbers:
        case=cases()[number]; name=f'IN_Ex{number}'
        src=next((args.hr/'test_buildings').glob(name+'_*.txt'))
        jobdir=args.jobs/name; jobdir.mkdir(exist_ok=True,parents=True)
        dest=args.output/name;dest.mkdir(exist_ok=True,parents=True)
        print(f'{name} {args.phase}',flush=True)
        configs={}; failures={}
        for u in case.units:
            try: configs[u.name]=make(case,u,args.corpus)
            except Exception:
                failures[u.name]=traceback.format_exc()
        summary={'case':name,'brief_file':'test_buildings/'+src.name,'brief_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
                 'input_failures':failures}
        if failures:
            dump(jobdir/'input_failures.json',failures)
            print(failures,flush=True)
            unsuccessful.append(name)
            continue
        if args.phase in ('all','native') and (jobdir/'input_failures.json').is_file():
            (jobdir/'input_failures.json').unlink()
        if args.phase=='preflight':
            for unit,cfg in configs.items():
                findings=preflight.check(cfg)
                print(unit,[r for r in findings if r[0]=='ERROR'],flush=True)
            continue
        if args.phase in ('native','all'):
            for key,cfg in configs.items():
                path=jobdir if len(configs)==1 else jobdir/'units'/key
                private_retrievals(cfg,args.corpus,path)
            with (jobdir/'native.log').open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log):
                try:
                    if len(configs)>1:
                        names=list(configs)
                        gap=250 if number==12 else 400
                        joints=[dict(units=[a,b],direction='Y' if number==19 else 'X',gap_mm=gap)
                                for a,b in zip(names,names[1:])]
                        result=pipeline.design_units(name,configs,joints=joints)
                    else:
                        result=pipeline.design_and_report(name,configs['Main'])
                        if number==15:
                            from pune_ebf import verify_full_imposed
                            verify_full_imposed(name,configs['Main'],jobdir)
                    summary['native']={key:result[key] for key in ('blocked','error','model_valid','demands_written','design_status','design_status_error','preflight','status') if key in result}
                except Exception:
                    summary['native']={'blocked':True,'error':traceback.format_exc()}
                dump(jobdir/'native_result.json',summary)
            print(name,summary['native'].get('error') or str(summary['native'].get('design_status') or summary['native'].get('status') or 'returned')[:200],flush=True)
            if summary['native'].get('blocked') or summary['native'].get('error'):
                unsuccessful.append(name)
        if args.phase in ('all','audit'):
            from handoff import export
            portable={k:summary[k] for k in ('case','brief_file','brief_sha256','input_failures')}
            export(case,configs,args.hr,jobdir,dest,portable,args.cfs,args.specs)
    if unsuccessful:raise SystemExit('Native production error: '+', '.join(unsuccessful))


if __name__=='__main__':
    main()
