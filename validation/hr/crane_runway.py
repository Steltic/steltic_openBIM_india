"""Visakhapatnam runway, with the rail datum at the running surface."""
import hr_autosize as HR
import sections as S


def design(cfg):
    crane=cfg['crane']
    girder='NPB750X270X202.49'
    cap='MC300'
    section='WPB400X400X191.11'
    column=cfg['gold']['col_sec']['lateral'].get('default') or cfg['gold']['col_sec']['lateral']['1']
    crane.update(gantry_section=girder,gantry_grade='E250B0',gantry_LLT_mm=4500,rail_foot_mm=100,
                 rail_weight_N_per_mm=.30+S.props(cap)['A']*7.85e-5,cap_section=cap,
                 rail_section_height_mm=100,top_flange_cap=HR.capped_flange(girder,cap))
    crane['bracket']=dict(section=section,grade='E250B0',column_section=column,
                         projection_mm=crane['bracket_eccentricity_mm']-S.props(column)['d']/2,
                         rail_height_mm=100+S.props(cap)['tw']+S.props(girder)['d'],dead_N=25400,
                         weld_leg_mm=12,electrode_fu_MPa=410,gamma_mw=1.25,
                         column_stiffeners={'b_mm':120,'t_mm':25,'n':2,'fy_MPa':240})


def draw(model):
    u=model.u
    cr=model.cfg['crane'];g=cr['gantry_section']; cap=cr['cap_section']; br=cr['bracket']['section']
    rail=cr['rail_height_mm']; top=rail-cr['rail_section_height_mm']
    gdepth=S.props(g)['d']; girder=top-S.props(cap)['tw']-gdepth/2
    bracket=girder-gdepth/2-S.props(br)['d']/2
    cap_z=top-S.props(cap)['bf']/2
    w=u.nx*u.sx*1000;sy=u.sy*1000
    rail_id='CRANE-RAIL-TRIAL'
    # Shop profile is pending. The coordinate reference and trial polygon are
    # recorded separately from the prescribed girder and IS 808 cap channel.
    outline=[[-50,-50],[50,-50],[50,-38],[7,-33],[7,22],[25,25],[25,50],
             [-25,50],[-25,25],[-7,22],[-7,-33],[-50,-38]]
    model.profile_lookup[rail_id]={'family':'POLYGON','contours_mm':[outline]}
    model.materials['RAIL']={'grade':'Vendor rail, trial section','standard':'Owner/vendor rail profile to be confirmed'}
    for side,x in enumerate((cr['bracket_eccentricity_mm'],w-cr['bracket_eccentricity_mm'])):
        for j in range(u.ny):
            for lab,role,z,roll,code,material in [(g,'gantry girder',girder,None,'GAN','E250B0'),
                    (cap,'gantry cap channel',cap_z,[0,0,-1],'GANC','E250B0'),
                    (rail_id,'crane rail',rail-50,None,'RAIL','RAIL')]:
                model.member(role,lab,(x,j*sy,z),(x,(j+1)*sy,z),ref=roll,material=material,
                             mid=f'{code}-{side}-{j}',bind=False)
        for j in range(u.ny+1):
            face=x+(-1 if side==0 else 1)*cr['bracket']['projection_mm']
            model.member('crane bracket',br,(face,j*sy,bracket),(x,j*sy,bracket),material='E250B0',
                         mid=f'BRK-{side}-{j}',bind=False)
    model.data['assumptions'].append('Runway uses the specified cap channel on the selected girder. The 100 mm trial rail profile and connections for the 4.5 m lateral restraint require crane-supplier confirmation.')
