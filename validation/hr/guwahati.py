"""Independent Guwahati EBF iterations for the flange and stem buildings."""
import math

import frame_build as FB
import hr_autosize as HR
from joint_iteration import SHEAR_KEYS


def revise(case,u,cfg,refinement,ground):
    g=cfg['gold'];connections=cfg['connections'];builder=cfg.get('custom_build')
    for k,bays in g['ebf_bays'].items():
        if u.name=='Flange':
            # Reflect the three north-face X bays about the plan centre, as required by the brief.
            g['ebf_bays'][k]=[[ax,u.nx-i-1 if ax=='X' and j==u.ny else i,j] for ax,i,j in bays]
        else:
            # The two X faces each retain both bays. Each Y end face has ONE bay,
            # rotated by 180 degrees about the centre to avoid a static eccentricity.
            g['ebf_bays'][k]=[[ax,i,j] for ax,i,j in bays if ax=='X' or j==(0 if i==0 else u.ny-1)]
    for k in g['ebf_brace_sec']:
        if int(k)>6:
            g['ebf_brace_sec'][k]=g['brace_sec'][k]='WPB400X400X219.67'
    if u.name=='Flange':
        import sections
        from copy import deepcopy
        lower='BOX750X750X63';sections.register_box(lower,750,750,63,63)
        old='BOX750X750X56'
        for k in ('1','2','3'):g['col_sec']['lateral'][k]=lower
        g['col_sec']['lateral']['12']='BOX400X400X22'
        connections['column_base'][lower]=deepcopy(connections['column_base'][old])
        splice=deepcopy(connections['column_splice'][old]);splice['weld']['t_mm']=63
        splice['note']='Full-penetration field butt splice on the 63 mm shafts with full UT. At the 63 to 40 mm transition taper the inner wall face at 1 in 4.'
        connections['column_splice'][lower]=splice
    else:
        # The two seventh-storey capacity-protected columns exceeded their buckling strength.
        # Continue the 450 mm upper shaft for a further storey. Size its transition at level seven.
        g['col_sec']['lateral']['7']='BOX450X450X25'
        for sec,lower,offset,thickness in [('BOX450X450X25','BOX750X750X40',150.,115.),
                                            ('BOX750X750X40','BOX800X800X40',25.,40.)]:
            sp=connections['column_splice'][sec];sp['transition']={'type':'division_plate','t_mm':thickness,
                'grade':'E250 B0','offset_mm':offset}
            sp['note']=f'Both {sec} and {lower} shafts CJP-welded to the {thickness:g} mm E250 B0 division plate at the section change. Verify material through-thickness properties and weld preparation.'
    # Distinguish 8.5 m gravity beams from the separately checked link/outside segments.
    roof='NPB600X220X122.45';g['beam_sec'].update(roof_X=roof,roof_Y=roof)
    collectors={roof:(400_000,.96)}
    if u.name=='Flange':
        g['beam_sec']['floor_X']='WPB700X300X240.51';cfg['beam']=g['beam_sec']['floor_X']
        for role in ('ebf_link_sec','ebf_beam_sec'):
            g[role]={axis:{k:'WPB650X300X224.78' for k in levels} for axis,levels in g[role].items()}
        collectors.update({'WPB700X300X240.51':(2_100_000,.99),'WPB650X300X224.78':(2_100_000,.99),'WPB550X300X199.44':(1_980_000,.99),
                           'NPB750X270X145.29':(500_000,.4)})
    else:collectors['WPB600X300X211.92']=(1_350_000,1_043_532/1_053_218)
    for sec,(demand,axial_fraction) in collectors.items():
        fin=HR.design_fin_plate(sec,demand,n_frac=axial_fraction,template={'slip_surface':'sand_blasted'})
        if fin is None:raise ValueError(f'{sec}: no fin fitted at {demand/1000:.0f} kN')
        connections['beam_shear'][sec]=fin
    for levels in g['ebf_beam_sec'].values():
        for sec in sorted(set(levels.values())):
            existing=connections['beam_column'].get(sec,{})
            revised=HR.cover_plate_joint_spec(sec,factor=1.75,doubler_t=existing.get('doubler_t_mm',0),
                                                continuity_t=existing.get('continuity_plate_t_mm'))
            revised['shear']={key:value for key,value in (connections['beam_shear'][sec] if sec in collectors else existing['shear']).items() if key in SHEAR_KEYS}
            connections['beam_column'][sec]=revised
    for sec in ('WPB400X300X255.74','WPB400X400X219.67'):
        spec=connections['column_splice'][sec];tr=spec.get('transition')
        if tr:
            tr['t_mm']=5*math.ceil(1.15*tr['t_mm']/5)
            spec['note']=f"Both shafts CJP-welded to {tr['t_mm']:g} mm E250 B0 division plate. Verify through-thickness properties and weld preparation."
    threshold={'Flange':('BOX450X450X32',100),'Stem':('BOX400X400X25',30)}
    sec,t=threshold[u.name]
    sp=connections['column_splice'][sec];sp['transition']['t_mm']=t
    sp['note']=f'Both shafts CJP-welded to the {t} mm E250 B0 division plate with full UT. Verify through-thickness properties.'
    sec=g['col_sec']['lateral']['1'];base=connections['column_base'][sec]
    # Resolved against 3,810 and 1,287 distinct concurrent N, Mz, My and V vectors
    # from the respective native R1 jobs; the 12.12 base checks include both capacity axes.
    n,t,proj,embed=(14,300,1150,5400) if u.name=='Flange' else (12,280,1000,4800)
    base=HR.ring_base(sec,base,d=64,n=n,t=t,proj=proj);a=base['anchors']
    a['pitch_mm']=math.floor(10*(min(base['B_mm'],base['L_mm'])-2*a['edge_mm'])/(n-1))/10
    a['embedment']={**a['embedment'],'L_mm':embed}
    connections['column_base'][sec]=base
    # R8 complete physical take-off includes the edge beams and packing beneath
    # the slab. Lower storeys reached 1.37 kPa, upper 1.11 and roof 0.64.
    cfg['extra_mass_floors']={int(k):(1.45 if int(k)<=6 else .72 if int(k)==12 else 1.19) for k in g['ebf_brace_sec']}
    cfg['column_imposed_load_reduction']=True
    for page,clause,match in [(9,'6.3.1',r'6\.3\.1'),(10,'6.3.3',r'6\.3\.3'),(15,'11.2 and 11.4.1',r'11\.4\.1'),
        (16,'11.4.2',r'11\.4\.2'),(21,'12.3.2.2 and 12.3.3',r'12\.3\.2\.2'),(22,'12.3.4.4 and 12.3.4.5',r'12\.3\.4\.4')]:
        ground.page('IS_18168_2023',match,'IS 18168, '+clause,pages=[page],inputs={'clear_link_mm':900,'system':'EBF','zone':'V'})
    FB.attach_gold(cfg,g)
    if builder:cfg['custom_build']=builder
