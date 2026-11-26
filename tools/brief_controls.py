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


def installed_measurements(model, *, floor_areas=False, condenser_openings=False, shed_overhang=False, stepped_office=False):
    """Measure structural worklines, soffits and actual cover panels on each reopened building."""
    import ifcopenshell.geom
    import ifcopenshell.util.placement as placement
    import numpy as np
    from shapely.geometry import Polygon, box
    from shapely import set_precision
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
        solar_faces=[]
        roof_tops=[]
        elevations=[]
        floors={}
        floor_heights={}
        cold_roof=[]
        condenser_posts=[]
        column_xy=[]
        main_roof=[]
        stepped_panels={}
        storeys=[s for r in building.IsDecomposedBy for s in r.RelatedObjects if s.is_a("IfcBuildingStorey")]
        for storey in storeys:
            for obj in (o for r in storey.ContainsElements for o in r.RelatedElements):
                role=(obj.ObjectType or "").lower()
                if condenser_openings and role=="platform post":
                    transform=placement.get_local_placement(obj.ObjectPlacement)
                    axis=next(r for r in obj.Representation.Representations if r.RepresentationIdentifier=="Axis")
                    point=axis.Items[0].Points[0]
                    condenser_posts.append((transform@[*point.Coordinates,1.])[:2])
                roof_panel=obj.is_a("IfcRoof") or (obj.is_a("IfcSlab") and ("roof" in role or role=="amenity deck"))
                floor_panel=floor_areas and obj.is_a("IfcSlab") and "floor" in role
                primary_column=shed_overhang and obj.is_a("IfcColumn") and "column" in role
                if (role not in member_roles|cover_roles and not primary_column and not roof_panel and not floor_panel) or not obj.Representation:
                    continue
                reps={r.RepresentationIdentifier:r for r in obj.Representation.Representations}
                mat=placement.get_local_placement(obj.ObjectPlacement)
                if primary_column:
                    column_xy.extend((mat@[*p.Coordinates,1.])[:2] for p in reps["Axis"].Items[0].Points)
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
                        if shed_overhang and roof_panel and "canopy" not in role:
                            main_roof.append(footprint)
                        if stepped_office and role=="roof deck":
                            stepped_panels.setdefault(round(storey.Elevation),[]).append(footprint)
                        if condenser_openings and role=="pitched roof":
                            cold_roof.append(set_precision(footprint,.01))
                        dz=float(transform[2,:3]@item.ExtrudedDirection.DirectionRatios)*item.Depth
                        limits=[float(exterior[:,2].min()+min(0,dz)),float(exterior[:,2].max()+max(0,dz))]
                        if role in surfaces:
                            surfaces[role].append(footprint)
                        if role in ("pv array","roof sheeting"):
                            normal=np.cross(exterior[1]-exterior[0],exterior[2]-exterior[0])
                            if np.linalg.norm(normal)<1e-6:
                                normal=transform[:3,2].copy()
                            if normal[2]<0:normal=-normal
                            normal/=np.linalg.norm(normal)
                            extrusion=transform[:3,:3]@np.asarray(item.ExtrudedDirection.DirectionRatios)*item.Depth
                            lift=float(normal@extrusion)
                            face=exterior[0]+(extrusion if (role=="pv array" and lift<0) or (role=="roof sheeting" and lift>0) else 0.)
                            (solar_faces if role=="pv array" else roof_tops).append((footprint,face,normal))
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
        if shed_overhang and main_roof and column_xy:
            bounds=np.asarray(column_xy)
            x0,y0=bounds.min(axis=0)
            x1,y1=bounds.max(axis=0)
            installed=unary_union(main_roof)
            ax,ay,bx,by=installed.bounds
            measured[key]["weathered_roof"]={"in_grid_m2":installed.intersection(box(x0,y0,x1,y1)).area/1e6,
                "installed_m2":installed.area/1e6,"extensions_mm":{"west":x0-ax,"east":bx-x1,"south":y0-ay,"north":by-y1}}
        if stepped_office:
            # Pune's five lower terrace edge columns are 500 mm boxes. The sheet
            # set-out allows 12 mm on each face. Both end notches meet a corner.
            terrace=box(0,0,36000,27000)
            head=box(0,27000,63000,45000)
            lower=unary_union(stepped_panels.get(20400,[]))
            upper=unary_union(stepped_panels.get(32100,[]))
            omitted=terrace.difference(lower)
            cuts=[terrace.intersection(box(x-262,27000-262,x+262,27000+262)) for x in range(0,36001,9000)]
            measured[key]["stepped_roof"]={"lower_net_m2":lower.area/1e6,"upper_net_m2":upper.area/1e6,
                "ledge_notches_mm2":[omitted.intersection(c).area for c in cuts],
                "unexplained_lower_difference_mm2":terrace.difference(unary_union(cuts)).symmetric_difference(lower).area,
                "upper_footprint_difference_mm2":head.symmetric_difference(upper).area}
        if condenser_openings:
            from shapely.geometry import Point
            roof=unary_union(cold_roof)
            islands=[roof] if roof.geom_type=="Polygon" else list(roof.geoms)
            holes=[Polygon(ring) for island in islands for ring in island.interiors]
            # Adjacent panels have complementary edge notches. The post penetrations
            # only become closed rings after unioning the installed roof faces.
            measured[key]["condenser_openings"]={
                "gross_m2":sum(Polygon(island.exterior).area for island in islands)/1e6,
                "net_m2":roof.area/1e6,
                "clear_openings":[{"width_mm":h.bounds[2]-h.bounds[0],"length_mm":h.bounds[3]-h.bounds[1],
                                  "area_mm2":h.area,"contained_posts":sum(h.contains(Point(p)) for p in condenser_posts)} for h in holes],
                "posts":len(condenser_posts),
            }
        if solar_faces and roof_tops:
            gaps=[]
            for solar,p,n in solar_faces:
                for roof,q,m in roof_tops:
                    overlap=solar.intersection(roof)
                    if overlap.area<=.01:continue
                    for x,y in overlap.convex_hull.exterior.coords:
                        z=p[2]-(n[0]*(x-p[0])+n[1]*(y-p[1]))/n[2]
                        gaps.append(float(m@(np.asarray([x,y,z])-q)))
            roof=areas["roof sheeting"].union(areas["rooflight"])
            x0,y0,x1,y1=roof.bounds
            centre=(x0+x1)/2;mid=(y0+y1)/2
            fields=[p.bounds for p,_,_ in solar_faces]
            eave=min(min(a-x0,x1-b) for a,_,b,_ in fields)
            ridge=min(max(0.,a-centre,centre-b) for a,_,b,_ in fields)
            lower=[d for _,c,_,d in fields if d<=mid];upper=[c for _,c,_,d in fields if c>=mid]
            cross=0. if not lower or not upper or any(c<mid<d for _,c,_,d in fields) else min(upper)-max(lower)
            measured[key].update(solar_standoff_min_mm=min(gaps,default=None),solar_standoff_max_mm=max(gaps,default=None),
                                 solar_eave_clear_mm=eave,solar_ridge_clear_mm=ridge,solar_cross_walkway_mm=cross)
    return measured


def run(family, number, measurements):
    requirements = (HR if family=="hr" else CFS)[number]
    expected = requirements if isinstance(requirements,dict) else {"Main":requirements}
    records = []
    def check(unit, label, observed, wanted, tolerance=.002):
        if isinstance(wanted,dict):
            ok=observed is not None and observed>=wanted["minimum"]-tolerance
        else:
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
            check(unit,"minimum clear height under main rafters (mm)",model.get("minimum_rafter_soffit_mm"),{"minimum":12000},.1)
            check(unit,"minimum clear height under dock canopy steel (mm)",model.get("minimum_canopy_beam_soffit_mm"),{"minimum":5500},.1)
        if family=="cfs" and number==2:
            condenser=model.get("condenser_openings",{})
            holes=condenser.get("clear_openings",[])
            check(unit,"full main roof footprint including service penetrations (m²)",condenser.get("gross_m2"),area,.1)
            check(unit,"main roof material after four 284 × 198 mm service cuts (m²)",model.get("roof_plan_union_m2"),area-4*.284*.198,.002)
            check(unit,"condenser posts",condenser.get("posts"),4,0)
            check(unit,"dedicated condenser penetrations",len(holes),4,0)
            for i,hole in enumerate(holes,1):
                for field,wanted,tolerance in (("width_mm",284,.02),("length_mm",198,.02),("area_mm2",284*198,3),("contained_posts",1,0)):
                    check(unit,f"condenser opening {i} {field}",hole[field],wanted,tolerance)
        elif family=="hr" and number==15:
            step=model["stepped_roof"]
            for i,actual in enumerate(step["ledge_notches_mm2"]):
                check(unit,f"terrace column clearance notch at X={9*i} m (mm²)",actual,262*262*(1 if i in (0,4) else 2),2.)
            check(unit,"5-storey terrace net of column clearances (m²)",step["lower_net_m2"],971.450848,.002)
            check(unit,"8-storey north bar roof (m²)",step["upper_net_m2"],1134.,.002)
            check(unit,"unexplained lower terrace footprint difference (mm²)",step["unexplained_lower_difference_mm2"],0,5.)
            check(unit,"upper roof footprint difference (mm²)",step["upper_footprint_difference_mm2"],0,5.)
            check(unit,"gross stepped roof footprint including five column clearances (m²)",model["roof_plan_union_m2"]+sum(step["ledge_notches_mm2"])/1e6,area,.002)
        elif family=="hr" and number in (6,7,8,9,10,21):
            weather=model.get("weathered_roof",{})
            check(unit,"main roof coverage inside the structural grid (m²)",weather.get("in_grid_m2"),area,.1)
            check(unit,"whole installed weathered roof, two independent IFC readers (m²)",weather.get("installed_m2"),model["roof_plan_union_m2"],.003)
            eaves={6:(("south","north"),450),7:(("west","east"),644),8:(("west","east"),617),
                   9:(("west","east"),692),10:(("south","north"),534.5),21:(("west","east"),590)}
            sides,extent=eaves[number]
            for side in sides:
                check(unit,f"{side} weathered eave beyond column grid (mm)",weather.get("extensions_mm",{}).get(side),extent,1.)
            gable={6:385,7:580,8:674,9:517,10:528,21:590}[number]
            for side in sorted({"west","east","south","north"}.difference(sides)):
                check(unit,f"{side} gable roof edge beyond end frame (mm)",weather.get("extensions_mm",{}).get(side),gable,1.)
        else:
            check(unit,"union of roof projections (m²)",model.get("roof_plan_union_m2"),area,.1)
        if family=="hr" and number in (1,2,4,5):
            check(unit,"daylight sheets, 3% of plan (m²)",model.get("rooflight_plan_m2"),.03*area,.1)
        if family=="hr" and number==5:
            check(unit,"PV fields, 75% of plan (m²)",model.get("solar_plan_m2"),.75*area,.1)
            check(unit,"PV overlap onto daylight sheets (m²)",model.get("solar_over_rooflight_m2"),0,.001)
            for label,field in (("minimum","solar_standoff_min_mm"),("maximum","solar_standoff_max_mm")):
                check(unit,f"{label} PV-to-sheet normal clearance (mm)",model.get(field),100,1.)
            for field,label,minimum in (("solar_eave_clear_mm","eave",600),("solar_ridge_clear_mm","ridge",600),("solar_cross_walkway_mm","mid-length",1000)):
                check(unit,f"clear {label} walkway (mm)",model.get(field),{"minimum":minimum},.1)
        if (family=="hr" and number in (1,2,3,4,5,7,8,9,10,21)) or (family=="cfs" and number in (1,2,3,8,9,11)):
            check(unit,"pitched roof faces",model.get("pitched_roof_panels"),{"minimum":1},0)
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
    observations={u:{k:v for k,v in r.items() if k in ("weathered_roof","outer_roof_z_range_mm","minimum_rafter_soffit_mm","solar_over_rooflight_m2","floor_panel_z_ranges_by_storey_datum_mm") and v is not None and v!={}} for u,r in measurements.items()}
    return {"status":"pass" if all(r["pass"] for r in records) else "fail","controls":records,"observations":observations}
