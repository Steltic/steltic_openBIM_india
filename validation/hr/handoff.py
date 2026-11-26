"""Emit physical steelwork tied to native analysis tags and the engine's decision."""
import csv
import hashlib
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path

import engine3d as E
import openseespy.opensees as ops
import sections as S
from openbim_handoff import export_handoff

from briefs import floor_cells
from secondary import select_z


def prof(sec):
    p=S.props(sec); s=p['section_type']
    if s=='double_angle' or p.get('component'):
        a=S.props(p['component']); w=a['bf']; h=a['d']; t=a['tw']; gap=p['gap_mm']
        right=[[gap/2,-h/2],[gap/2+w,-h/2],[gap/2+w,-h/2+t],[gap/2+t,-h/2+t],[gap/2+t,h/2],[gap/2,h/2]]
        return {'family':'POLYGON','contours_mm':[right,[[-x,y] for x,y in reversed(right)]]}
    fam={'I':'I','box':'RHS','angle':'L','channel':'C','CHS':'CHS'}[s]
    d=dict(d=p['d'],b=p['bf'],tw=p['tw'],tf=p['tf'])
    if fam=='CHS':d.update(t=p['tw'],diameter=p['d'])
    if fam=='I' and p.get('flange_slope_deg'):
        d['slope_deg']=p['flange_slope_deg']-90
    if p.get('R1') and fam in ('I','C'):d['r']=p['R1']
    return {'family':fam,'dimensions_mm':d}


def _levels(unit):
    result=[0.]
    for h in unit.heights:result.append(result[-1]+h*1000)
    return result


def check(rows,key,desc,status='review',dc=None,reference='Steltic India upstream analysis'):
    row=dict(id=key,description=desc,status=status,reference=reference)
    if isinstance(dc,(float,int)) and math.isfinite(dc) and dc>=0:row['utilization']=dc
    rows.append(row)
    return key


def native_checks(unit,folder,data):
    cp=folder/'design'/'calc_package.json'
    if not cp.is_file():
        check(data['checks'],unit+'-UNAVAILABLE','The native engineering package is unavailable for this structural unit.')
        return {},{},{}
    p=json.loads(cp.read_text(encoding='utf-8-sig')); groups={}; evidence={}
    for family,field in [('members','M'),('connections','J')]:
        for i,item in enumerate(p[family],1):
            desc=item.get('governing_check') or item.get('limit_state') or item['id']
            dc=item.get('DC')
            failed=any(c.get('ok') is False for c in item.get('checks',[]))
            open_=any(c.get('ok') is None for c in item.get('checks',[]))
            st='fail' if failed or isinstance(dc,(int,float)) and dc>1 else 'review' if open_ or dc is None else 'pass'
            k=check(data['checks'],f'{unit}-{field}{i}',item['id']+' / '+str(desc),st,dc,'IS 800:2007 and native calculation package')
            if family=='members':
                input_=item.get('inputs',{});groups[(input_.get('role'),input_.get('section'))]=k
            else:
                evidence.setdefault(item.get('section'),[]).append(k)
    for k,ok in (p.get('gates') or {}).items():
        if isinstance(ok,bool): check(data['checks'],f'{unit}-G-{k}',f'{unit} / {k}','pass' if ok else 'fail',reference='Native model and serviceability gate')
    labels={};materials={}
    session_grades={(m['inputs'].get('role'),m['inputs'].get('section')):m['inputs'].get('grade')
                     for m in p['members'] if m.get('inputs')}
    sch=folder/'design'/'member_schedule.csv'
    if sch.is_file():
        with sch.open(encoding='utf-8-sig',newline='') as fh:
            for r in csv.DictReader(fh):
                tag=int(r['ele_tag']);key=(r['role'],r['section'])
                labels[tag]=groups.get(key)
                if session_grades.get(key):materials[tag]=session_grades[key]
    p['_element_materials']=materials
    return labels,evidence,p


class UnitModel:
    def __init__(self,data,case,u,cfg,hr,cfs,folder,offset):
        self.data,self.case,self.u,self.cfg=data,case,u,cfg
        self.hr,self.cfs,self.folder=hr,cfs,folder
        self.offset=list(offset)
        self.pre=u.name+'-';self.local=defaultdict(list); self.profile_lookup=data['profiles']
        self.materials=data['materials'];self.roles={}
        self.checks,self.conn_checks,self.native=native_checks(u.name,folder,data)
        self.datums=_levels(u);self.n=0

    def xyz(self,point):
        return [round(a+d,4) for a,d in zip(point,self.offset)]

    def level(self,z):
        level=max(h for h in self.datums if h<=z+.1)
        return f'EL-{level:g}'

    def member(self,role,sec,a,b,*,material=None,checks=(),ref=None,refs=None,end_profile=None,mid=None,bind=True):
        self.n+=1;tag=self.pre+(mid or f'P{self.n}')
        if sec not in self.profile_lookup:self.profile_lookup[sec]=prof(sec)
        if end_profile and end_profile not in self.profile_lookup:self.profile_lookup[end_profile]=prof(end_profile)
        if refs and material is None:
            grades={self.native.get('_element_materials',{}).get(t) for t,lab in refs}-{None}
            if len(grades)>1:raise ValueError(f'Multiple native steel grades on {tag}: {grades}')
            if grades:
                raw=next(iter(grades)).upper().replace(' ','')
                material={'E250':'E250','E250B':'E250B0','YST310':'YST310'}.get(raw,raw)
                if material not in self.materials:
                    self.materials[material]=dict(grade=material,standard='IS 1161:2014' if material.startswith('YST') else 'IS 2062 Part 1:2025')
        if material is None:material='YST310' if sec.startswith('CHS') else ('E250B0' if role in ('brace','gable post','roof brace') else self.cfg['steel_grade'])
        row=dict(id=tag,role=role,profile=sec,material=material,start=self.xyz(a),end=self.xyz(b),
                 level=self.level(min(a[2],b[2])),unit=self.u.name)
        if end_profile and end_profile!=sec: row['end_profile']=end_profile
        if ref:row['ref_direction']=ref
        if checks:row['checks']=list(dict.fromkeys(x for x in checks if x))
        if refs:
            rows=[dict(unit=self.u.name,tag=t,source_profile=lab,offset_mm=list(self.offset)) for t,lab in refs]
            row['source_element' if len(rows)==1 else 'source_elements']=rows[0] if len(rows)==1 else rows
        self.data['members'].append(row)
        self.roles[tag]=(role,sec)
        if bind:
            for pt in (a,b): self.local[tuple(round(v,3) for v in pt)].append(tag)
        return row

    def primary(self):
        info=E.build(self.cfg,'Linear')
        rows={r[0]:r for r in info['ele']}
        pb=info.get('peb') or {};pe=pb.get('elements') or {}
        used=set()
        def pos(nd):return list(ops.nodeCoord(nd))
        for mem in (pb.get('members') or {}).values():
            tags=[t for t in mem['elements'] if t in rows]
            if not tags: continue
            seg=[pe[t] for t in tags]
            # A removed gable segment was replaced by two supported pieces and is exported separately.
            if len(tags)!=len(mem['elements']):continue
            a,b=pos(seg[0]['n1']),pos(seg[-1]['n2'])
            st,end=seg[0]['sec_i'],seg[-1]['sec_j']
            role=mem['kind']
            ref=None
            if role=='column':
                ref=[0,1,0] if mem.get('strong_dir','X')=='X' else [1,0,0]
            self.member(role,st,a,b,mid=mem['id'],refs=[(t,rows[t][2]) for t in tags],end_profile=end,
                        checks=[self.checks.get(t) for t in tags],ref=ref)
            used.update(tags)
        link_tags={r['tag'] for r in info.get('links',[])}
        for t,kind,sec,n1,n2 in rows.values():
            if t in used:continue
            a,b=pos(n1),pos(n2)
            role=(info.get('physical_roles') or {}).get(t) or ('shear link' if t in link_tags else
                  'column' if kind=='col' else 'brace' if kind in ('brace','truss') else
                  'rafter' if self.case.rise and abs(a[2]-b[2])>1 else 'beam')
            ref=None
            if kind=='col':ref=[0,1,0] if info.get('col_dir',{}).get(t,'X')=='X' else [1,0,0]
            self.member(role,sec,a,b,mid='E'+str(t),refs=[(t,sec)],checks=[self.checks.get(t)],ref=ref)

    def panel(self,role,points,thick,material,mid,openings=None):
        row=dict(id=self.pre+mid,unit=self.u.name,role=role,material=material,outline=[self.xyz(p) for p in points],
                 level=self.level(min(p[2] for p in points)),thickness_mm=thick)
        if openings:row['openings']=[[self.xyz(p) for p in loop] for loop in openings]
        self.data['panels'].append(row)

    def roof_z(self,x):
        w=self.u.nx*self.u.sx*1000
        return self.datums[-1]+self.case.rise*1000*(1-abs(2*x/w-1))

    def roof_y(self,y):
        length=self.u.ny*self.u.sy*1000
        return self.datums[-1]+(min(y,length-y)/60 if self.case.number==10 else 0)

    def secondaries(self):
        case,u=self.case,self.u; n=case.number
        chosen=self.cfg.get('physical_secondaries',{})
        self.secondary_checks={}
        for row in self.native.get('secondary_members',[]):
            dc=row.get('DC')
            status='review' if dc is None else 'pass' if dc<=1 else 'fail'
            self.secondary_checks[row['id']]=check(self.data['checks'],self.pre+'S-'+row['id'].replace(' ','-'),
                    row['id']+' / '+row['section'],status,dc,'Native IS 800 secondary member and Table 6 service check')
        sx=u.sx*1000; sy=u.sy*1000; w=u.nx*sx; length=u.ny*sy; h=self.datums[-1]
        if case.rise:
            purlin_z=n in (1,2,3,4,5,21)
            ps=self.cfg.get('purlin_spacing_mm',case.purlin_spacing*1000)
            gs=self.cfg.get('girt_spacing_mm',case.girt_spacing*1000)
            if purlin_z:
                # Ex5 is a check on the already selected Ex1 purlin and girt. Recheck the same members for the extra PV weight.
                q=self.cfg['D_roof']+self.cfg['Lr']+self.cfg['D_roof_collateral']+(0 if n==5 else self.cfg['D_roof_pv'])
                mw=self.cfg['load_plan'].get('member_wind',[])
                pd=self.cfg['load_plan']['wind_summary']['pd_kNm2']
                uplift=max((abs(min(r['roof_windward_kNm2'],r['roof_leeward_kNm2'])) for r in mw),default=1.6*pd)
                zname,dims,dc=select_z(self.cfs,sy,ps,q,uplift)
                if n==5:
                    zname,dims,dc=select_z(self.cfs,sy,case.purlin_spacing*1000,q+.15,uplift,fixed=zname)
                gname,gdims,gdc=select_z(self.cfs,sy,gs,1.35*pd,1.35*pd)
                for lab,dim in ((zname,dims),(gname,gdims)):self.profile_lookup[lab]=dict(family='Z',dimensions_mm=dim)
                pmat='IS801-FY240'
                pk=check(self.data['checks'],self.pre+'Z-ROOF','CFS India IS 801 service-load purlin assessment' + (' with PV on the Ex1 frozen section' if n==5 else ''),'pass' if dc<=1 else 'fail',dc,'IS 801 clauses 5.2 and 6.3–6.5')
                gk=check(self.data['checks'],self.pre+'Z-WALL','CFS India IS 801 service-load girt selection','pass' if gdc<=1 else 'fail',gdc,'IS 801 clauses 5.2 and 6.3–6.5')
            else:
                zname=chosen['roof purlin'];gname=chosen['side girt'];pmat='E250B0'
                pk=self.secondary_checks.get('roof purlin');gk=self.secondary_checks.get('side girt')
            count=2*math.ceil(w/(2*ps))
            for p in range(count+1):
                x=w*p/count; z=self.roof_z(x)
                if p in (0,count//2,count):continue  # eave/ridge line already has a structural longitudinal member
                for j in range(u.ny):
                    self.member('purlin',zname,(x,j*sy,z),(x,(j+1)*sy,z),material=pmat,checks=[pk],mid=f'PU-{p}-{j+1}',bind=False)
            low=3000 if n in (1,2,4,5,21) else 0
            count_g=math.ceil((h-low)/gs)
            for i in (0,u.nx):
                from enclosure import doors,allowed_segments
                holes=doors(case,u,'Y',int(i==u.nx))
                for k in range(0 if n in (1,2,4,5) and low else 1,count_g):
                    z=low+(h-low)*k/count_g
                    for j in range(u.ny):
                        for seq,(a,b) in enumerate(allowed_segments(j*sy,(j+1)*sy,z,holes)):
                            self.member('girt',gname,(i*sx,a,z),(i*sx,b,z),material=pmat,
                                        ref=[0,0,1],checks=[gk],mid=f'GI-{i}-{j+1}-{k}-{seq}',bind=False)
            if n not in (8,21):
                for j in sorted({0,u.ny-1}|({u.ny//2} if n in (2,9) else set())):
                    for a,b in [(0,w/2),(w/2,w)]:
                        for i1,i2 in [(a,b),(b,a)]:
                            self.member('roof brace','CHS139.7X5.4',(i1,j*sy,self.roof_z(i1)),(i2,(j+1)*sy,self.roof_z(i2)),
                                        mid=f'RB-{j}-{i1:g}-{i2:g}',bind=False)
            for i,(a,b) in enumerate([(0,w/2),(w/2,w)]):
                self.panel('roof sheeting',[(a,0,self.roof_z(a)),(b,0,self.roof_z(b)),(b,length,self.roof_z(b)),(a,length,self.roof_z(a))],
                           .5,'SHEET',f'SLOPE-{i+1}')
            if n==7:
                from crane_runway import draw
                draw(self)
            if n==3:
                cr=self.cfg['crane'];rail=cr['rail_height_mm'];ecc=cr['bracket_eccentricity_mm']
                girder=cr['gantry_section'];bracket=cr['bracket']['section']
                beam_z=rail-75-S.props(girder)['d']/2
                seat_z=rail-75-S.props(girder)['d']-S.props(bracket)['d']/2
                col_face=S.props(cr['bracket']['column_section'])['d']/2
                for side,x in enumerate((ecc,w-ecc)):
                    for j in range(1,u.ny-1):
                        self.member('gantry girder',girder,(x,j*sy,beam_z),(x,(j+1)*sy,beam_z),material='E250B0',
                                    mid=f'GAN-{side}-{j}',bind=False)
                    for j in range(1,u.ny):
                        self.member('crane bracket',bracket,(col_face if side==0 else w-col_face,j*sy,seat_z),(x,j*sy,seat_z),material='E250B0',
                                    mid=f'BRK-{side}-{j}',bind=False)
            if n==2:
                import peb_build as PB
                canopy_axis=self.cfg['canopy_axis_height_mm']
                face=PB.section_at(self.cfg['gold']['peb_column'],canopy_axis/h)
                support=w+S.props(face)['d']/2
                cap_z=canopy_axis+350
                self.panel('dock canopy',[(support,0,cap_z),(support+6000,0,cap_z-200),(support+6000,length,cap_z-200),(support,length,cap_z)],.5,'SHEET','CANOPY')
                roof=self.cfg['load_plan']['member_wind']; can_down=max(p['canopy_pressure_kNm2'] for p in roof)
                can_up=max(-p['canopy_pressure_kNm2'] for p in roof)
                cn,dim,cdc=select_z(self.cfs,sy,750,max(.2+.75,can_down+.2),can_up)
                self.profile_lookup[cn]=dict(family='Z',dimensions_mm=dim)
                ck=check(self.data['checks'],self.pre+'Z-CANOPY','IS 801 canopy purlin at 750 mm, with independent positive and negative canopy pressure.',
                    'pass' if cdc<=1 else 'fail',cdc,'IS 801 5.2, 6.3–6.5; attached-canopy pressure assumption')
                for k in range(9):
                    for j in range(u.ny):
                        self.member('canopy purlin',cn,(support+750*k,j*sy,cap_z-25*k),(support+750*k,(j+1)*sy,cap_z-25*k),
                                    material=pmat,checks=[ck],mid=f'CAN-PU-{k}-{j}',bind=False)
            if n==9:
                self.panel('lean-to roof',[(-12000,0,5000),(0,0,5000),(0,4*sy,5000),(-12000,4*sy,5000)],100,'CONC','LEAN-ROOF')
                check(self.data['checks'],self.pre+'LEAN','Flat lean-to roof drainage, overflow path and ponding depth require site drainage design. Snow drift is included in the native load plan.')
        else:
            for k,z in enumerate(self.datums[1:],1):
                for i,j in sorted(floor_cells(u,k)):
                    roof_cell=k==len(u.heights) or (i,j) in {tuple(cell) for cell in self.cfg['gold'].get('roof_regions',{}).get(k,[])}
                    zl=self.roof_y(j*sy) if n==10 else z
                    zu=self.roof_y((j+1)*sy) if n==10 else z
                    self.panel('roof deck' if roof_cell else 'floor deck',[(i*sx,j*sy,zl),((i+1)*sx,j*sy,zl),((i+1)*sx,(j+1)*sy,zu),(i*sx,(j+1)*sy,zu)],
                               .75 if n==10 or u.name=='Gym' or n==6 and k==len(u.heights) else 100,
                               'SHEET' if n==10 or u.name=='Gym' or n==6 and k==len(u.heights) else 'CONC', f'DECK-{k}-{i}-{j}')
                    spacing=case.purlin_spacing if n==6 and k==len(u.heights) else 2.5 if n in (10,11) else 3
                    count=max(2,math.ceil(u.sy/spacing))
                    service='roof joist' if roof_cell else 'floor joist'
                    sec=chosen.get(service) or self.cfg['gold']['beam_sec']['roof_X' if roof_cell else 'floor_X']
                    for b in range(1,count):
                        y=(j+b/count)*sy
                        elev=self.roof_y(y) if n==10 else z
                        self.member('roof joist' if n==10 else 'secondary beam',sec,(i*sx,y,elev),((i+1)*sx,y,elev),
                                    checks=[self.secondary_checks.get(service)],mid=f'SEC-{k}-{i}-{j}-{b}',bind=False)

    def joints(self):
        for i,(pt,ids) in enumerate(self.local.items(),1):
            if len(ids)<2 and abs(pt[2])>1e-3:continue
            roles=[self.roles[mid][0] for mid in ids]; sec=self.roles[ids[0]][1]
            typ='base plate' if abs(pt[2])<1e-3 else 'brace connection' if any('brace' in r for r in roles) else 'beam-column connection' if 'column' in roles else 'member splice'
            row=dict(id=self.pre+'J'+str(i),unit=self.u.name,type=typ,at=self.xyz(pt),members=ids,level=self.level(pt[2]))
            keys=list(dict.fromkeys(k for mid in ids for k in self.conn_checks.get(self.roles[mid][1],[])))
            if keys:row['checks']=keys
            if typ=='base plate':
                detail=self.cfg['connections']['column_base'].get(sec)
                if detail:
                    b,l,t=(detail[k] for k in ('B_mm','L_mm','t_plate_mm'))
                    at=self.xyz(pt)
                    def point(dx,dy,dz):return [at[0]+dx,at[1]+dy,at[2]+dz]
                    row['parts']=[dict(id=row['id']+'-BP',kind='plate',material='E250B0',thickness_mm=t,
                                       outline=[point(-b/2,-l/2,-t),point(b/2,-l/2,-t),point(b/2,l/2,-t),point(-b/2,l/2,-t)])]
                    anchors=detail['anchors']; row['parameters']={'plate_width_mm':b,'plate_length_mm':l,'plate_thickness_mm':t,
                        'anchor_count':anchors['n_total'],'anchor_diameter_mm':anchors['d_mm'],'concrete_strength_mpa':30}
                    row['description']='Trial base plate. Anchor embedment, concrete breakout and foundation require foundation design.'
            if 'description' not in row:row['description']='Refer to the native joint check. Fit-up and connection hardware require detailing.'
            self.data['connections'].append(row)


def export(case,configs,hr,jobdir,dest,summary,cfs=None,specs=None):
    name=summary['case']
    src=hr/summary['brief_file']
    title=src.read_text(encoding='utf-8-sig').splitlines()[0].split('—',1)[-1].strip()
    data={'schema_version':'1.0','project':dict(id=name,name=title,module='HR',units='mm',design_status='review',
          design_basis=['IS 800:2007','IS 875 Parts 1–5 (as applicable)','IS 1893 Part 1:2016 including amendments',
          'IS 18168:2023 where applicable','IS 808:2021 and IS 2062 Part 1:2025']),
          'materials':{},'profiles':{},'members':[],'panels':[],'connections':[],'checks':[],'units':[],'levels':[],
          'assumptions':list(case.notes)+['Site soil Type II pending geotechnical confirmation.',
          'Trial connection details and matched source member checks are recorded where available. Each unverified design item retains review status.'],
          'grids':{},'separation_joints':[]}
    for id,grade,standard in [('E250B0','E250B0','IS 2062 Part 1:2025'),('E350','E350','IS 2062 Part 1:2025'),
                     ('YST310','YST310','IS 1161:2014'),('IS801-FY240','Fy 240','IS 801:1975 / IS 811:1987'),
                     ('SHEET','Profiled sheet','Cladding supplier trial specification'),('CONC','M25','IS 456 (design assumption)')]:
        data['materials'][id]=dict(grade=grade,standard=standard)
    grids={'x':set(),'y':set()}; zs=set()
    for u in case.units:
        offset=[float(u.offset[0]*1000),float(u.offset[1]*1000),0.]
        data['units'].append(dict(id=u.name,name=u.name,origin_mm=offset,levels=[f'EL-{h:g}' for h in _levels(u)]))
        source=jobdir if len(configs)==1 else jobdir/'units'/u.name
        cfg=dict(configs[u.name])
        # Releasing the physical files may follow several independent sizing
        # runs. Use the selected job's actual details and applied actions.
        # The Python model callbacks are regenerated from the versioned recipe;
        # the upstream writer checks every native work line, profile and grade.
        snapshot_file=source/'design'/'cfg_snapshot.json'
        if snapshot_file.exists():
            snapshot=json.loads(snapshot_file.read_bytes())
            if case.number<=5:
                # Fabrication coordinates are supplemental to the native plate
                # and bolt capacity spec. Retain them only for that exact spec.
                for family in ('beam_column','rafter_splice'):
                    for label,selected in snapshot.get('connections',{}).get(family,{}).items():
                        proposed=cfg.get('connections',{}).get(family,{}).get(label,{})
                        if 'fabrication' not in selected and proposed.get('fabrication'):
                            if selected.get('end_plate')!=proposed.get('end_plate'):
                                raise ValueError(f'{name} {label}: proposed drawing data differs from the selected native end plate')
                            selected['fabrication']=proposed['fabrication']
            for key in ('connections','truss_connections','member_overrides','physical_secondaries','secondary_members',
                        'load_plan','crane','flange_braces','gage_bracing','connected_crossings','purlin_spacing_mm',
                        'girt_spacing_mm','beam_lateral_bracing','column_lateral_support_both_flanges','seismic_restraint_layout'):
                if key in snapshot:cfg[key]=snapshot[key]
                elif key in cfg:cfg.pop(key)
        model=UnitModel(data,case,u,cfg,hr,cfs or hr.parent/'cfs',source,offset)
        from enclosure import envelope
        model.primary();model.secondaries();envelope(model);model.joints()
        from restraints import draw as draw_restraints
        draw_restraints(model)
        if case.number in (1,2,3,4,5):
            from peb_details import detail
        else:
            from native_joint_parts import detail
        detail(model)
        from evidence import unit_evidence
        summary.setdefault('units',[]).append(unit_evidence(cfg,source,u,case,specs))
        if case.number<=5 and specs:
            from peb_details import specification_pages
            summary['units'][-1]['peb_verified_pdf_pages']=specification_pages(specs,case)
        for k,count,step,o in [('x',u.nx,u.sx,offset[0]),('y',u.ny,u.sy,offset[1])]:
            grids[k].update(o+i*step*1000 for i in range(count+1))
        zs.update(_levels(u))
    for k,pts in grids.items():data['grids'][k]=[dict(id=f'{k.upper()}{i+1}',coordinate_mm=v) for i,v in enumerate(sorted(pts))]
    data['levels']=[dict(id=f'EL-{v:g}',elevation_mm=v) for v in sorted(zs)]
    if len(case.units)>1:
        for i,(u,v) in enumerate(zip(case.units,case.units[1:]),1):
            axis='y' if case.number==19 else 'x'; sg=-1 if case.number==19 else 1
            data['separation_joints'].append(dict(id='SJ'+str(i),units=[u.name,v.name],axis=axis,direction=sg,
                 declared_gap_mm=250 if case.number==12 else 400,reference='IS 1893 Part 1, 7.11.3'))
        from setout import place
        place(data,case,jobdir)
    if any(r['status']=='fail' for r in data['checks']):data['project']['design_status']='fail'
    # A missing native viewer cannot substantiate a reference. Exporter preserves an explicit review gate.
    if not (jobdir/'viewer_3d.html').exists() and len(configs)==1:
        for r in data['members']:
            r.pop('source_element',None);r.pop('source_elements',None)
    result=export_handoff(jobdir,data)
    shutil.copyfile(result,dest/'handoff.json')
    obj=json.loads(result.read_text(encoding='utf-8'))
    summary.update(handoff_sha256=hashlib.sha256(result.read_bytes()).hexdigest(),members=len(data['members']),
                   panels=len(data['panels']),connections=len(data['connections']),physical_profiles=len(data['profiles']),
                   source_evidence=obj.get('source_evidence'),checked_design_status=obj['project']['design_status'],
                   assumptions=data['assumptions'],separation_joints=data['separation_joints'])
    (dest/'evidence.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f"{name}: {summary['members']} members, {summary['connections']} joints, {summary['panels']} panels; native {obj.get('source_evidence',{}).get('native_status')}",flush=True)
