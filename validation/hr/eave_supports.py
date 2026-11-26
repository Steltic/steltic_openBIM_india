"""Welded fascia rails and column haunches for the six HR shed roof edges."""
import math

from bearing import UP,centre,endpoints,location
from native_joint_parts import plate
from peb_takeoff import area
from steltic_openbim_india.geometry import cross,dot,frame,plane,sub,unit


def rev(v):return tuple(-p for p in v)


def make_weld(key,a,b,leg,normal):
    return dict(id=key,kind='weld',start=a,end=b,leg_mm=leg,ref_direction=list(normal),material='WELD410')


def gable_overhangs(f,cross_i,lo,hi,axis0,length,nspans,fascia_axes):
    """Check each actual projecting secondary between its outside bearing and the gable line."""
    import sections
    import india_is800 as hr
    from is811_sections import props as z_props
    from is801_members import bending_allowable,web_shear_64
    import india_wind_tables as wind
    along_i=1-cross_i
    model=f.model
    cfg=model.cfg
    suction=cfg['load_plan']['wind_summary']['pz_kNm2']*(2.+abs(wind.cpi_from_openings(model.case.openings)['Cpi']))
    gravity=cfg['D_roof']+cfg.get('D_roof_collateral',0)+cfg.get('D_roof_pv',0)+max(cfg.get('Lr',0),cfg.get('snow',0) or 0)
    existing=[r for r in f.members if r['role'] in ('purlin','roof joist','secondary beam') and
              r['level']==model.level(model.datums[-1]) and abs(unit(sub(r['end'],r['start']))[along_i])>.999]
    records=[]
    for i,(edge,grid) in enumerate(((lo,axis0),(hi,axis0+nspans*length))):
        extended=[r for r in existing if any(abs(p[along_i]-edge)<1. for p in endpoints(r))]
        if not extended:raise ValueError('No gable carrier terminates at the installed roof edge')
        pos=sorted({round(centre(r)[cross_i],2) for r in extended}|set(fascia_axes))
        by_profile={}
        # The nominal 100 mm fastening shoe is wholly inboard of its support workline.
        arm=abs(edge-grid)+100.
        for r in extended:
            station=pos.index(round(centre(r)[cross_i],2))
            if not 0<station<len(pos)-1:raise ValueError('Actual carrier projects beyond the eave fascia')
            trib=(pos[station+1]-pos[station-1])/2000.
            name=r['profile'];dims=f.data['profiles'][name]['dimensions_mm'];typ=f.data['profiles'][name]['family']
            slope=abs(frame(*endpoints(r),r.get('ref_direction'))[0][2])
            cosine=math.sqrt(1.-slope*slope)
            if typ=='Z':
                prop=z_props(name);weight=prop['A']*7.85e-5
                down=(gravity*trib+weight)*cosine
                up=suction*trib/cosine
                statement='Roof system fixes the top flange, with cantilever effective unbraced length twice the full projection. Confirm gable edge fixing and torsional restraint at its primary support.'
                available=lambda reverse:bending_allowable(prop,240,2*arm,wind_eq=reverse,zed_basis=statement)['Ma_Nmm']
                bend=max(down*arm**2/(2*available(False)),up*arm**2/(2*available(True)))
                shear=max(web_shear_64(prop,240,v*arm,wind_eq=reverse)['dc'] for v,reverse in ((up,True),(down,False)))
                defl=max(up,down)*arm**4/(8*200000*prop['Ix'])/(arm/180)
            else:
                prop=sections.props(name);weight=prop['A']*7.85e-5;fy=f.data['materials'][r['material']]['fy_mpa']
                down=gravity*trib+weight;up=suction*trib/cosine
                w=max(down*cosine,up);weak=down*slope
                mx=hr.ltb_moment_capacity(prop,2*arm,fy,support='cantilever',welded=typ=='RHS')['Md_Nmm']
                my=hr.ltb_moment_capacity(prop,2*arm,fy,support='cantilever',axis='y',welded=typ=='RHS')['Md_Nmm']
                bend=1.5*arm**2/2*(w/mx+weak/my)
                shear_area=(dims['d']-2*dims['tf'])*dims['tw']*(2 if typ=='RHS' else 1)
                # On channels fix within 18 mm of the web centreline. For a uniform-flange
                # channel the shear centre is outside its web by at most half the flange width.
                ecc=dims['b']/2+18. if typ=='C' else 0.
                torque=w*arm*ecc;J=prop['J']
                shear=1.5*(math.hypot(w,weak)*arm/shear_area+torque*max(dims['tw'],dims['tf'])/J)/(fy/(math.sqrt(3)*1.1))
                vertical=arm**4/(8*2.e5)*math.hypot(w/prop['Ix'],weak/prop['Iy'])
                twist=w*ecc*arm**2/(2*76900.*J)
                defl=(vertical+ecc*twist)/(arm/180)
            dc=max(bend,shear,defl);design_uplift=1.5*up*arm/1000
            # The outer overhang has the opposite sign to the first inboard simple span.
            # These records give the added reach demand separately from that span's reaction.
            key=(name,i)
            if key not in by_profile or dc>by_profile[key]['utilization']:
                by_profile[key]=dict(profile=name,gable=i,governing_member=r['id'],projection_mm=abs(edge-grid),
                    conservative_arm_mm=arm,tributary_m=round(trib,4),bending_dc=round(bend,4),
                    shear_torsion_dc=round(shear,4),deflection_dc=round(defl,4),utilization=dc,
                    additional_factored_root_uplift_kN=round(design_uplift,3))
        for row in by_profile.values():
            ck=model.pre+f"GABLE-CANT-{i}-{row['profile']}"
            dc=row['utilization']
            f.data['checks'].append(dict(id=ck,status='pass' if dc<=1 else 'fail',utilization=round(dc,5),
                description=f"{row['governing_member']}: {arm:.1f} mm conservative gable cantilever, {row['tributary_m']:.3f} m tributary. Added factored local uplift {row['additional_factored_root_uplift_kN']:.2f} kN per support. Wind reversal, flexure, shear and displacement assessed; channel screw line within 18 mm of its web.",
                reference='IS 875 Part 3 Table 6 local pressure. IS 800 8.2, 8.4, torsion, L/180; IS 801 6.1–6.4 on cold-formed sections with 2L unbraced length.'))
            records.append(row)
    return records


def rail_size(span,overhang,trib,normal,model):
    """A singly supported bay and cantilever extension under separately enveloped actions."""
    import india_wind_tables as wind
    cfg=model.cfg;cd=model.case
    pz=cfg['load_plan']['wind_summary']['pz_kNm2']
    cpi=abs(wind.cpi_from_openings(cd.openings)['Cpi'])
    # Envelope the local gable/eave strips, all height ratios and 0–20° in the
    # checked Table 6, with unreduced pz (Kd=Ka=Kc=1) and adverse internal pressure.
    suction=(2.0+cpi)*pz
    gravity=cfg['D_roof']+cfg.get('D_roof_collateral',0)+cfg.get('D_roof_pv',0)+max(cfg.get('Lr',0),cfg.get('snow',0) or 0)
    pressure=max(gravity,suction)
    slope=math.hypot(*normal[:2])/normal[2]
    for h,b,t in ((150,100,5),(180,120,6),(200,120,6),(225,140,6),(250,150,8),(300,160,8),
                  (350,180,8),(400,200,10),(450,225,12),(500,250,12),(600,250,16)):
        A=b*h-(b-2*t)*(h-2*t);Ix=(b*h**3-(b-2*t)*(h-2*t)**3)/12;Iy=(h*b**3-(h-2*t)*(b-2*t)**3)/12
        # Biaxial wind includes the sloping roof reaction and the exposed vertical fascia.
        vertical=max(1.5*(gravity*trib+.10+A*7.85e-5),1.5*suction*trib)
        horizontal=1.5*suction*(trib*slope+(h/1000))
        lm=max(span**2/8,overhang**2/2)
        bend=1.1*(vertical*lm*h/(2*Ix)+horizontal*lm*b/(2*Iy))/250
        shear=math.hypot(vertical,horizontal)*(span/2+overhang)/(2*t*(h-2*t)*250/(math.sqrt(3)*1.1))
        deflection=5*vertical/1.5*span**4/(384*2.e5*Ix)/(span/240)
        if max(bend,shear,deflection)<=.90:
            return h,b,t,dict(bending_dc=bend,shear_dc=shear,deflection_dc=deflection,
                 vertical_design_N_mm=vertical,horizontal_design_N_mm=horizontal,
                 local_suction_kNm2=suction,design_screw_load_kN=1.5*suction*trib*.15)
    raise ValueError('No eave box rail satisfies the actual span and roof edge actions')


def bracket(f,host,rails,mid,along,out,n,roof,dimensions,loads,Rv,Rh,domain,mark):
    m=f.model;z_top=max(p[2] for p in endpoints(host));h,b,tw=dimensions
    level=rails[0]['level'];steel='E250B0';key=m.pre+'EAVE-SEAT-'+mark
    tcap=16.;wcap=b+25.;lcap=180.
    local_x,local_y,_=frame(*endpoints(host),host.get('ref_direction'))
    hp=f.data['profiles'][host['profile']]['dimensions_mm'];cold=hp['d'];colb=hp['b'];coltf=hp['tf']
    weak=f.data['profiles'][host['profile']]['family'] in ('I','TAPERED_I') and abs(dot(local_x,out))>.75
    seam_spacing=(cold-coltf)/2 if weak else min(100,.34*(max(colb,cold) if f.data['profiles'][host['profile']]['family']=='RHS' else colb))
    # The weak side of an I has two real flange toes. Other orientations present
    # a full flange or box wall. Sample each seam on the actual steel.
    along=unit(along);out=unit(out)
    cap_x=along if dot(cross(along,out),UP)>0 else rev(along)
    rise=unit(cross(n,cap_x))
    if dot(rise,out)<0:raise ValueError('Reversed eave cap frame')
    underside=lambda xy:(roof-dot(n,(xy[0],xy[1],0))-h-tcap)/n[2]
    capmid=list(mid);capmid[2]=underside(capmid)
    capbase=location(capmid,(cap_x,-lcap/2),(rise,-wcap/2))
    root_axis=host['end'];outer_face=dot(out,root_axis)+f.extremity(host,out)[1]
    root_origin=location(root_axis,(out,outer_face-dot(root_axis,out)))
    # Choose a welded box haunch termination. Full-height welds at the column
    # and twin webs carry the vertical force, axial face force and overturning.
    width=max(180,2*seam_spacing+24);Wroot=max(85,min(150,width-30));lever=dot(sub(capmid,root_origin),out)
    if lever<=wcap/2:raise ValueError(f'{key}: insufficient outward bracket reach {lever:.1f}')
    for tall,t,back,weld in ((260,12,18,8),(320,16,20,10),(380,16,25,10),(440,20,30,12),(500,25,35,14),(600,30,40,16)):
        rootz=z_top-tall/2-55;dz=abs(capmid[2]-rootz);moment=Rv*lever+Rh*dz
        sig=6*moment/(2*t*tall*tall)+Rh/(2*t*tall)
        shear=1.5*Rv/(2*t*tall)
        plate_dc=math.sqrt(sig**2+3*shear**2)/(240/1.1)
        length=tall-2*weld;throat=.7*weld
        root_weld=math.hypot(6*moment/(4*throat*length**2)+Rh/(4*throat*length),math.sqrt(3)*Rv/(4*throat*length))/(410/1.5)
        parent_t=min(back,coltf,hp.get('tw',coltf) if f.data['profiles'][host['profile']]['family']=='RHS' else coltf)
        parent=math.hypot(6*moment/(2*parent_t*tall**2)+Rh/(2*parent_t*tall),math.sqrt(3)*Rv/(2*parent_t*tall))/(230/1.5)
        # Bending of the backplate from the parallel bracket web welds to the CJP seams.
        rear_strip=abs(seam_spacing-Wroot/2)
        backing=1.1*6*(Rh/(2*tall)+3*moment/tall**2)*rear_strip/(back**2*230)
        # End cutbacks provide 75 mm effective rail attachment on each side
        # of every bay joint; check an entire half-span plus end overhang.
        railw=max(4,min(8,math.floor(tw-1)))
        capweld=math.hypot(Rv,Rh)/len(rails)/(2*.7*railw*75*410/(math.sqrt(3)*1.5))
        if max(plate_dc,root_weld,parent,backing,capweld)<=.93:break
    else:raise ValueError(f'{key}: haunch/weld/parent cannot develop the factored eave reactions')
    parts=[]
    def append(p):
        f.record_plate(p,level,area(p['outline']));parts.append(p);return p
    root_origin[2]=rootz
    back_x=along if dot(cross(along,UP),out)>0 else rev(along)
    bp=append(plate(key+'-BACK',location(root_origin,(back_x,-width/2),(UP,-tall/2)),back_x,UP,width,tall,back,steel))
    cap=append(plate(key+'-CAP',capbase,cap_x,rise,lcap,wcap,tcap,steel))
    # Both full-depth folded outlines end on the true inclined underside of
    # the seating plate. They carry both signs of pressure.
    side_axis=unit(cross(out,UP))
    d0=back;dc=dot(sub(capmid,root_origin),out);d1=dc-wcap/2*dot(rise,out);d2=dc+wcap/2*dot(rise,out)
    def pt(dx,z,transverse=0):
        p=location(root_origin,(out,dx),(side_axis,transverse));p[2]=z;return p
    def top(dx):return underside(pt(dx,0))
    tip_depth=max(120,tall*.48)
    for i,g in enumerate((-Wroot/2,Wroot/2),1):
        outline=[pt(d0,rootz-tall/2,g-t/2),pt(d2,top(d2)-tip_depth,g-t/2),pt(d2,top(d2),g-t/2),
                 pt(d1,top(d1),g-t/2),pt(d0,rootz+tall/2,g-t/2)]
        web=append(dict(id=key+f'-WEB{i}',kind='plate',material=steel,outline=outline,thickness_mm=t))
        for hand in (-1,1):
            v=g+hand*t/2
            parts.append(make_weld(key+f'-WR{i}-{hand}',pt(d0,rootz-tall/2+weld,v),pt(d0,rootz+tall/2-weld,v),weld,out))
        pweb=pt(dc,top(dc),g)
        f.sample(m.pre+'eave-web-cap-'+domain,[web['id'],cap['id']],n,pweb)
    # Root seam design uses a genuine full-penetration butt/T detail over the
    # two flange positions, so no fictitious triangular fillet throat is used.
    for sign in (-1,1):
        root_seam=location(root_origin,(back_x,sign*seam_spacing))
        hit=f.ray(host,root_seam,out)
        if hit is None or abs(hit[1]-outer_face)>.5:raise ValueError(f'{key}: weld misses the supporting column flange')
        parts.append(dict(id=key+'-CJP'+str(sign),kind='weld',weld_type='cjp',material='WELD410',
                          start=location(root_seam,(UP,-tall/2)),end=location(root_seam,(UP,tall/2)),
                          throat_mm=parent_t,width_mm=parent_t,ref_direction=list(out)))
        f.sample(m.pre+'eave-column-'+domain,[host['id'],bp['id']],out,root_seam)
    for rail in rails:
        v=1 if dot(sub(centre(rail),mid),along)>0 else -1
        for k,dx in enumerate((-b/2,b/2),1):
            edge=location(capmid,(n,tcap),(rise,dx))
            parts.append(make_weld(key+'-HOLD-'+rail['id']+str(k),location(edge,(along,v*7.5)),
                                   location(edge,(along,v*82.5)),railw,rev(rise) if dx<0 else rise))
        bearing=location(capmid,(n,tcap),(along,v*38))
        f.sample(m.pre+'eave-cap-rail-'+domain,[cap['id'],rail['id']],n,bearing)
    for piece in parts:
        if piece['kind']=='weld':
            a=piece.get('throat_mm',0)*piece.get('width_mm',0) if piece.get('weld_type') else .5*piece['leg_mm']**2
            f.mass[level]+=a*math.dist(*endpoints(piece))*7.85e-6
    ratios=dict(twin_web_dc=plate_dc,web_weld_dc=root_weld,column_CJP_dc=parent,
                backplate_bending_dc=backing,rail_hold_down_dc=capweld)
    ck=key+'-CHECK'
    f.data['checks'].append(dict(id=ck,status='pass',utilization=max(ratios.values()),
        description=f'Column haunch and fascia hold-down for {Rv/1000:.1f} kN vertical, {Rh/1000:.1f} kN horizontal and {moment/1e6:.1f} kN m at the column face.',
        reference='IS 800:2007 8.2, 8.4 and 10.5.7.1.2. Combined parent stress and weld strength.'))
    f.data['connections'].append(dict(id=key,type='welded eave bracket',level=level,unit=m.u.name,at=list(root_origin),
        members=[host['id']]+[r['id'] for r in rails],parts=parts,checks=[ck],
        parameters={**ratios,'column_face_reach_mm':lever,'root_moment_kNm':moment/1e6,'factored_vertical_kN':Rv/1000,
                    'factored_horizontal_kN':Rh/1000,'column_CJP_length_each_mm':tall,'web_weld_leg_mm':weld,
                    'rail_hold_down_leg_mm':railw,'rafter_workline_unchanged':True},
        description='Twin welded web bracket, CJP backplate seams on actual column flange positions and two rail hold-down welds per span. Detail the approved shop WPS, HAZ/UT access and local force transfer into the supporting column.'))
    f.verified+=1


def fit(f):
    model=f.model;number=model.case.number
    if number not in (6,7,8,9,10,21):return
    walls=next((r['exterior_planes_global_mm'] for r in reversed(f.scope) if 'exterior_planes_global_mm' in r),None)
    if not walls:raise ValueError('Eave design needs installed wall planes')
    cover=[p for p in f.panels if p['role'] in ('roof deck','roof sheeting')]
    cross_i=1 if number in (6,10) else 0;along_i=1-cross_i
    u=model.u;along=tuple(1. if i==along_i else 0. for i in range(3))
    counts=(u.nx,u.ny);spans=(u.sx*1000,u.sy*1000);length=spans[along_i]
    lo=walls[f'{along_i}-0'];hi=walls[f'{along_i}-1'];axis0=model.offset[along_i]
    roofs=sorted(cover,key=lambda p:p['id'])
    records=[];mass0=sum(f.mass.values())+sum(f.extra_mass.values())
    for side in (0,1):
        sg=1 if side else -1;outside=walls[f'{cross_i}-{side}'];grid=model.offset[cross_i]+side*spans[cross_i]*counts[cross_i]
        out=tuple(float(sg) if i==cross_i else 0. for i in range(3))
        edge=[p for p in roofs if any(abs(v[cross_i]-outside)<.6 for v in p['outline'])]
        if not edge:raise ValueError(f'{number}: roof does not meet installed sidewall')
        n=plane(edge[0]['outline'])[3];roof=dot(n,edge[0]['outline'][0])
        eaves=[r for r in f.members if r['role'] in ('purlin','roof joist','secondary beam') and
               (r['role']!='secondary beam' or r['level']==model.level(model.datums[-1])) and
               abs(dot(unit(sub(r['end'],r['start'])),along))>.99]
        nearest=min(abs(centre(r)[cross_i]-outside) for r in eaves)
        trib=max(.20,nearest/2000+.10)
        overhang=max(abs(lo-axis0),abs(hi-axis0-counts[along_i]*length))
        h,b,t,loads=rail_size(length,overhang,trib,n,model)
        width_axis=unit(cross(n,along));offset=(b/2)*abs(width_axis[cross_i])+25
        station=outside-sg*offset
        # Independent IFC samples distinguish the lower edge of the roof from
        # the outer wall and the original structural grid.
        def point(pos,drop):
            v=[0.,0.,0.];v[cross_i]=station;v[along_i]=pos
            v[2]=(roof-dot(n,v)-drop)/n[2];return v
        label=f'RHS{h}X{b}X{t}-EAVE';f.data['profiles'].setdefault(label,dict(family='RHS',dimensions_mm=dict(d=h,b=b,tw=t,tf=t)))
        ck=model.pre+'EAVE-RAIL-'+str(side)
        f.data['checks'].append(dict(id=ck,status='pass',utilization=max(v for k,v in loads.items() if k.endswith('_dc')),
            description=f'{label}, {length:g} mm supported bay and {overhang:.1f} mm end overhang. Local net suction {loads["local_suction_kNm2"]:.3f} kN/m² on the {trib:.3f} m edge tributary.',
            reference='IS 800 8.2, 8.4 and Table 6, L/240. IS 875 Part 3:2015 Table 6 and 7.3.2, local eave/gable suction envelope.'))
        f.data['checks'].append(dict(id=ck+'-SHEET',status='review',description=f'At 150 mm centres the selected sheet-to-fascia screw and sealing washer must develop at least {loads["design_screw_load_kN"]:.3f} kN factored pull-through and withdrawal per fastener. Confirm tested capacity in the actual roofing system.',
                                     reference='IS 875 Part 3:2015, 7.2 and 7.3. Rectangular closed rails are welded to the steel support.'))
        rail=[];unit_area=h*b-(h-2*t)*(b-2*t)
        for j in range(counts[along_i]):
            a=point(lo if j==0 else axis0+j*length,h/2)
            bpt=point(hi if j==counts[along_i]-1 else axis0+(j+1)*length,h/2)
            row=dict(id=model.pre+f'EAVE-RAIL-{side}-{j}',role='fascia rail',unit=u.name,level=model.level(model.datums[-1]),profile=label,
                     material='E250B0',ref_direction=list(width_axis),start=a,end=bpt,checks=[ck,ck+'-SHEET'],
                     basis='Welded closed box, roof-aligned top face. The rolled stock/plate procurement must retain the specified dimensions and certified E250 B0.')
            f.data['members'].append(row);f.members.append(row);rail.append(row)
            f.extra_mass[row['level']]+=unit_area*math.dist(a,bpt)*7.85e-6
            pos=centre(row);host=next(p for p in edge if min(v[along_i] for v in p['outline'])<=pos[along_i]<=max(v[along_i] for v in p['outline']))
            host.setdefault('bearing_members',[]).append(row['id']);f.sample(model.pre+'eave-rail-skin-'+str(side),[row['id'],host['id']],n,pos)
        for j in range(counts[along_i]+1):
            pos=axis0+j*length;connected=rail[max(0,j-1):min(len(rail),j+1)]
            col=[r for r in f.members if r['role']=='column' and abs(r['end'][along_i]-pos)<1 and abs(r['end'][cross_i]-grid)<1]
            if not col:raise ValueError(f'No actual eave column on grid {side}/{pos}')
            host=max(col,key=lambda r:r['end'][2]);trib_length=length if len(connected)==2 else length/2+overhang
            bracket(f,host,connected,point(pos,h),along,out,n,roof,(h,b,t),loads,loads['vertical_design_N_mm']*trib_length,
                    loads['horizontal_design_N_mm']*trib_length,str(side),f'{side}-{j}')
        records.append(dict(side=side,outer_sheet_mm=outside,outer_workline_mm=grid,
                     rail_axis_mm=station,free_sheet_edge_mm=25.,longitudinal_rail_overhang_mm=round(overhang,2),
                     maximum_column_spacing_mm=length,roof_tributary_width_m=round(trib,4),section=label,
                     factored_screw_reaction_kN=round(loads['design_screw_load_kN'],4),fastener_spacing_mm=150))
    mass=round(sum(f.mass.values())+sum(f.extra_mass.values())-mass0,2)
    ends=gable_overhangs(f,cross_i,lo,hi,axis0,length,counts[along_i],{round(r['rail_axis_mm'],2) for r in records})
    f.scope.append(dict(roles=['fascia rail','welded eave bracket'],eaves=records,gable_cantilevers=ends,added_eave_steel_kg=mass))
