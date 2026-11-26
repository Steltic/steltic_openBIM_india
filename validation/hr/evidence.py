"""Portable summaries of verified local calculations. No licensed excerpts are published."""
from functools import lru_cache
from hashlib import sha256
import json
import re
from pathlib import Path


EDITIONS={
    'IS_800_2007':'IS 800:2007',
    'IS_808_2021':'IS 808:2021',
    'IS_2062_Part_1_2025':'IS 2062 (Part 1):2025',
    'IS_18168_2023':'IS 18168:2023',
    'IS_1893_Part_1_2016':'IS 1893 (Part 1):2016 + Amendments 1 (2017) and 2 (2020)',
    'IS_875_Part_1_2026':'IS 875 (Part 1):2026',
    'IS_875_Part_2_1987':'IS 875 (Part 2):1987',
    'IS_875_Part_3_2015':'IS 875 (Part 3):2015',
    'IS_875_Part_4_1987':'IS 875 (Part 4):2021, third revision (source filename retains 1987)',
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}


@lru_cache(maxsize=None)
def pdf_reference(specs,stem):
    if not specs:return None
    matches=sorted(Path(specs).glob(stem+'*.pdf'))
    if len(matches)!=1:return None
    path=matches[0]
    return {'file':path.name,'sha256':sha256(path.read_bytes()).hexdigest()}


def source_table(actual,specs):
    rows=[]
    for hit in actual.get('retrieval',[]):
        stem=hit.get('stem')
        rec={k:hit[k] for k in ('found','cite','source_path','sha256','csv_rows','selected_inputs') if k in hit}
        rec['edition']=EDITIONS.get(stem,stem)
        pdf=pdf_reference(specs,stem)
        if pdf:rec['licensed_pdf']=pdf
        rows.append(rec)
    return rows


def short_checks(package):
    status=package.get('design_status',{})
    result={'status':status.get('status','unavailable'),'native_findings':status.get('n_reasons'),
            'finding_classes':status.get('reason_classes',{}),'model_gates':package.get('gates',{}),
            'combination_count':len(package.get('load_combinations') or {})}
    for key in ('members','connections'):
        rows=package.get(key,[])
        numerical=[r for r in rows if isinstance(r.get('DC'),(float,int))]
        governing=max(numerical,key=lambda r:r['DC'],default={})
        inputs=governing.get('inputs',{})
        result[key]={'groups':len(rows),'groups_with_numeric_dc':len(numerical),'groups_above_unity':sum(r['DC']>1 for r in numerical),
            'governing_group':governing.get('id'),'governing_dc':governing.get('DC'),
            'section':governing.get('section') or inputs.get('section'),'limit_state':governing.get('governing_check') or governing.get('limit_state'),
            'governing_element':inputs.get('governing_element'),'governing_combination':inputs.get('governing_combo')}
    drift=max((r for r in (package.get('drift_table') or []) if isinstance(r.get('dc'),(float,int))),
              key=lambda r:r['dc'],default={})
    result['governing_drift']={k:drift[k] for k in ('storey','dir','value','limit','dc','ok') if k in drift}
    return result


def unit_evidence(cfg,job,unit,case,specs):
    actual=read(job/'load_plan.json')
    package=read(job/'design'/'calc_package.json')
    snapshot=read(job/'design'/'cfg_snapshot.json') or cfg
    wind=actual.get('wind_summary') or {}
    seismic=actual.get('seismic_summary') or {}
    analysis=package.get('seismic_analysis') or {}
    loads={k:snapshot.get(k) for k in ['D_roof','Lr','D_roof_collateral','D_roof_pv','D_floor','L_floor',
           'clad','partitions','partition_load_kNm2','self_weight','snow'] if k in snapshot}
    out={'unit':unit.name,'site':case.city,'geometry':{'bays_x':unit.nx,'bays_y':unit.ny,
        'span_x_m':unit.sx,'span_y_m':unit.sy,'storey_heights_m':list(unit.heights),'footprint':unit.shape},
        'loads_kN_per_m2':loads,'member_grade':snapshot.get('steel_grade'),
        'lateral_system':{'X':snapshot.get('system_x'),'Y':snapshot.get('system_y')},
        'seismic':{k:seismic[k] for k in ('zone','Z','I','soil','R_x','R_y','W_kN','Ta_x_s','Ta_y_s',
                    'Sa_g_x','Sa_g_y','Ah_x','Ah_y','VB_x_kN','VB_y_kN','W_by_floor_kN') if k in seismic},
        'wind':{k:wind[k] for k in ('Vb_mps','terrain_category','k1','k2','k3','k4','Kd','Ka','Ka_area_m2',
                      'Kc','pz_kNm2','pd_kNm2') if k in wind},
        'analysis':{'method':analysis.get('method'),'rsa_used_in_demands':analysis.get('rsa_used_in_demands'),
                    'scale_by_axis':analysis.get('scale')},
        'grounding':source_table(actual,specs),'native_checks':short_checks(package)}
    status_file=job/'STATUS.engine.md'
    if status_file.is_file():
        matched=re.search(r'(?im)^# .*?design status:\s*(\w+)\s*$',status_file.read_text(encoding='utf-8-sig'))
        if matched:
            final=matched.group(1).lower()
            if out['native_checks']['status']!=final:
                out['native_checks']['pre_report_package_status']=out['native_checks']['status']
            out['native_checks']['status']=final
            out['native_checks']['post_report_status_sha256']=sha256(status_file.read_bytes()).hexdigest()
    if case.number in (3,7):
        crane=snapshot.get('crane') or {}
        out['crane_inputs']={k:crane.get(k) for k in ('capacity_kN','crab_kN','bridge_kN','rail_height_mm',
             'gantry_section','gantry_grade','gantry_LLT_mm','bracket_eccentricity_mm') if k in crane}
        gantry=package.get('gantry_girder') or {}
        out['gantry_check']={k:gantry.get(k) for k in ('section','DC') if k in gantry}
    if wind.get('gust_factor'):
        gust=wind['gust_factor']
        out['wind']['dynamic']={'G_X':gust['X']['G'],'G_Y':gust['Y']['G'],'fa_x_hz':gust['X']['fa_hz'],
          'fa_y_hz':gust['Y']['fa_hz'],'gust_base_shear_X_kN':gust['VB_x_kN'],'gust_base_shear_Y_kN':gust['VB_y_kN'],
          'Cfs_X':wind['across_wind']['X']['Cfs']['value'],'Cfs_Y':wind['across_wind']['Y']['Cfs']['value'],
          'assumption':wind['across_wind_basis']}
    return out
