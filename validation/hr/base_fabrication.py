"""Place native gusseted foundations and the two equal-strength welded blanks."""
import math
import inspect
from native_joint_parts import location,plate
from steltic_openbim_india.geometry import cross


def detail(model,row,col,spec,corner,wide,deep,holes):
    up=(0.,0.,1.)
    B,L,t=(spec[k] for k in ('B_mm','L_mm','t_plate_mm'))
    p=model.data['profiles'][col['profile']]['dimensions_mm']
    g=spec.get('stiffeners') or {}
    if g and g.get('layout')=='cross':
        width=g['t_mm'];height=g['h_mm']
        for face,direction in enumerate((wide,[-i for i in wide],deep,[-i for i in deep]),1):
            front=p['b'] if face<=2 else p['d']; cover=p['d'] if face<=2 else p['b']
            length=((B if face<=2 else L)-front)/2.
            n=int(g.get('n_per_side_y',g['n_per_side']) if face<=2 else g['n_per_side'])
            tang=cross(direction,up)
            stations=[(i/(n-1)-.5)*(cover-width) for i in range(n)] if n>1 else [0.]
            for i,station in enumerate(stations,1):
                at=location(row['at'],(direction,front/2),(tang,station-width/2))
                row['parts'].append(dict(id=row['id']+f'-GS{face}-{i}',kind='plate',material='E250B0',thickness_mm=width,
                    outline=[at,location(at,(direction,length)),location(at,(up,height))]))
        row['parameters'].update(base_gusset_thickness_mm=width,base_gusset_height_mm=height,
                                  base_gussets_per_face=g['n_per_side'],base_gusset_weld='Shop CJP to shaft and base')
    fab=spec.get('fabrication') or {}
    if not fab:return
    a=spec['anchors'];seams=fab['seams_from_edge_mm']
    pieces=[];gap=10. # effective narrow-gap weld zone after machining
    for i,(lo,hi) in enumerate(zip([0.,*seams],[*seams,B]),1):
        x=lo+(gap/2 if lo else 0);end=hi-(gap/2 if hi<B else 0)
        drill=[(x0-x,y,r) for x0,y,r in holes if x<x0<end]
        pieces.append(plate(row['id']+f'-BP-S{i}',location(corner,(wide,x)),wide,deep,end-x,L,t,'E250B0',drill))
    model.materials.setdefault('CJP-E250B0',dict(grade='Full-penetration butt weld metal matching E250 B0',
                                               standard='IS 800:2007 10.5.7.1.2, 10.5.10.2.2; qualified shop WPS/PQR'))
    for i,x in enumerate(seams,1):
        pieces.append(plate(row['id']+f'-CJP-{i}',location(corner,(wide,x-gap/2)),wide,deep,gap,L,t,'CJP-E250B0'))
    row['parts']=[v for v in row['parts'] if v['id']!=row['id']+'-BP']+pieces
    # Conserve the native footprint and every through bore after splitting.
    if sum(len(v.get('openings',[])) for v in pieces)!=len(holes):
        raise ValueError(row['id']+': incomplete drill-through on edge-laid strips')
    package=next(r for r in model.native['connections'] if r.get('section')==col['profile'] and
                 any('column base' in v.get('name','') for v in r.get('checks',[])))
    def maxima(suffix):
        rows=[v for v in package['checks'] if 'column base' in v['name'] and v['name'].split(': ')[-1].split(':')[-1]==suffix]
        major=max((abs(v['value']) for v in rows if ': y:' not in v['name']),default=0.)
        minor=max((abs(v['value']) for v in rows if ': y:' in v['name']),default=0.)
        return major+minor
    M=maxima('plate_thickness')
    q=maxima('gusset_weld_to_plate_10_5_7')*g['t_mm']
    global_V=abs(package['demand']['base_demands']['V_N'])
    sigma=6*M/t**2
    # Keep the complete base shear within the 850 mm shaft width at the
    # point of application. No credit for spreading over the full plate.
    load_width=min(p['b'],p['d'])
    tau=1.5*(q+global_V/load_width)/t
    stress=math.sqrt(sigma**2+3*tau**2)
    limit=210./1.25
    import india_connections as calc
    import sections
    from secondary_weight import areas
    mass=0.
    for v in row['parts']:
        if v['kind']=='plate':
            volume=(areas(v['outline'])-sum(areas(h) for h in v.get('openings',[])))*v['thickness_mm']
        elif v['kind']=='bolt':volume=math.pi*v['diameter_mm']**2/4*math.dist(v['start'],v['end'])
        else:continue
        mass+=volume*7.85e-6
    # Foundation hardware is below the superstructure and is absent from
    # storey inertial mass. Add it locally to compression; retain the original
    # frame-only case separately, including uplift, without stability credit.
    extra_N=mass*9.81
    prop=sections.props(col['profile'])
    args={k:v for k,v in spec.items() if k in inspect.signature(calc.base_plate_design).parameters}
    args.update(col_d_mm=prop['d'],col_bf_mm=prop['bf'],col_tf_mm=prop['tf'])
    tag=col['source_element']['tag']
    authority=next(a for a in model.native['capacity_design']['section12']['checks'] if a['id']=='12.12_base' and a['member']==f'base-e{tag}')
    cases=authority['per_case'];count=0;peak_base=0.;worst_load=None;strength=stress
    cache=getattr(model,'_seam_load_cache',{})
    model._seam_load_cache=cache
    for state in cases:
        for add in (0.,1.5*extra_N):
            loads={k:state[k] for k in ('P_N','Mz_Nmm','My_Nmm','V_N')}
            loads['P_N']+=add
            cachekey=(col['profile'],tuple(round(v,2) for v in loads.values()))
            if cachekey not in cache:
                out=calc.base_plate_design_biaxial(**args,**loads)
                res=out['checks']
                def two(key):return sum(abs(res.get(x,{}).get('value') or 0.) for x in (key,'y:'+key))
                m=two('plate_thickness');line=two('gusset_weld_to_plate_10_5_7')*g['t_mm']
                bend=6*m/t**2; shear=1.5*(line+abs(loads['V_N'])/load_width)/t
                cache[cachekey]=(math.sqrt(bend**2+3*shear**2),max((r.get('dc') or 0.) for r in res.values()),
                    m,line,bend,shear,{k:res['shear_path'].get(k) for k in ('friction_N','anchors_N','shear_key_N')})
            current,base_ratio,m,line,bend,shear,path=cache[cachekey];count+=1
            peak_base=max(peak_base,base_ratio)
            if worst_load is None or current>strength:
                strength=current;sigma=bend;tau=shear;M=m;q=line;global_V=loads['V_N']
                worst_load=dict(combo=state['combo'],axial_plus_local_dead_N=loads['P_N'],local_dead_factor=1.5 if add else 0.,
                    friction_kN=round((path['friction_N'] or 0.)/1000,3),anchor_shear_kN=round((path['anchors_N'] or 0.)/1000,3))
    stress=strength
    key=row['id']+'-BASE-CJP'
    if not any(i['id']==key for i in model.data['checks']):
        model.data['checks'].extend([
            dict(id=key,status='pass' if stress<=limit else 'fail',utilization=stress/limit,
                 description=f'Full-depth base butt seam, elastic combined stress {stress:.2f} MPa against {limit:g} MPa. Includes both plate strip moments, both gusset line shears and the full base shear within the {load_width:g} mm column footprint.',
                 reference='IS 800:2007 7.4.2, 10.5.7.1.2, 10.5.10.2.2; native governing base occurrence.'),
            dict(id=key+'-QUAL',status='review',description=f'Shop qualification required for the {t:g} mm deep, double-sided butt welds before installation. Require matching toughness, through-thickness testing, controlled heat input, sequence, distortion/flatness machining and complete UT. Foundation engineer to confirm 4.5 m anchor development, group breakout and pedestal reinforcement.',
                 reference='IS 800 Section 10; IS 2062 Part 1:2025; IS 456 26.2.1.1; project fabrication and foundation design.')])
        model.data['checks'].append(dict(id=key+'-LOCAL-DL',status='pass' if peak_base<=1. else 'fail',utilization=peak_base,
                description=f'Local steel-base/anchor check includes {mass:.1f} kg at foundation level. Enveloped all {len(cases)} native concurrent states, retaining uplift and a separate 1.5-times hardware dead-load upper bound on compression.',
                reference='IS 800 7.4, 10.3 and 12.12; IS 18168 9.3. Separate from concrete breakout and pedestal design.'))
    row.setdefault('checks',[]).extend([key,key+'-QUAL',key+'-LOCAL-DL'])
    row['parameters'].update(strip_count=len(seams)+1,full_penetration_seams=len(seams),seam_weld_depth_mm=t,
        effective_weld_zone_mm=gap,seam_moment_per_width_nmm_mm=round(M,2),seam_line_shear_n_mm=round(q,2),
        concurrent_base_shear_n=round(global_V,1),shear_introduction_width_mm=load_width,seam_bending_stress_mpa=round(sigma,3),seam_shear_stress_mpa=round(tau,3),
        seam_combined_stress_mpa=round(stress,3),seam_design_limit_mpa=limit,plain_anchor_development_mm=a['embedment']['L_mm'],
        checked_base_load_states=count,source_base_id=authority['member'],total_local_foundation_steel_kg=round(mass,1),
        nominal_added_pedestal_dead_kN=round(extra_N/1000,2),controlling_weld_case=worst_load,
        source_capacity_shear_MN=round(global_V/1e6,5),applied_shear_key_kN=0.)
    row['description']=spec['procurement_basis']+(' Native SFRS base shear envelopes the factored frame shear, 1.2 times column shear capacity per IS 800 12.12.2, '
            'and IS 18168 9.3 fixed-base capacity actions. The model takes friction at 0.45 of bearing-block compression and the remaining resultant through the anchor group. '
            'The foundation designer must establish a concrete/group transfer path, grout shear and local reinforcement or provide a separately designed shear key. '
            'The indicated fusion zones need qualified shop procedures and full UT.')
