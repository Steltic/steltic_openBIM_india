"""Independent dimensional controls transcribed from the 36 active project briefs.

These are global column-grid spans, highest specified steel datum, and horizontal
roof areas. The latter catches a solid rectangle substituted for an irregular plan.
Numbers are metres and square metres. A range records unspecified layout dimensions.
"""

HR = {
    1:(30,75,11.5,2250), 2:(96,108,15.4,10368), 3:(24,60,11.2,1440), 4:(30,90,12,2700),
    5:(30,75,11.5,2250), 6:(18,32,9,576), 7:(21,72,12.55,1512), 8:(24,36,9.2,864),
    9:(36,60,11,1800), 10:(90,60,10,5400),
    11:{"Office":(30,22.5,15,675), "Workshop":(30,15,10.8,450)},
    12:{"Classroom":(25.5,17,10.8,433.5), "Link":(17,17,7.2,289), "Gym":(17,17,8,289)},
    13:(30,24,18,720), 14:(37.5,30,28.8,1125), 15:(63,45,32.1,2106), 16:(30,30,31.5,900),
    17:(51,34,36.9,1734), 18:(36,27,39.6,972),
    19:{"Flange":(51,17,39.4,867), "Stem":(17,17,39.4,289)},
    20:(27,18,59.8,486), 21:(18,36,8.75,648)
}
CFS = {
    1:(48,18,(6.01,10),864), 2:(76,21,9,1596), 3:(24,30,8.4,720),
    4:(30,36,(7.3,10),1008), 5:(49,31,(8.7,12),700), 6:(37,21,(12.9,15),777),
    7:(12,8,12,96), 8:(43,40,(11.86,17),966), 9:(52,20,(11.91,17),(790,1039.5)),
    10:(24,12,15,288), 11:(55,46,(14.61,20),1558), 12:(36,12,18.3,432), 13:(84,54,17.8,1800),
    14:(64,40,23,(900,2560)), 15:(46,46,23.3,1332)
}


def installed_measurements(model, *, floor_areas=False):
    """Measure structural worklines, soffits and actual cover panels on each reopened building."""
    import ifcopenshell.geom
    import ifcopenshell.util.placement as placement
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    settings=ifcopenshell.geom.settings()
    meshes={}
    buildings=model.by_type("IfcBuilding")
    measured={}
    member_roles={"column","beam","truss top chord","rafter","gable rafter","canopy"}
    cover_roles={"roof sheeting", "rooflight", "pv array"}
    for building in buildings:
        key=building.Name if len(buildings)>1 else "Main"
        tops=[]
        ridge=[]
        undersides={"rafter":[],"canopy":[]}
        surfaces={k:[] for k in cover_roles}
        elevations=[]
        floors={}
        floor_heights={}
        storeys=[s for r in building.IsDecomposedBy for s in r.RelatedObjects if s.is_a("IfcBuildingStorey")]
        for storey in storeys:
            for obj in (o for r in storey.ContainsElements for o in r.RelatedElements):
                role=(obj.ObjectType or "").lower()
                roof_panel=obj.is_a("IfcRoof") or (obj.is_a("IfcSlab") and ("roof" in role or role=="amenity deck"))
                floor_panel=floor_areas and obj.is_a("IfcSlab") and "floor" in role
                if (role not in member_roles|cover_roles and not roof_panel and not floor_panel) or not obj.Representation:
                    continue
                reps={r.RepresentationIdentifier:r for r in obj.Representation.Representations}
                mat=placement.get_local_placement(obj.ObjectPlacement)
                if "Axis" in reps and role!="canopy":
                    z=[float((mat@[*p.Coordinates,1.])[2]) for p in reps["Axis"].Items[0].Points]
                    tops.extend(z)
                    if role in ("rafter","gable rafter"):
                        ridge.extend(z)
                if role in cover_roles or roof_panel or floor_panel:
                    for item in reps["Body"].Items:
                        transform=mat@placement.get_axis2placement(item.Position)
                        def ring(curve):
                            return np.asarray([(transform@[*p.Coordinates,0.,1.])[:3] for p in curve.Points])
                        area=item.SweptArea
                        exterior=ring(area.OuterCurve)
                        holes=[ring(r)[:,:2] for r in getattr(area,"InnerCurves",())]
                        footprint=Polygon(exterior[:,:2],holes)
                        dz=float(transform[2,:3]@item.ExtrudedDirection.DirectionRatios)*item.Depth
                        limits=[float(exterior[:,2].min()+min(0,dz)),float(exterior[:,2].max()+max(0,dz))]
                        if role in surfaces:
                            surfaces[role].append(footprint)
                        if roof_panel:
                            elevations.extend(limits)
                        if floor_panel:
                            datum=str(round(storey.Elevation))
                            floors.setdefault(datum,[]).append(footprint)
                            floor_heights.setdefault(datum,[]).extend(limits)
                if role not in ("rafter","gable rafter","canopy"):
                    continue
                body=reps["Body"]
                if body.id() not in meshes:
                    geometry=ifcopenshell.geom.create_shape(settings,body)
                    meshes[body.id()]=np.asarray(geometry.verts).reshape(-1,3)*1000.
                z=meshes[body.id()]@mat[2,:3]+mat[2,3]
                undersides["canopy" if role=="canopy" else "rafter"].append(float(z.min()))
        areas={k:unary_union(shapes) for k,shapes in surfaces.items()}
        measured[key]={"primary_axis_top_mm":max(tops,default=None),"primary_rafter_axis_apex_mm":max(ridge,default=None),
            "minimum_rafter_soffit_mm":min(undersides["rafter"],default=None),
            "minimum_canopy_beam_soffit_mm":min(undersides["canopy"],default=None),
            "outer_roof_z_range_mm":[min(elevations),max(elevations)] if elevations else None,
            "rooflight_plan_m2":areas["rooflight"].area/1e6, "solar_plan_m2":areas["pv array"].area/1e6,
            "solar_over_rooflight_m2":areas["pv array"].intersection(areas["rooflight"]).area/1e6,
            "floor_net_plan_m2_by_storey_datum_mm":{k:unary_union(polys).area/1e6 for k,polys in floors.items()},
            "floor_panel_z_ranges_by_storey_datum_mm":{k:[min(z),max(z)] for k,z in floor_heights.items()}}
    return measured


def run(family, number, measurements):
    requirements = (HR if family=="hr" else CFS)[number]
    expected = requirements if isinstance(requirements,dict) else {"Main":requirements}
    records = []
    def check(unit, label, observed, wanted, tolerance=.002):
        bounds = wanted if isinstance(wanted,tuple) else (wanted,wanted)
        ok = observed is not None and bounds[0]-tolerance <= observed <= bounds[1]+tolerance
        records.append({"unit":unit, "control":label, "required":wanted, "measured":observed, "pass":ok})
    check("project","independent unit count",len(measurements),len(expected),0)
    for unit,(width,length,top,area) in expected.items():
        model = measurements.get(unit,{})
        spans = model.get("column_spans_mm",[])
        for axis,name,target in [(0,"column span X (m)",width),(1,"column span Y (m)",length)]:
            check(unit,name,spans[axis]/1000 if spans else None,target)
        portal=family=="hr" and number in (1,2,3,4,5,7,8,9)
        datum="primary_rafter_axis_apex_mm" if portal else "primary_axis_top_mm"
        maximum=model.get(datum)
        check(unit,"primary rafter ridge workline (m)" if portal else "upper structural workline (m)",maximum/1000 if maximum is not None else None,top)
        if family=="hr" and number==2:
            check(unit,"minimum clear height under main rafters (mm)",model.get("minimum_rafter_soffit_mm"),(12000,13000),.1)
            check(unit,"minimum clear height under dock canopy steel (mm)",model.get("minimum_canopy_beam_soffit_mm"),(5500,6000),.1)
        check(unit,"union of roof projections (m²)",model.get("roof_plan_union_m2"),area,.1)
        if family=="hr" and number in (1,2,4,5):
            check(unit,"daylight sheets, 3% of plan (m²)",model.get("rooflight_plan_m2"),.03*area,.1)
        if family=="hr" and number==5:
            check(unit,"PV fields, 75% of plan (m²)",model.get("solar_plan_m2"),.75*area,.1)
        if (family=="hr" and number in (1,2,3,4,5,7,8,9,10,21)) or (family=="cfs" and number in (1,2,3,8,9,11)):
            check(unit,"pitched roof faces",model.get("pitched_roof_panels"),(1,10**6),0)
        if family=="cfs" and number==6:
            check(unit,"south walkout diaphragm, +3.0 m structural level (m²)",model.get("floor_net_plan_m2_by_storey_datum_mm",{}).get("3000"),388.5,.1)
        if family=="cfs" and number==11:
            check(unit,"accessible west amenity deck (m²)",model.get("flat_roof_plan_union_m2"),513,.1)
            check(unit,"north gabled wing (m²)",model.get("pitched_roof_plan_union_m2"),1045,.1)
        if family=="cfs" and number==13:
            sections=model.get("roof_transverse_sections_by_y_fraction",{})
            for station,target in (("0.125",46),("0.5",8),("0.875",46)):
                check(unit,f"wing or connecting corridor width at y/H={station} (m)",sections.get(station,{}).get("total_m"),target)
        if family=="cfs" and number==14:
            floors=model.get("floor_net_plan_m2_by_storey_datum_mm",{})
            check(unit,"full podium floor at +4.0 m (m²)",floors.get("4000"),2560,.1)
            upper=floors.get("11000")
            check(unit,"upper U floor and north courtyard at +11.0 m (m²)",upper,(900,2500),.1)
            sections=model.get("roof_transverse_sections_by_y_fraction",{})
            check(unit,"continuous south bar",sections.get("0.125",{}).get("segments"),1,0)
            check(unit,"two wings enclosing the north courtyard",sections.get("0.875",{}).get("segments"),2,0)
    observations={u:{k:v for k,v in r.items() if k in ("outer_roof_z_range_mm","minimum_rafter_soffit_mm","solar_over_rooflight_m2","floor_panel_z_ranges_by_storey_datum_mm") and v is not None and v!={}} for u,r in measurements.items()}
    return {"status":"pass" if all(r["pass"] for r in records) else "fail","controls":records,"observations":observations}
