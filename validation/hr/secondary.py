"""Cold-formed secondary sizing, using the checked-in IS 811 catalogue and India IS 801 functions."""
from pathlib import Path
import sys


def select_z(section_root,span_mm,spacing_mm,gravity,uplift,fixed=None,*,details=False):
    steel=Path(section_root)/'steel_engine'
    # The IS 801 and IS 811 modules have distinct names in the CFS producer.
    if str(steel) not in sys.path: sys.path.append(str(steel))
    import is811_sections as catalog
    import is801_members as checks
    candidates=[catalog.props(fixed)] if fixed else sorted((catalog.props(n) for n in catalog.list_labels('LZ')),key=lambda p:p['A'])
    chosen=None
    for p in candidates:
        # Simply supported rods at thirds restrain the free flange. A roof/wall system
        # supplier must confirm fastener stiffness and lap capacities before release.
        w=gravity*spacing_mm/1000
        wu=uplift*spacing_mm/1000
        down=checks.bending_allowable(p,240,span_mm,compression_flange_restrained=True,
             zed_basis='Sheeting fixed to outer flange; verify sheet and screw translational restraint.')
        up=checks.bending_allowable(p,240,span_mm/3,wind_eq=True,
             zed_basis='Bridging at the third points restrains the inner flange under reversal.')
        if not down.get('Ma_Nmm') or not up.get('Ma_Nmm'): continue
        q=p['A']*7.85e-5
        shear=checks.web_shear_64(p,240,(w+q)*span_mm/2)
        cripple=checks.web_crippling_65(p,240,(w+q)*span_mm/2,100)
        ratios={'IS 801 gravity bending':(w+q)*span_mm**2/8/down['Ma_Nmm'],
                'IS 801 wind reversal bending':max(0,wu-q)*span_mm**2/8/up['Ma_Nmm'],
                'IS 800 Table 6 L/150 deflection':5*(w+q)*span_mm**4/(384*200000*p['Ix'])/(span_mm/150),
                'IS 801 web shear':shear.get('dc') or 0,'IS 801 web crippling':cripple.get('dc') or 0}
        dc=max(ratios.values())
        chosen=p,dc,ratios
        if dc<=.92: break
    if chosen is None: raise ValueError('No IS 811 lipped Z candidate produced a bending resistance')
    p,dc,ratios=chosen
    dims=dict(d=p['h'],b=p['b'],tw=p['t'],tf=p['t'],lip=p.get('c') or 0,r=p.get('Ri') or 0)
    result=p.get('label') or p['name'],dims,dc
    return (*result,ratios) if details else result
