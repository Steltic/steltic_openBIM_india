"""Place Hosur's knee hardware from the per-occurrence Section 12 bolt layouts."""
import math

import openseespy.opensees as ops
import sections as S
from steltic_openbim_india.geometry import cross,unit

from native_joint_parts import bolt,location,plate,steel


def index_knees(model,frame,configuration):
    design=configuration.get('truss_connections') or {}
    checks=model.native.get('capacity_design',{}).get('section12',{}).get('checks',[])
    by_occurrence={}
    for check in checks:
        if check.get('member'):
            by_occurrence.setdefault(check['member'],{})[check['id']]=check
    result={}
    delta=getattr(model,'offset',[1000*model.u.offset[0],1000*model.u.offset[1],0])
    for knee in frame.get('truss_knees',[]):
        rows=by_occurrence.get(knee['id'],{})
        if not rows or not design:continue
        p=ops.nodeCoord(knee['knee_node']);q=ops.nodeCoord(knee['chord_node'])
        toward_bay=unit((q[0]-p[0],q[1]-p[1],0))
        for kind,field in [('knee','knee_node'),('chord','chord_node'),('heel','heel_node')]:
            coord=tuple(round(n+d,3) for n,d in zip(ops.nodeCoord(knee[field]),delta))
            result[coord]=(kind,knee,toward_bay,design,rows)
    return result


def link_checks(model,row,kid,records):
    keys=[]
    for record in records:
        key=f"{model.u.name}-{kid}-{record['id']}"
        status={True:'pass',False:'fail',None:'review'}[record.get('ok')]
        check=dict(id=key,description=f"{kid} / {record['id'].split('_',1)[-1].replace('_',' ')}",
                   reference=record['clause'],status=status)
        if isinstance(record.get('dc'),(int,float)) and math.isfinite(record['dc']):
            check['utilization']=record['dc']
        model.data['checks'].append(check);keys.append(key)
    row['checks']=list(dict.fromkeys(row.get('checks',[])+keys))


def drilled_gusset(model,row,at,run,x0,z0,length,height,thickness,grade,groups):
    up=(0.,0.,1.);normal=cross(run,up)
    origin=location(at,(run,x0),(up,z0),(normal,-thickness/2))
    holes=[]
    for label,spec,coords,near,far in groups:
        if len(coords)!=spec['n_bolts']:
            raise ValueError(f"{row['id']}: {label} bolt count differs from the Section 12 design")
        for i,(x,z) in enumerate(coords,1):
            radius=spec['d0_mm']/2
            if any(math.dist((x-x0,z-z0),(u,v))<r+radius for u,v,r in holes):
                raise ValueError(f"{row['id']}: an opening for {label} overlaps a separate bolt hole")
            holes.append((x-x0,z-z0,radius))
            pos=location(at,(run,x),(up,z))
            row['parts'].append(bolt(model,f"{row['id']}-{label}{i}",pos,normal,near,far,spec['d_mm'],spec['grade']))
    row['parts'].append(plate(row['id']+'-G',origin,run,up,length,height,thickness,steel(model,grade),holes))
    row['parameters'].update(gusset_width_mm=length,gusset_height_mm=height,gusset_thickness_mm=thickness,
                             bolt_count=len(holes))


def truss_detail(model,new,station,at,linked):
    kind,knee,run,design,checks=station
    knee_member=next((m for m in linked if m.get('source_element',{}).get('tag')==knee['brace_tag']),None)
    col=next((m for m in linked if m['role']=='column'),None)
    chord=next((m for m in linked if m['role']=='truss bottom chord'),None)
    vertical=next((m for m in linked if m['role']=='truss vertical'),None)
    knee_spec={**design.get('default',{}),**design.get('truss_knee_brace',{})}
    if kind=='heel' and col and chord and design.get('heel'):
        spec=design['heel']
        row=new('pinned truss heel seat',[m for m in linked if m['role'] in ('column','truss top chord','truss bottom chord')])
        row['parameters'].update(connected_plate_mm=spec['t_plate_mm'],bolt_count=spec['n_bolts'],
            bolt_diameter_mm=spec['d_mm'],hole_diameter_mm=spec['d0_mm'],bolt_grade=spec['grade'],
            bolt_pitch_mm=spec['pitch_mm'],bolt_end_mm=spec['end_mm'],thread_shear_planes=spec['nn'])
        row['description']='Pinned chord ends at the column cap. The resultant heel force is checked against the declared double-shear bolt group. The cap has a specified CJP weld to the column. Seat outline, bolt positions, rotation clearance and cap attachment fit require a dimensioned fabrication detail.'
        link_checks(model,row,knee['id'],[c for name,c in checks.items() if 'heel' in name])
        return set()
    if knee_member is None:return set()
    key='12.10.2.1_knee_gusset_layout' if kind=='knee' else '12.10.2.1_knee_chord_gusset_layout'
    layout=checks.get(key,{}).get('layout',{})
    if not layout.get('fits'):return set()
    if kind=='knee' and col and design.get('knee_gusset'):
        g=design['knee_gusset'];h=g['face_length_mm'];t=g['t_mm']
        row=new('knee gusset at column flange',[knee_member,col])
        face=location(at,(run,S.props(col['profile'])['d']/2),((0.,0.,1.),layout['force_line_at_face_above_work_point_mm']))
        drilled_gusset(model,row,face,run,0,layout['weld_centre_above_F_mm']-h/2,
                       g['projection_mm'],h,t,g['grade'],[('K',knee_spec,layout['bolts'],-t/2,t/2)])
        row['description']='The column-face gusset and bolt centres follow the fitted Section 12 knee layout. The CJP weld runs along the column face. Bolt shafts show the grip through the gusset. Angle drilling, weld preparation and bolt hardware require shop coordination.'
        row['parameters'].update(cjp_weld_length_mm=h,bolt_diameter_mm=knee_spec['d_mm'],bolt_pitch_mm=knee_spec['pitch_mm'],
                                 bolt_gauge_mm=knee_spec['gauge_mm'],edge_min_mm=layout['edge_min_mm'])
        link_checks(model,row,knee['id'],[c for name,c in checks.items() if 'knee_gusset' in name or 'column_web' in name])
        return {knee_member['id']}
    if kind!='chord' or chord is None or vertical is None or not design.get('knee_chord_node'):
        return set()
    g=design['knee_chord_node'];t=g['t_mm'];left=g['toward_column_mm'];right=g['toward_midspan_mm']
    chord_section=S.props(chord['profile']);v_spec={**design['default'],**design.get('truss_vertical',{})}
    # The native layout fits the horizontal chord-group length but leaves its start free.
    # Centre that group between the two declared plate edges. The gauge is from the chord heel.
    dz=g['gauge_mm']-chord_section['c_back_mm']
    if g['chord_heel']=='top':dz=-dz
    pitch=g['pitch_mm'];count=g['n_bolts']
    chord_centres=[((right-left)/2+(i-(count-1)/2)*pitch,dz) for i in range(count)]
    a_thick=S.props(chord_section['component'])['tw'];gap=chord_section['gap_mm']
    if abs(t-gap)>.01:
        raise ValueError(f"{knee['id']}: the selected gusset does not match the double-angle packing gap")
    row=new('knee gusset at bottom chord',[m for m in linked if m['role'] in ('knee brace','truss bottom chord','truss vertical')])
    drilled_gusset(model,row,at,run,-left,-g['below_mm'],left+right,g['above_mm']+g['below_mm'],t,g['gusset_grade'],
        [('K',knee_spec,layout['lines']['knee brace'],-t/2,t/2),('V',v_spec,layout['lines']['vertical'],-t/2,t/2),
         ('C',g,chord_centres,-t/2-a_thick,t/2+a_thick)])
    row['description']='The knee and vertical bolt centres use the native fit check. The horizontal group is centred along the declared gusset and drilled at the selected gauge from the chord heel. The chord bolt grip includes both angle legs. Angle cuts, remaining grips and hardware require shop coordination.'
    row['parameters'].update(knee_bolts=knee_spec['n_bolts'],vertical_bolts=v_spec['n_bolts'],chord_bolts=count,
                             chord_bolt_diameter_mm=g['d_mm'],chord_pitch_mm=pitch,chord_gauge_mm=g['gauge_mm'],
                             edge_min_mm=layout['edge_min_mm'])
    link_checks(model,row,knee['id'],[c for name,c in checks.items() if 'knee_chord' in name])
    return {knee_member['id'],vertical['id']}
