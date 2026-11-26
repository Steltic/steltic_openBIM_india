"""Size failed groups after explicit secondary tributaries and physical dead loads."""
import argparse
import json
from pathlib import Path
from functools import lru_cache


FILE=Path(__file__).with_name('transfer_sections.json')


@lru_cache(maxsize=1)
def _read():
    return json.loads(FILE.read_bytes()) if FILE.is_file() else {}


def decisions(number,unit):
    return _read().get(str(number),{}).get(unit,{})


if __name__=='__main__':
    import sys
    import csv
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jobs',type=Path);parser.add_argument('numbers',nargs='+',type=int)
    parser.add_argument('--hr',required=True,type=Path)
    args=parser.parse_args()
    sys.path.insert(0,str(args.hr.resolve()/'steel_engine'))
    from briefs import cases
    from final_members import select
    result=_read()
    for number in args.numbers:
        case=cases()[number]
        for u in case.units:
            path=args.jobs/f'IN_Ex{number}'
            if len(case.units)>1:path=path/'units'/u.name
            cp=json.loads((path/'design'/'calc_package.json').read_bytes())
            failed={(r['inputs']['role'],r['inputs']['section']) for r in cp['members'] if (r.get('DC') or 0.)>1.}
            with (path/'design'/'member_schedule.csv').open(encoding='utf-8-sig',newline='') as stream:
                schedule={str(r['ele_tag']):(r['role'],r['section']) for r in csv.DictReader(stream)}
            for key,rec in cp['capacity_design']['checks'].items():
                label,_,tag=key.partition('@e')
                if label.startswith('is18168_table2_') and rec.get('ok') is False and tag in schedule:
                    failed.add(schedule[tag])
            if not failed:continue
            options=select(case,u,path,rolled_gravity=True)
            prior=result.setdefault(str(number),{}).setdefault(u.name,{'sections':{}})
            fabricated=None
            for role,old in sorted(failed):
                take=options['sections'].get(role,{}).get(old)
                if not take and role=='gravity_col':
                    if fabricated is None:fabricated=select(case,u,path)
                    take=fabricated['sections'].get(role,{}).get(old)
                if not take:print(number,role,old,'no trial candidate',flush=True);continue
                sub=prior['sections'].setdefault(role,{})
                for name,sel in list(sub.items()):
                    if sel==old:sub[name]=take
                sub[old]=take
                prior['source_package_sha256']=options['source_package_sha256']
                print(number,role,old,take,flush=True)
    FILE.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
