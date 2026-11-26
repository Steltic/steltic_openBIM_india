"""Place the design's PEB restraints, anchor rings and solar coverage at their actual work points."""
import math

import peb_build as PB
import sections as S


def specification_pages(specs,case):
    """Check licensed primary pages locally and publish only locators and file digests."""
    from hashlib import sha256
    from pathlib import Path
    import pymupdf
    pages={'IS_800_2007.pdf':[(32,'4.6','4.6 frame stability'),(37,'rafter','Table 6 industrial roofs and columns'),
        (64,'8.3.2','8.3.2 flange restraint'),(95,'12.10','12.10 ordinary moment connections')],
        'IS_2062_Part_1_2025.pdf':[(9,'350','Table 3 E350 steel by thickness')]}
    if case.number in (2,4):
        pages['IS_800_2007.pdf'].append((96,'12.11','12.11 special moment framing'))
        pages['IS_18168_2023.pdf']=[(7,'classification','5.3 seismic compactness'),(9,'6.2','6.2 beam restraint'),
                                    (10,'slenderness','7.2 seismic column slenderness')]
    records=[]
    for name,lookups in pages.items():
        path=Path(specs)/name
        digest=sha256(path.read_bytes()).hexdigest()
        with pymupdf.open(path) as doc:
            for p,term,cite in lookups:
                present=term in doc[p-1].get_text().lower()
                if not present:raise ValueError(f'{name} PDF page {p} does not match the adopted clause')
                records.append(dict(file=name,sha256=digest,pdf_page=p,clause=cite,verified=True))
    return records


def _roof_depth(model,j,distance):
    u=model.u;g=model.cfg['gold'];plane=g['roof_planes'][0]
    schedules=plane.get('rafter_members_by_line',{}).get(str(j),plane['rafter_members'])['lo']
    x0=0.
    for end,label in schedules:
        if distance<=end+.001:
            f=max(0,min(1,(distance-x0)/(end-x0)))
            return S.props(PB.section_at(label,f))['d']
        x0=end
    raise ValueError('Restraint beyond tapered roof profile')


def restraints(model):
    u=model.u;c=model.cfg;w=u.sx*u.nx*1000;h=sum(u.heights)*1000; sy=u.sy*1000
    slope=2*model.case.rise*1000/w;rise=math.hypot(1,slope)
    section=c['flange_braces']['members']['default']['section']
    fly=c['flange_braces']['rafter']['fly_braces_mm']
    for j in range(u.ny+1):
        sign=1 if j<u.ny else -1
        y=sy*j
        for side in (0,1):
            for i,distance in enumerate(fly,1):
                x=distance if side==0 else w-distance
                z=model.roof_z(x)
                depth=_roof_depth(model,j,distance)
                # The diagonal links the lower flange to its purlin at the
                # underside of the roof sheet. It is inclined 45° in the YZ plane.
                a=(x,y,z-depth/(2*rise));b=(x,y+sign*depth/rise,z+depth/(2*rise))
                row=model.member('rafter flange brace',section,a,b,material='E250B0',
                    mid=f'FLY-R-{j}-{side}-{i}',bind=False)
                row['basis']='IS 800 8.3.2; one-leg connection with two M20 class 8.8 bolts; native 1.5 m length envelope.'
            for i,z in enumerate(c['flange_braces']['column']['fly_braces_mm'],1):
                label=c['gold']['peb_column']
                depth=S.props(PB.section_at(label,z/h))['d']
                x=0 if side==0 else w; inward=1 if side==0 else -1
                a=(x+inward*depth/2,y,z);b=(x-inward*depth/2,y+sign*depth,z)
                row=model.member('column flange brace',section,a,b,material='E250B0',
                                 mid=f'FLY-C-{j}-{side}-{i}',bind=False)
                row['basis']='Both flange levels are tied via the outer girt line; two M20 class 8.8 bolts.'


def _base(model,joint,detail,ref):
    b,l,t=(detail[k] for k in ('B_mm','L_mm','t_plate_mm'))
    x,y,z=joint['at']
    # Width follows the physical column flange direction; length follows the web.
    ux,uy=ref[:2]
    def pos(a,b,vertical):
        return [round(x+ux*a+uy*b,4),round(y+uy*a-ux*b,4),round(z+vertical,4)]
    an=detail['anchors'];n=an['n_per_row'];ed=an['edge_mm'];d=an['d_mm']
    shank=an['embedment']['L_mm']
    centre=lambda extent,k:(extent/2-ed)*(2*k/(n-1)-1)
    locations=[(centre(b,i),centre(l,j)) for i in range(n) for j in range(n) if i in (0,n-1) or j in (0,n-1)]
    hole_radius=(d+(2 if d<=24 else 3))/2
    holes=[[pos(a+hole_radius*math.cos(i*math.tau/16),bb+hole_radius*math.sin(i*math.tau/16),-t)
            for i in range(16)] for a,bb in locations]
    model.materials.setdefault('BOLT-8.8',dict(grade='8.8',standard='IS 1367 Part 3'))
    # Polygon winding gives the top-of-steel direction. No drilled geometry is
    # asserted for the column: only its actual base plate carries these holes.
    outline=[pos(-b/2,-l/2,-t),pos(-b/2,l/2,-t),pos(b/2,l/2,-t),pos(b/2,-l/2,-t)]
    joint['parts']=[dict(id=joint['id']+'-BP',kind='plate',material='E250B0',thickness_mm=t,outline=outline,openings=holes)]
    for i,(xx,yy) in enumerate(locations,1):
        joint['parts'].append(dict(id=joint['id']+f'-A{i}',kind='bolt',material='BOLT-8.8',diameter_mm=d,
            start=pos(xx,yy,-t-50-shank),end=pos(xx,yy,d)))
    joint['parameters']=dict(plate_width_mm=b,plate_length_mm=l,plate_thickness_mm=t,
        anchor_count=len(locations),anchor_diameter_mm=d,anchor_grade='8.8',hole_diameter_mm=2*hole_radius,
        minimum_anchor_edge_mm=ed,embedment_mm=shank,grout_mm=50,concrete_strength_mpa=detail['fck_MPa'])
    if detail.get('stiffeners'):
        st=detail['stiffeners']
        joint['parameters'].update(gusset_thickness_mm=st['t_mm'],gusset_height_mm=st['h_mm'],
                                   gussets_per_face=st['n_per_side'])
    joint['description']='Designed cast-in anchor ring with plain shanks. The foundation engineer verifies the pedestal, grout and concrete breakout. The model uses one bolt diameter of projection above the plate.'


def _moment(model,joint,spec,normal,face,paired):
    from native_joint_parts import bolt,location,plate,steel
    from steltic_openbim_india.geometry import cross,unit
    ep=spec['end_plate']; f=spec['fabrication'];sh=spec['shear']
    normal=unit(normal)
    width_axis=(0,1 if normal[0]>0 else -1,0);depth_axis=unit(cross(normal,width_axis))
    width=f['width_mm'];height=f['height_mm'];thickness=ep['t_plate_mm'];dia=ep['d_mm']
    rows=sorted({sign*abs(r['h_mm']-ep['hf_mm']/2) for r in ep['rows'] for sign in (-1,1)})
    holes=[(width/2+sg*f['gauge_mm']/2,height/2+h,(dia+(2 if dia<=24 else 3))/2) for h in rows for sg in (-1,1)]
    origin=location(face,(width_axis,-width/2),(depth_axis,-height/2))
    parts=[]
    for j,offset in enumerate((-thickness,0) if paired else (0,),1):
        parts.append(plate(joint['id']+f'-EP{j}',location(origin,(normal,offset)),width_axis,depth_axis,width,height,
                     thickness,steel(model,ep['plate_grade']),holes))
    # For a column flange the receiver's workline solid has no drilled openings.
    # Declare only the grip in a designed plate, with full common grip at pairs.
    for i,(x,y,r) in enumerate(holes,1):
        at=location(origin,(width_axis,x),(depth_axis,y))
        parts.append(bolt(model,joint['id']+f'-M{i}',at,normal,-thickness if paired else 0,thickness,dia,ep['grade']))
    joint['parts']=parts
    joint['parameters']=dict(plate_width_mm=f['width_mm'],plate_depth_mm=round(f['height_mm'],2),
        plate_thickness_mm=ep['t_plate_mm'],plate_grade=ep['plate_grade'],bolt_diameter_mm=ep['d_mm'],
        bolt_grade=ep['grade'],moment_bolt_count=len(holes),gauge_mm=f['gauge_mm'],
        pitch_mm=f['pitch_mm'],web_doubler_mm=20,continuity_plate_mm=spec['continuity_plate_t_mm'],
        shear_bolt_count=sh['bolts']['n_bolts'],shear_bolt_diameter_mm=sh['bolts']['d_mm'],
        shear_fin_count=sh['n_plates'],shear_fin_thickness_mm=sh['t_plate_mm']/sh['n_plates'])
    joint['description']='Symmetric extended end plate with matched HSFG bolt rows, double shear fins and CJP flange welds. The model gives the bolt grip through the shown plates. Coordinate the host holes, member cutbacks and weld bevels at fabrication.'


def detail(model):
    d=model.data; c=model.cfg; u=model.u; w=u.nx*u.sx*1000; n=model.case.number
    members={r['id']:r for r in d['members'] if r['unit']==u.name}
    conn=c['connections'];sy=u.sy*1000
    for joint in d['connections']:
        if joint['unit']!=u.name:continue
        rows=[members[x] for x in joint['members']]
        columns=[r for r in rows if r['role'] in ('column','gable post')]
        rafters=[r for r in rows if r['role'] in ('rafter','gable rafter')]
        x,y,z=[a-b for a,b in zip(joint['at'],model.offset)]
        if z<.01 and columns:
            col=columns[0]; spec=conn['column_base'].get(col['profile'],conn['column_base']['default'])
            _base(model,joint,spec,col.get('ref_direction') or [0,1,0])
        elif rafters and (min(abs(x),abs(x-w))<1 and abs(y)>1 and abs(y-u.ny*sy)>1):
            sec=PB.section_at(c['gold']['roof_planes'][0]['rafter_members']['lo'][0][1],0)
            sign=1 if x<w/2 else -1
            face=list(joint['at']);face[0]+=sign*S.props(PB.section_at(c['gold']['peb_column'],1))['d']/2
            joint['type']='portal knee';_moment(model,joint,conn['beam_column'][sec],(sign,0,0),face,False)
        elif len(rafters)>=2 and (abs(x-w/2)<1 or all(abs(x-i*u.sx*1000)>1 for i in range(u.nx+1))) and not columns:
            joint['type']='apex splice' if abs(x-w/2)<1 else 'rafter splice'
            slope=0 if abs(x-w/2)<1 else 2*model.case.rise*1000/w*(1 if x<w/2 else -1)
            _moment(model,joint,conn['rafter_splice']['default'],(1,0,slope),joint['at'],True)
        elif any(r['role']=='brace' for r in rows):
            spec=conn['brace_end'][c['brace']]
            gs=spec['gusset'];ws=spec['welds']
            joint['parameters']=dict(gusset_thickness_mm=gs['t_mm'],weld_length_mm=ws['length_mm'],weld_lines=ws['n_sides'],
                                       gusset_free_length_mm=gs['L_unbraced_mm'])
            joint['description']=spec['detail']+'. The native brace-end checks use the stated gusset length and complete-penetration welds.'
    if n==2:
        for row in members.values():
            if row['role']!='canopy':continue
            a=row['start'];j=round((a[1]-model.offset[1])/sy)
            column=next(x for x in members.values() if x['role']=='column' and abs(x['start'][0]-model.offset[0]-w)<1 and abs(x['start'][1]-a[1])<1)
            joint=dict(id=model.pre+f'CAN-ROOT-{j}',type='canopy root',at=a,level=row['level'],unit=u.name,members=[column['id'],row['id']])
            _moment(model,joint,conn['rafter_splice']['canopy_root'],(1,0,0),a,False); d['connections'].append(joint)
    if n==5:
        from solar_capacity import fields
        from handoff import check
        from secondary import select_z
        d['materials']['PV']=dict(grade='PV module assembly',standard='PV vendor load supplied in test brief')
        regions=fields(w,sy*u.ny)
        for i,(x0,x1,y0,y1) in enumerate(regions,1):
            points=[(a,b,model.roof_z(a)+100) for a,b in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
            model.panel('PV array',points,35,'PV',f'PV-FIELD-{i}')
        d['assumptions'].append('Four PV module fields supply 75% coverage, at least 0.6 m clear of eaves and ridge, with 1 m clear across mid-length. Module depth assumed 35 mm; vendor designs rail and clamp fixings.')
        purlins=[r for r in members.values() if r['role']=='purlin']
        gravity=c['D_roof']+c['D_roof_collateral']+c['Lr'];mw=c['load_plan']['member_wind']
        uplift=max(abs(min(v['roof_windward_kNm2'],v['roof_leeward_kNm2'])) for v in mw)
        baseline=select_z(model.cfs,sy,model.case.purlin_spacing*1000,gravity,uplift,fixed=purlins[0]['profile'])[2]
        key=check(d['checks'],model.pre+'Z-ROOF-CLEAR','Original unladen purlins outside the array tributary strip.','pass' if baseline<=1 else 'fail',baseline,'IS 801 clauses 5.2 and 6.3–6.5')
        for row in purlins:
            sx=row['start'][0]-model.offset[0]
            if all(sx+750<=x0 or sx-750>=x1 for x0,x1,y0,y1 in regions):row['checks']=[key]
