"""IS 875-3 clauses 10.2–10.4, using this design's modal frequencies and licensed figure readings."""
import csv
import math

import india_wind_tables as W


def add(case,unit,ground,plan,wind,coeff):
    if case.number not in (16,17,18,20):return
    from final_members import decisions
    trial=decisions().get(str(case.number),{}).get(unit.name,{})
    freq=trial.get('frequency_hz')
    if not freq:return
    h=sum(unit.heights); b={'X':unit.ny*unit.sy,'Y':unit.nx*unit.sx}
    beta=.02; gust={};across={}
    for axis,normal in [('X','Y'),('Y','X')]:
        along=W.along_wind_story_forces(unit.heights,b[axis],coeff[axis]['Cp_net'],freq[axis.lower()],
                     case.terrain,wind['Vb_mps'],case.k1,case.k3,case.k4,beta)
        g=along['gust'];gust[axis]=dict(g,fa_hz=freq[axis.lower()])
        gust['VB_'+axis.lower()+'_kN']=along['VB_N']/1000
        for k,f in enumerate(along['F_N'],1):
            components=plan['story_forces']['W_'+axis][str(k)]
            ix=0 if axis=='X' else 1
            components[ix]=max(components[ix],f)
        reduced=g['Vh_d']/(freq[normal.lower()]*b[axis])
        sample=[]; source=[]
        for figure in (10,11):
            stem='IS_875_Part_3_2015'
            path=next((ground.root/stem/'tables').glob(f'*_Fig_{figure}_recovered.csv'))
            with path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.reader(f))
            numeric=[]
            for line,row in enumerate(rows[1:],2):
                try:x=float(row[0])
                except (ValueError,IndexError):continue
                values=[]
                for cell in row[1:]:
                    try:values.append(float(cell))
                    except ValueError:continue
                if values:numeric.append((line,x,max(values)))
            abscissa=[x for line,x,v in numeric]
            # The lowest available X bounds lower reduced velocities. Structural and
            # terrain ratios between the published curves are enveloped at each X.
            lo=max((x for x in abscissa if x<=reduced),default=min(abscissa))
            hi=min((x for x in abscissa if x>=reduced),default=max(abscissa))
            points=[(i,v) for i,x,v in numeric if x in (lo,hi)]
            ordinate=max(v for _,v in points)
            sample.append(ordinate);source.append(path.name)
            ground.hit(stem,path,f'IS 875 Part 3, Figure {figure}, wind along {axis}, reduced velocity',
                       selected=[i for i,_ in points],inputs={'reduced_velocity':round(reduced,5),'tabulated_bracket':[lo,hi],
                       'bound_Cfs':ordinate,'adoption':'Upper curve ordinates, both tabulated turbulence bands and shapes'})
        # Include the digitisation uncertainty identified in the local figure manifest.
        cfs=1.10*max(sample)
        across[axis]={'Cfs':{'value':cfs,'source':' / '.join(source),'cite':'IS 875 Part 3:2015 Figures 10 and 11'},
            'beta':beta,'fc_hz':freq[normal.lower()],'k':1,'b_m':b[axis],'h_m':h}
    wind['gust_factor']=dict(gust,G=max(gust['X']['G'],gust['Y']['G']),beta=beta,frequency_basis=trial['source_package_sha256'])
    wind['across_wind']=across
    wind['across_wind_basis']='Trial rectangular-plan coefficient envelope including 10% figure-reading allowance. Verify application to actual shape and confirm final normal-mode frequencies.'
