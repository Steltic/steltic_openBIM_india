"""Occurrence-specific steel connection hardware from the HR design package (HR6–21)."""
import json
import math
from pathlib import Path

import engine3d as E
import sections as S
from steltic_openbim_india.geometry import cross,dot,frame,sub,unit


def location(origin,*steps):
    return [round(origin[i]+sum(distance*axis[i] for axis,distance in steps),4) for i in range(3)]


def plate(key,origin,xaxis,yaxis,width,height,thick,material,holes=()):
    if min(width,height,thick)<=0 or any(r<=0 or x-r<-.01 or y-r<-.01 or
                                         x+r>width+.01 or y+r>height+.01 for x,y,r in holes):
        raise ValueError(f'{key}: invalid plate extent or a bolt hole breaks a plate edge')
    def point(x,y):return location(origin,(xaxis,x),(yaxis,y))
    outline=[point(x,y) for x,y in ((0,0),(width,0),(width,height),(0,height))]
    result=dict(id=key,kind='plate',outline=outline,material=material,thickness_mm=thick)
    if holes:
        result['openings']=[[point(x+r*math.cos(i*math.tau/12),y+r*math.sin(i*math.tau/12)) for i in range(12)]
                             for x,y,r in holes]
    return result


def bolt(model,key,at,axis,start,stop,diameter,grade):
    material='BOLT-'+str(grade)
    model.materials.setdefault(material,dict(grade=str(grade),standard='IS 1367 Part 3'))
    return dict(id=key,kind='bolt',material=material,diameter_mm=diameter,
                start=location(at,(axis,start)),end=location(at,(axis,stop)))


def flange_frame(member):
    return frame(member['start'],member['end'],member.get('ref_direction'))


def outgoing(row,at):
    return unit(sub(row['end'] if math.dist(at,row['start'])<1 else row['start'],at))


def steel(model,grade):
    value=str(grade or 'E250').upper().replace(' ','')
    model.materials.setdefault(value,dict(grade=value,standard='IS 2062 Part 1:2025'))
    return value


def support_face(col,run):
    p=S.props(col['profile']);wide,deep,_=flange_frame(col)
    if abs(dot(run,wide))>abs(dot(run,deep)):
        # A perpendicular beam meets the web between flanges on an open I.
        return (p['tw'] if p['section_type']=='I' else p['bf'])/(2*abs(dot(run,wide)))
    return p['d']/(2*abs(dot(run,deep)))


def fin(model,row,beam,col,spec):
    p=S.props(beam['profile']);run=outgoing(beam,row['at'])
    lateral=unit(cross(run,(0,0,1)))
    up=unit(cross(lateral,run))
    face=support_face(col,run)
    origin=location(row['at'],(run,face))
    fast=spec['bolts']; bolts=int(fast['n_bolts']);lines=int(spec.get('bolt_lines',1))
    n=bolts//lines; spacing=fast['p_mm'];edge=fast['e_mm'];radius=fast['d0_mm']/2
    gauge=spec.get('gauge_mm',0);thick=spec['t_plate_mm']/spec.get('n_plates',1)
    height=spec['h_plate_mm'];width=2*edge+(lines-1)*gauge
    if n*lines!=bolts or height+1e-6<2*edge+(n-1)*spacing or edge<=radius:
        raise ValueError(f"{row['id']}: fin bolt group cannot fit declared plate")
    hole=[(edge+j*gauge,edge+i*spacing,radius) for j in range(lines) for i in range(n)]
    normal=cross(run,up)
    base=location(origin,(up,-height/2)); web=p['tw']
    end=0 if math.dist(beam['start'],row['at'])<1 else 1
    cuts=beam.setdefault('end_cutbacks_mm',[0.,0.])
    cuts[end]=max(cuts[end],face)
    drilled=p['section_type']=='I' and abs(dot(flange_frame(beam)[0],normal))>.9999
    offsets=[web/2] if spec.get('n_plates',1)==1 else [web/2,-web/2-thick]
    for i,offset in enumerate(offsets,1):
        part=plate(row['id']+f'-FIN{i}',location(base,(normal,offset)),run,up,width,height,thick,steel(model,spec.get('plate_grade')),hole)
        row['parts'].append(part)
    lo=-web/2-(thick if len(offsets)==2 else 0)
    for i,(x,y,r) in enumerate(hole,1):
        at=location(base,(run,x),(up,y))
        row['parts'].append(bolt(model,row['id']+f'-B{i}',at,normal,lo,web/2+thick,fast['d_mm'],fast['grade']))
        if drilled:
            beam.setdefault('member_voids',[]).append(dict(id=row['id']+f'-W{i}',kind='bore',connection=row['id'],
                 start=location(at,(normal,-web/2-1.)),end=location(at,(normal,web/2+1.)),diameter_mm=2*r))
    row['parameters'].update(fin_plate_count=len(offsets),fin_thickness_mm=thick,fin_height_mm=height,fin_width_mm=width,
        hole_diameter_mm=2*radius,bolt_count=bolts,bolt_diameter_mm=fast['d_mm'],bolt_grade=str(fast['grade']),
        bolt_lines=lines,edge_mm=edge,pitch_mm=spacing,gauge_mm=gauge,beam_web_holes=bolts if drilled else 0)
    return origin,run,lateral,up


def cover(model,row,beam,axes,spec):
    c=spec['cover_plate'];p=S.props(beam['profile']);origin,run,lat,up=axes
    t=c['plate_t_mm'];width=c['plate_b_mm'];weld=c['weld'];length=weld['length_mm'];leg=weld['size_mm']
    for k,(nm,off) in enumerate((('TOP',p['d']/2),('BOT',-p['d']/2-t))):
        # run x (-lateral) points towards the top face of the horizontal flange.
        transverse=unit(cross(up,run))
        corner=location(origin,(transverse,-width/2),(up,off))
        row['parts'].append(plate(row['id']+'-'+nm,corner,run,transverse,length,width,t,steel(model,c.get('plate_grade'))))
        # The design assigns a single effective longitudinal fillet to each cover.
        # Draw that effective run with a triangular fillet section at the plate edge.
        wpt=location(corner,(up,0 if k==0 else t))
        row['parts'].append(dict(id=row['id']+'-'+nm+'-W',kind='weld',material='WELD410',leg_mm=leg,
            start=wpt,end=location(wpt,(run,length)),ref_direction=list(transverse if k else tuple(-v for v in transverse))))
    model.materials.setdefault('WELD410',dict(grade='410 MPa matching consumable',standard='IS 814 / IS 800 section 10'))
    row['parameters'].update(cover_width_mm=width,cover_thickness_mm=t,cover_effective_weld_length_mm=length,
        cover_weld_leg_mm=leg,continuity_plate_mm=spec.get('continuity_plate_t_mm',0),panel_zone_doubler_mm=spec.get('doubler_t_mm',0))


def base(model,row,col,spec):
    p=S.props(col['profile']);width,deep,_=flange_frame(col);normal=(0,0,1)
    if cross(width,deep)[2]<0:deep=tuple(-v for v in deep)
    B,L,t=spec['B_mm'],spec['L_mm'],spec['t_plate_mm']
    a=spec['anchors'];n=int(a['n_per_row']);ed=a['edge_mm'];dia=a['d_mm']
    dia_hole=dia+(2 if dia<=24 else 3)
    pts=[(ed+(B-2*ed)*i/(n-1),ed+(L-2*ed)*j/(n-1),dia_hole/2)
         for i in range(n) for j in range(n) if i in (0,n-1) or j in (0,n-1)]
    if len(pts)!=a['n_total']:raise ValueError(f"{row['id']}: ring count differs from native selection")
    corner=location(row['at'],(width,-B/2),(deep,-L/2),(normal,-t))
    row['parts']=[plate(row['id']+'-BP',corner,width,deep,B,L,t,steel(model,spec.get('plate_grade')),pts)]
    embed=(a.get('embedment') or {}).get('L_mm')
    # The grip through the selected plate is measured. Extend only if the
    # design supplies an embedded length. Nut, washer and pit sizing are separate.
    for i,(x,y,r) in enumerate(pts,1):
        at=location(corner,(width,x),(deep,y))
        row['parts'].append(bolt(model,row['id']+f'-A{i}',at,normal,-float(embed or 0),t,dia,a['grade']))
    row['parameters'].update(plate_width_mm=B,plate_length_mm=L,plate_thickness_mm=t,anchor_count=len(pts),
        anchor_diameter_mm=dia,hole_diameter_mm=dia_hole,anchor_edge_mm=ed,anchor_grade=str(a['grade']),
        v_column_depth_mm=p['d'],concrete_mpa=spec['fck_MPa'])
    if embed:row['parameters']['declared_embedment_mm']=embed
    row['description']='Base plate drilled for the selected perimeter anchor ring. Shaft model shows the steel grip and any declared embedment. Foundations, grout thickness and anchor hardware require coordination.'
    from base_fabrication import detail as base_fabrication
    base_fabrication(model,row,col,spec,corner,width,deep,pts)


def gusset(model,row,brace,spec):
    g=spec['gusset'];a=spec.get('bolts');ws=spec.get('welds',{})
    width=g.get('plate_width_mm') or g['w_start_mm'];length=g['L_conn_mm'];t=g['t_mm']
    run=outgoing(brace,row['at'])
    side=unit(cross((0,0,1),run))
    transverse=unit(cross(side,run))
    corner=location(row['at'],(transverse,-width/2),(side,-t/2))
    holes=[]
    if a:
        e=a['e_mm'];pitch=a['p_mm'];n=int(round((length-2*e)/pitch))+1
        lines=a['n_bolts']//n if n>0 else 0
        if lines not in (1,2) or n*lines!=a['n_bolts'] or abs(2*e+(n-1)*pitch-length)>1:
            raise ValueError(f"{row['id']}: gusset connection length and bolt group disagree")
        gs=g['w_start_mm']-2*e
        holes=[(e+i*pitch,width/2+(j-(lines-1)/2)*gs,a['d0_mm']/2) for i in range(n) for j in range(lines)]
        for i,(x,y,r) in enumerate(holes,1):
            at=location(corner,(run,x),(transverse,y))
            row['parts'].append(bolt(model,row['id']+f'-B{i}',at,side,0,t,a['d_mm'],a['grade']))
        row['parameters'].update(bolt_count=a['n_bolts'],bolt_diameter_mm=a['d_mm'],bolt_grade=str(a['grade']),
                                 hole_diameter_mm=a['d0_mm'],bolt_rows=n,bolt_lines=lines,pitch_mm=pitch,gauge_mm=gs if lines==2 else 0)
    row['parts'].append(plate(row['id']+'-G',corner,run,transverse,length,width,t,steel(model,spec.get('plate_grade')),holes))
    row['parameters'].update(gusset_thickness_mm=t,gusset_connection_length_mm=length,gusset_width_mm=width,
        gusset_free_length_mm=g['L_unbraced_mm'],cjp_weld_length_mm=ws.get('length_mm',0),cjp_weld_lines=ws.get('n_sides',0))
    row['description']='Gusset connection region and through-plate bolt grip. The brace delivers load by its declared longitudinal CJP runs. Verify the mating frame attachment, gusset outline beyond the bolt group and fit-up with adjacent steel.'


def detail(model):
    from truss_joint_parts import index_knees,truss_detail
    snapshot=Path(model.folder)/'design'/'cfg_snapshot.json'
    archived=json.loads(snapshot.read_text(encoding='utf-8-sig')) if snapshot.is_file() else {}
    specs=archived.get('connections') or model.cfg['connections']
    native=E.build(model.cfg,'Linear')
    knee_nodes=index_knees(model,native,archived or model.cfg)
    elements={r[0]:r for r in native['ele']}
    release=native.get('beam_rel',{})
    moment_joints={c['member'] for c in model.native.get('capacity_design',{}).get('section12',{}).get('checks',[])
                   if str(c.get('member','')).startswith('J')}
    by_id={r['id']:r for r in model.data['members'] if r['unit']==model.u.name}
    original=[r for r in model.data['connections'] if r['unit']==model.u.name]
    out=[r for r in model.data['connections'] if r['unit']!=model.u.name]
    for joint in original:
        linked=[by_id[k] for k in joint['members']]
        at=joint['at'];columns=[r for r in linked if r['role'] in ('column','gable post','lean-to column')]
        beams=[r for r in linked if r['role'] in ('beam','rafter','shear link','lean-to roof beam','gable rafter')]
        braces=[r for r in linked if r['role'] in ('brace','truss diagonal','truss vertical','knee brace','lean-to wall brace')]
        count=0
        def new(typ,occ):
            nonlocal count
            count+=1
            row={k:joint[k] for k in ('at','level','unit')}
            row.update(id=joint['id']+f'-{count}',type=typ,members=list(dict.fromkeys(x['id'] for x in occ)),
                       parameters={},parts=[])
            keys=list(dict.fromkeys(i for m in occ for i in model.conn_checks.get(m['profile'],[])))
            if keys:row['checks']=keys
            out.append(row);return row
        knee_station=knee_nodes.get(tuple(round(n,3) for n in at))
        assigned=truss_detail(model,new,knee_station,at,linked) if knee_station else set()
        if columns and abs(at[2])<.01:
            col=columns[0];spec=specs.get('column_base',{}).get(col['profile'])
            if spec and spec.get('layout')=='ring':
                base(model,new('column base',columns),col,spec)
        if len(columns)>=2 and not knee_station:
            top=next((r for r in columns if math.dist(r['start'],at)<1),None)
            bottom=next((r for r in columns if math.dist(r['end'],at)<1),None)
            if top and bottom:
                spec=specs.get('column_splice',{}).get(top['profile'])
                if spec and not spec.get('none'):
                    row=new('column splice',[bottom,top]);row['description']=spec.get('note','Native column splice; fit-up requires detailing.')
                    tr=spec.get('transition')
                    if tr and tr.get('type')=='division_plate':
                        p1,p2=S.props(top['profile']),S.props(bottom['profile'])
                        w=max(p1['bf'],p2['bf']);h=max(p1['d'],p2['d']);t=tr['t_mm']
                        wide,deep,_=flange_frame(bottom)
                        o=location(at,(wide,-w/2),(deep,-h/2),((0,0,1),-t/2))
                        row['parts']=[plate(row['id']+'-DP',o,wide,deep,w,h,t,steel(model,tr.get('grade')))]
                        row['parameters']=dict(division_plate_mm=t,width_mm=w,depth_mm=h,offset_mm=tr['offset_mm'])
                    elif spec.get('weld'):row['parameters']['cjp_throat_mm']=spec['weld'].get('t_mm',0)
        if columns:
            col=columns[0]
            for beam in beams:
                ref=beam.get('source_element')
                if not ref:continue
                tag=ref['tag'];record=elements.get(tag)
                if not record:continue
                at_start=math.dist(beam['start'],at)<1
                node=record[3] if at_start else record[4]
                run=outgoing(beam,at);direction='X' if abs(run[0])>=abs(run[1]) else 'Y'
                is_rigid=release.get(tag,('none','none'))[0] not in ('both','I' if at_start else 'J')
                moment=is_rigid and f'J{node}-{direction}' in moment_joints
                spec=specs.get('beam_column' if moment else 'beam_shear',{}).get(beam['profile'])
                if not spec:continue
                sh=spec.get('shear') if moment else spec
                if not sh or not sh.get('bolts'):continue
                row=new('moment beam to column' if moment else 'fin plate beam to column',[beam,col])
                axes=fin(model,row,beam,col,sh)
                if moment and spec.get('cover_plate'):
                    cover(model,row,beam,axes,spec)
                    row['description']='CJP beam flanges, fillet-welded cover plates and HSFG web fins. The schedule gives the selected bolt group and bored web count. Coordinate the CJP preparation, hardware and panel-zone assembly at fabrication.'
                else:
                    row['description']='HSFG bolts pass through the selected fin plates. The schedule records the bored beam web and physical end set-out. Check any flange cope and fabrication clearances at the support.'
        for brace in braces:
            if brace['id'] in assigned:continue
            spec=specs.get('brace_end',{}).get(brace['profile'])
            if not spec or not spec.get('gusset'):continue
            row=new('brace gusset',[brace]+(columns or beams or [m for m in linked if m!=brace])[:1])
            gusset(model,row,brace,spec)
        if not count:
            joint['description']='Located member interface. No native detail was identified for this occurrence; field connection and section changes require review.'
            out.append(joint)
    model.data['connections']=out
