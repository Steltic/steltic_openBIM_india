"""Service-load drainage check on the two-way load path of Indore's 1:60 roof."""
import sections


def indore(cfg):
    span=15000.
    area=cfg['D_roof']+.075*9.81
    # Trial overflow crest 75 mm above the low gutter. For a blocked primary
    # outlet, conservatively put this head over the complete roof tributary.
    # Add both simply supported deformations at the same roof point.
    members=[(cfg['physical_secondaries']['roof joist'],2500.),(cfg['gold']['roof_planes'][0]['rafter_sec'],15000.)]
    deformation=[]
    for section,tributary in members:
        p=sections.props(section)
        w=area*tributary/1000+p['A']*7.85e-5
        deformation.append(5*w*span**4/(384*2e5*p['Ix']))
    cfg['roof_pitch_deg']=.9548412539
    cfg['ponding']={'span_mm':span,'roof_slope':1/60,'delta_mm':sum(deformation),'end_drainage':True}
    cfg['drainage_basis']={'overflow_head_mm':75,'water_load_kNm2':.075*9.81,'rafter_delta_mm':deformation[1],
          'joist_delta_mm':deformation[0],'reference':'IS 875 Part 4:2021, 4.4; service-load engineering screen',
          'assumption':'Free discharge at both eave gutters at the 75 mm overflow crest. Confirm scupper hydraulic capacity against local rainfall.'}


def shimla(cfg):
    span=12000.;head=.075*9.81
    p=sections.props(cfg['lean_beam']); secondary=sections.props(cfg['lean_purlin'])
    q=2.5+cfg['lower_roof_snow_drift']['s_wall_kNm2']+head
    # Full peak snow on the whole tributary is an upper envelope of the
    # actual 6 m linear drift taper applied at the structural analysis nodes.
    def deflection(sec,L,spacing):
        return 5*(q*spacing/1000+sec['A']*7.85e-5)*L**4/(384*2e5*sec['Ix'])
    girder=deflection(p,span,7500);purlin=deflection(secondary,7500,3000)
    cfg['ponding']={'span_mm':span,'roof_slope':1/80,'delta_mm':girder+purlin,'end_drainage':True}
    cfg['drainage_basis']={'roof':'lower lean-to','fall':1/80,'overflow_head_mm':75,'water_load_kNm2':head,
           'maximum_snow_drift_kNm2':cfg['lower_roof_snow_drift']['s_wall_kNm2'],'rafter_delta_mm':girder,
           'purlin_delta_mm':purlin,'reference':'IS 875 Part 4:2021, 4.4',
           'assumption':'Flat structural deck and tapered roofing to the outer gutter. Free overflow verified as a project assumption; confirm outlet capacity for the site.'}
