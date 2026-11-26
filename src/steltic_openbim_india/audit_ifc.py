"""Read the saved STEP file independently of the writer. All distances below are mm."""
from functools import lru_cache
from collections import Counter
import json
import math

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as element
import ifcopenshell.util.placement as placement
import ifcopenshell.util.unit as units
import ifcopenshell.validate
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .audit_gaps import measure
from .audit_features import check as check_member_openings, mesh as feature_mesh
from .bolt_fit import assembly as measure_bolts


MM_TOL = 0.02


def near(a, b, tolerance=MM_TOL):
    return np.allclose(a, b, atol=tolerance, rtol=0)


def world(matrix, pt):
    values = list(pt)
    return (matrix @ np.array((values + [0.] * (3 - len(values)) + [1.])))[:3]


def areas(profile):
    boundary = [pt.Coordinates for pt in profile.OuterCurve.Points]
    holes = [[pt.Coordinates for pt in ring.Points] for ring in getattr(profile, "InnerCurves", ())]
    return Polygon(boundary, holes)


def check_section(profiles, name, spec, expect, key):
    expect(all(p.ProfileName == name for p in profiles), "profile identifier", key)
    dims = spec.get("dimensions_mm", {})
    if len(profiles)==1 and profiles[0].is_a("IfcIShapeProfileDef") and spec["family"]=="I" and "contours_mm" not in spec:
        p = profiles[0]
        expect(near([p.OverallDepth,p.OverallWidth,p.WebThickness,p.FlangeThickness],
                    [dims["d"],dims["b"],dims["tw"],dims["tf"]]), "I flange and web geometry",key)
        expect(near([p.FilletRadius or 0,p.FlangeEdgeRadius or 0,p.FlangeSlope or 0],
                    [dims.get("r",dims.get("r1",0)),dims.get("r2",0),math.radians(dims.get("slope_deg",0))], 1e-6),
               "I flange radii and slope",key)
        expect(p.Position is None or near(placement.get_axis2placement(p.Position),np.identity(4)), "profile origin",key)
        return
    if spec["family"] in ("ROD", "CHS") and "contours_mm" not in spec:
        profile = profiles[0]
        diameter = dims.get("diameter", dims.get("d"))
        expect(len(profiles) == 1 and near(2 * profile.Radius, diameter), "section outside diameter", key)
        if spec["family"] == "CHS":
            expect(near(profile.WallThickness, dims["t"]), "tube wall thickness", key)
        return
    shapes = [areas(p) for p in profiles]
    expect(all(shape.is_valid and shape.area > 0 for shape in shapes), "valid profile loops", key)
    if "contours_mm" in spec:
        holes = spec.get("holes_mm", [[] for _ in spec["contours_mm"]])
        expected = [Polygon(shell, inner) for shell, inner in zip(spec["contours_mm"], holes)]
        expect(len(expected) == len(shapes) and all(a.hausdorff_distance(b) <= MM_TOL and
               a.symmetric_difference(b).area <= max(0.01, a.length * 1e-6)
               for a, b in zip(shapes, expected)), "section components and voids", key)
        return
    profile = unary_union(shapes)
    x0, y0, x1, y1 = profile.bounds
    depth = dims.get("d", dims.get("t"))
    expect(near(y1 - y0, depth), "profile depth", key)
    b = dims["b"]
    web = dims.get("tw", dims.get("t"))
    family = spec["family"]
    width = (2 * b - web) if family == "Z" else b
    expect(near(x1 - x0, width), "profile width", key)
    if web is None or family == "PLATE":
        return
    web_cut = LineString([(x0 - 10, (y0 + y1)/2), (x1 + 10, (y0 + y1)/2)])
    expect(near(web_cut.intersection(profile).length, web * (2 if family == "RHS" else 1)), "web thickness", key)
    # IS 808 flanges with a declared slope give their nominal thickness at b/4.
    xf = x1 - b / 4
    if family == "Z":
        xf = x1 - b / 3
    cut = LineString([(xf, y0 - 10), (xf, y1 + 10)])
    flange = dims.get("tf", dims.get("t"))
    if flange:
        layers = 1 if family in ("L", "Z") else 2
        expect(near(cut.intersection(profile).length, flange * layers), "flange thickness", key)
    if family in ("C","Z") and dims.get("lip", 0):
        # A reversed or missing lip can have the same outer envelope.
        top_toe = LineString([(x1-web*.5, y0-1), (x1-web*.5, y1+1)]).intersection(profile)
        bottom_x = x1-web*.5 if family == "C" else x0+web*.5
        bottom_toe = LineString([(bottom_x,y0-1),(bottom_x,y1+1)]).intersection(profile)
        expect(top_toe.bounds[3] > y1 - max(web, dims.get("r", 0)+web) and
               bottom_toe.bounds[1] < y0 + max(web, dims.get("r", 0)+web) and
               profile.covers(Point(x1-web*.5, y1-dims["lip"]+min(web/4, .1))) and
               profile.covers(Point(bottom_x, y0+dims["lip"]-min(web/4,.1))),
               "return lip geometry", key)


def audit_ifc(source, path, source_hash, expect):
    model = ifcopenshell.open(str(path))
    project, = model.by_type("IfcProject")
    expect(model.schema == "IFC4" and math.isclose(units.calculate_unit_scale(model), .001), "IFC4 project in millimetres", "project")
    project_data = element.get_psets(project).get("Steltic_India_Source", {})
    expect(project_data.get("ProjectId") == source["project"]["id"] and project.Name == source["project"]["name"]
           and project_data.get("Module") == source["project"]["module"] and project_data.get("SourceSHA256") == source_hash,
           "IFC source identity", "project")
    for prop, value in [("Checks",source.get("checks", [])), ("DesignBasis",source["project"].get("design_basis",[])),
                        ("Assumptions",source.get("assumptions",[]))]:
        expect(json.loads(project_data.get(prop,"null")) == value, "IFC " + prop, "project")
    ids = [o.GlobalId for o in model.by_type("IfcRoot")]
    expect(len(set(ids)) == len(ids), "unique IFC GlobalIds", "project")
    del ids
    schema_log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, schema_log)
    errors = [x for x in schema_log.statements if x.get("level") == "error"]
    for error in errors:
        expect(False, "IFC schema", str(error.get("attribute") or error.get("type") or "") + " " + str(error.get("message"))[:150])

    @lru_cache(maxsize=8192)
    def matrix(place):
        if not place:
            return np.identity(4)
        return matrix(place.PlacementRelTo) @ placement.get_axis2placement(place.RelativePlacement)

    storeys = model.by_type("IfcBuildingStorey")
    expected_levels = {s["id"]:s["elevation_mm"] for s in source["levels"]}
    expect({s.Name for s in storeys}==set(expected_levels), "IFC storey inventory", "project")
    for s in storeys:
        h=expected_levels.get(s.Name)
        expect(h is not None and near(matrix(s.ObjectPlacement)[2,3],h) and near(s.Elevation,h), "storey elevation and placement", s.Name)
    declared_units={u["id"]:u for u in source.get("units",[])}
    if declared_units:
        buildings={b.Name:b for b in model.by_type("IfcBuilding")}
        expect(set(buildings)==set(declared_units),"independent building units","project")
        for key, unit in declared_units.items():
            expect(key in buildings and near(matrix(buildings[key].ObjectPlacement)[:3,3],unit["origin_mm"]),"unit placement",key)
    grids = model.by_type("IfcGrid")
    expect(len(grids) == 1, "IFC grid count", "project")
    for direction, expected in source["grids"].items():
        if direction not in ("x","y") or not grids:
            continue
        axes = grids[0].UAxes if direction == "x" else grids[0].VAxes
        axis_by_name = {a.AxisTag: a.AxisCurve for a in axes}
        expect(set(axis_by_name) == {a["id"] for a in expected}, "grid labels", direction)
        for line in expected:
            curve = axis_by_name.get(line["id"])
            expect(curve and curve.is_a("IfcPolyline") and all(near(world(matrix(grids[0].ObjectPlacement),p.Coordinates)[0 if direction=="x" else 1],line["coordinate_mm"]) for p in curve.Points),
                   "grid position", line["id"])

    parts = [p for c in source.get("connections",[]) for p in c.get("parts",[])]
    expected_tags = {r["id"] for r in [*source["members"], *source.get("panels", []), *source.get("connections", []), *parts]}
    entities = [e for e in model.by_type("IfcElement") if not e.is_a("IfcOpeningElement")]
    products = {e.Tag: e for e in entities}
    expect(set(products) == expected_tags and len(products) == len(entities), "exact IFC occurrence inventory", "project")
    settings = ifcopenshell.geom.settings()
    cached_shapes, checked_profiles = set(), set()
    gaps = json.loads(project_data.get("SeparationJoints","[]"))
    meshes, unit_solids, drilled_cache = {}, {}, {}
    unit_for = {r["id"]: r.get("unit") for r in [*source["members"], *source.get("panels",[])]}
    for joint in source.get("connections",[]):
        unit_for.update({p["id"]:joint.get("unit") for p in joint.get("parts",[])})
    def read_product(row):
        key = row["id"]
        obj = products.get(key)
        if not obj:
            expect(False,"missing product",key)
            return None
        props = element.get_psets(obj).get("Steltic_India_Source", {})
        expect(obj.Name == key and props.get("SourceId") == key and json.loads(props.get("CheckIds","null")) == row.get("checks", []),
               "occurrence identity and calculation links",key)
        if declared_units and row.get("unit"):
            parent=element.get_container(obj,ifc_class="IfcBuilding")
            expect(parent is not None and parent.Name==row["unit"], "product unit containment",key)
        if "material" in row:
            material = element.get_material(obj)
            spec = source["materials"][row["material"]]
            expect(material and material.Name == row["material"] and material.Description == f"{spec['standard']} | {spec['grade']}"
                   and props.get("Grade") == spec["grade"] and props.get("Standard") == spec["standard"]
                   and props.get("FyMPa") == spec.get("fy_mpa"), "material and grade", key)
        body = next((r for r in (obj.Representation.Representations if obj.Representation else ()) if r.RepresentationIdentifier=="Body"), None)
        if body and body.id() not in cached_shapes:
            cached_shapes.add(body.id())
            try:
                shape = ifcopenshell.geom.create_shape(settings, body)
                target = getattr(shape, "geometry", shape)
                expect(len(target.verts) >= 12 and len(target.faces) >= 12 and np.isfinite(target.verts).all(), "independent solid tessellation",key)
                if gaps:
                    meshes[body.id()] = (np.asarray(target.verts).reshape(-1,3) * 1000,
                                         np.asarray(target.faces).reshape(-1,3))
            except (ValueError,RuntimeError,TypeError) as error:
                expect(False, "independent solid tessellation", f"{key}: {error}")
        if gaps and body and body.id() in meshes:
            local, triangles = feature_mesh(settings,obj) if row.get("member_voids") else meshes[body.id()]
            loc = matrix(obj.ObjectPlacement)
            vertices = local @ loc[:3,:3].T + loc[:3,3]
            unit_solids.setdefault(unit_for.get(key), []).append((key,vertices,triangles))
        return obj, props, body

    def sweep(item, obj, row, key):
        trans = matrix(obj.ObjectPlacement) @ placement.get_axis2placement(item.Position)
        direction = np.array(item.ExtrudedDirection.DirectionRatios)
        direction = direction / np.linalg.norm(direction)
        expect(near(trans[:3,3],row["start"]) and near(world(trans,direction*item.Depth),row["end"]), "physical solid endpoints",key)
        if row.get("ref_direction"):
            vec = np.asarray(row["ref_direction"], dtype=float)
            vec -= trans[:3,2] * np.dot(vec, trans[:3,2])
            expect(near(trans[:3,0], vec / np.linalg.norm(vec), 1e-6), "section rotation", key)
        return trans

    footprints, column_points, axis_tops = {}, {}, {}
    for row in source["members"]:
        key = row["id"]
        read = read_product(row)
        if read is None:
            continue
        obj, props, body = read
        role=str(obj.ObjectType or "").casefold()
        if any(word in role for word in ("brace","bracing","flange stay")):
            expect(obj.is_a()=="IfcMember","bracing occurrence classification",key)
        expected_level = row.get("level")
        if not expected_level:
            z = min(row["start"][2],row["end"][2])
            ordered = sorted(source["levels"],key=lambda s:s["elevation_mm"])
            expected_level = next((s["id"] for s in reversed(ordered) if s["elevation_mm"] <= z + .01),ordered[0]["id"])
        container = element.get_container(obj)
        expect(container and container.Name == expected_level, "member storey",key)
        expect(props.get("Profile") == row["profile"] and props.get("Role") == row["role"] and obj.ObjectType == row["role"], "member schedule",key)
        axis_rep = next((r for r in obj.Representation.Representations if r.RepresentationIdentifier == "Axis"),None) if obj.Representation else None
        if axis_rep and len(axis_rep.Items)==1 and axis_rep.Items[0].is_a("IfcPolyline"):
            points = [world(matrix(obj.ObjectPlacement),p.Coordinates) for p in axis_rep.Items[0].Points]
            expect(len(points)==2 and near(points,[row["start"],row["end"]]), "actual IFC axis",key)
            owner = row.get("unit","Main")
            axis_tops[owner] = max(axis_tops.get(owner,float("-inf")),*(p[2] for p in points))
            if obj.is_a("IfcColumn") and "column" in role:
                column_points.setdefault(owner,[]).extend(points)
        else:
            expect(False,"missing axis",key)
        if not body:
            expect(False,"missing member body",key)
            continue
        if row.get("member_voids") or obj.HasOpenings:
            check_member_openings(row,obj,body,settings,matrix,expect,drilled_cache)
        end_a,end_b=np.asarray(row["start"],dtype=float),np.asarray(row["end"],dtype=float)
        direction=(end_b-end_a)/np.linalg.norm(end_b-end_a)
        d0,d1=row.get("end_cutbacks_mm",(0.,0.))
        actual_start,actual_end=end_a+d0*direction,end_b-d1*direction
        if all(solid.is_a("IfcPolygonalFaceSet") for solid in body.Items):
            # A tapered arbitrary profile is represented as a capped loft. Compare
            # the actual two cap polygons (including holes), not an axis or label.
            a,b = actual_start,actual_end
            length=float(np.linalg.norm(b-a))
            trans=matrix(obj.ObjectPlacement)
            expect(near(trans[:3,3],a) and near(world(trans,[0,0,length]),b), "loft endpoints",key)
            for z,profile_key in [(0.,row["profile"]), (length,row.get("end_profile",row["profile"]))]:
                cap_rings=[]
                for solid in body.Items:
                    points=np.array(solid.Coordinates.CoordList)
                    for face in solid.Faces:
                        coords=points[np.array(face.CoordIndex)-1]
                        if near(coords[:,2],z):
                            holes=[points[np.array(v)-1][:,:2] for v in getattr(face,"InnerCoordIndices",())]
                            cap_rings.append(Polygon(coords[:,:2],holes))
                expect(bool(cap_rings),"loft cap exists",key)
                if cap_rings:
                    actual=unary_union(cap_rings)
                    spec=source["profiles"][profile_key]
                    if "contours_mm" in spec:
                        expected=unary_union([Polygon(shell,inner) for shell,inner in zip(spec["contours_mm"],spec.get("holes_mm",[[] for v in spec["contours_mm"]]))])
                        expect(actual.hausdorff_distance(expected)<=MM_TOL and actual.symmetric_difference(expected).area<max(.01,expected.length*1e-6),"loft section and voids",key)
                    else:
                        dims=spec["dimensions_mm"]
                        x0,y0,x1,y1=actual.bounds
                        w=dims.get("b",dims.get("diameter"))
                        if spec["family"]=="Z":
                            w=2*w-dims.get("tw",dims.get("t"))
                        expect(near([x1-x0,y1-y0],[w,dims.get("d",dims.get("t",dims.get("diameter")))]),"loft end dimensions",key)
            continue
        for solid in body.Items:
            sweep(solid,obj,dict(row,start=actual_start,end=actual_end) if d0 or d1 else row,key)
        ends = [("SweptArea",row["profile"])]
        if row.get("end_profile", row["profile"]) != row["profile"]:
            ends.append(("EndSweptArea",row["end_profile"]))
        else:
            expect(all(not item.is_a("IfcExtrudedAreaSolidTapered") for item in body.Items), "prismatic selection",key)
        for attr, name in ends:
            profiles = [getattr(v,attr,None) for v in body.Items]
            if any(p is None for p in profiles):
                expect(False, "taper profile missing",key)
                continue
            token = (name, tuple(p.id() for p in profiles))
            if token not in checked_profiles:
                checked_profiles.add(token)
                check_section(profiles, name, source["profiles"][name], expect, key)

    def check_panel(row, building_surface=False):
        key = row["id"]
        read = read_product(row)
        if read is None:
            return
        obj, _, body = read
        if not body or len(body.Items) != 1:
            expect(False, "plate body count",key)
            return
        solid = body.Items[0]
        mat = matrix(obj.ObjectPlacement) @ placement.get_axis2placement(solid.Position)
        inv = np.linalg.inv(mat)
        def local(ring):
            pts = [world(inv, pt) for pt in ring]
            expect(all(abs(v[2]) < MM_TOL for v in pts), "plate boundary plane", key)
            return [p[:2] for p in pts]
        required = Polygon(local(row["outline"]), [local(h) for h in row.get("openings",[])])
        actual = areas(solid.SweptArea)
        role = str(obj.ObjectType or "").lower()
        if building_surface and ("roof" in role or "floor" in role or role=="amenity deck") and not any(t in role for t in ("airlock","canopy")):
            unit = row.get("unit","Main")
            ring = [world(mat,[x,y,0.]) for x,y in actual.exterior.coords]
            holes = [[world(mat,[x,y,0.])[:2] for x,y in inner.coords] for inner in actual.interiors]
            projection = Polygon([p[:2] for p in ring], holes)
            if projection.area > 1:
                z = [p[2] for p in ring]
                footprints.setdefault(unit,[]).append((role,projection, min(z), max(z)))
        expect(actual.symmetric_difference(required).area < max(.01,required.length*1e-6) and near(solid.Depth,row["thickness_mm"]), "plate outline, thickness and voids", key)
        relations = tuple(getattr(obj,"HasOpenings",()))
        openings = {e.Name:e for e in (r.RelatedOpeningElement for r in relations)}
        expect(len(relations)==len(openings)==len(row.get("openings",[])), "hosted opening count",key)
        for index, opening in enumerate(row.get("openings",[]),1):
            occurrence = openings.get(f"{key}/opening/{index}")
            if occurrence is None:
                expect(False, "opening identity", key)
                continue
            item = occurrence.Representation.Representations[0].Items[0]
            hole_matrix = matrix(occurrence.ObjectPlacement) @ placement.get_axis2placement(item.Position)
            boundary = [world(inv,world(hole_matrix,pt.Coordinates))[:2] for pt in item.SweptArea.OuterCurve.Points]
            expect(Polygon(boundary).symmetric_difference(Polygon(local(opening))).area < max(.01,required.length*1e-6) and near(item.Depth,row["thickness_mm"]), "opening body and location",key)
        return mat[:3,3],mat[:3,:3].T,actual,solid.Depth

    for panel in source.get("panels",[]):
        check_panel(panel, building_surface=True)
    horizontal_plates=[]
    fit_counts=Counter()
    fit_issues=[]
    for c in source.get("connections",[]):
        key = c["id"]
        read = read_product(c)
        if read is None:
            continue
        obj, props, _ = read
        expect(obj.is_a("IfcElementAssembly") and near(matrix(obj.ObjectPlacement)[:3,3],c["at"]), "connection workpoint",key)
        expect({r.RelatingElement.Tag for r in obj.ConnectedFrom} == set(c["members"]), "connection receiver identities",key)
        expect({p.Tag for p in element.get_parts(obj)} == {p["id"] for p in c.get("parts",[])}, "connection part ownership",key)
        plates,bolts=[],[]
        for part in c.get("parts",[]):
            if part["kind"] == "plate":
                frame=check_panel(part)
                if frame is not None:
                    plates.append((part["id"],frame))
                if len(declared_units)>1 and part["id"] in products:
                    plate=products[part["id"]]
                    solid=plate.Representation.Representations[0].Items[0]
                    transform=matrix(plate.ObjectPlacement) @ placement.get_axis2placement(solid.Position)
                    vec=transform[:3,:3] @ np.asarray(solid.ExtrudedDirection.DirectionRatios)
                    if near(abs(vec[2]),1,1e-8):
                        area=solid.SweptArea
                        def xy(ring):
                            return [world(transform,p.Coordinates)[:2] for p in ring.Points]
                        poly=Polygon(xy(area.OuterCurve),[xy(r) for r in getattr(area,"InnerCurves",())])
                        z0=transform[2,3]
                        z1=z0+solid.Depth*vec[2]
                        horizontal_plates.append((c.get("unit"),part["id"],poly,min(z0,z1),max(z0,z1)))
                continue
            part_read = read_product(part)
            if not part_read:
                continue
            product, metadata, body = part_read
            solid = body.Items[0]
            trans=sweep(solid,product,part,part["id"])
            if part["kind"] == "bolt":
                expect(near(solid.SweptArea.Radius*2,part["diameter_mm"]), "bolt diameter",part["id"])
                tip=world(trans,np.array(solid.ExtrudedDirection.DirectionRatios)*solid.Depth)
                bolts.append((product.Tag,trans[:3,3],tip,solid.SweptArea.Radius*2))
            elif part.get("weld_type")=="cjp":
                half_y=part["throat_mm"]/2
                half_x=part.get("width_mm",part["throat_mm"])/2
                expected=Polygon([(-half_x,-half_y),(half_x,-half_y),(half_x,half_y),(-half_x,half_y)])
                expect(areas(solid.SweptArea).symmetric_difference(expected).area<.01,"CJP effective groove section",part["id"])
                expect(metadata.get("WeldType")=="CJP" and metadata.get("EffectiveThroatMm")==2*half_y and
                       metadata.get("EffectiveWidthMm")==2*half_x,"CJP effective groove properties",part["id"])
            else:
                expected = Polygon([(0,0),(part["leg_mm"],0),(0,part["leg_mm"])])
                expect(areas(solid.SweptArea).symmetric_difference(expected).area < .01, "fillet weld size",part["id"])
        hits,errors_fit=measure_bolts(plates,bolts)
        fit_counts.update(hits)
        fit_issues.extend(dict(connection=key,**issue) for issue in errors_fit)
    overlaps=[]
    if horizontal_plates:
        tree=STRtree([p[2] for p in horizontal_plates])
        for i,(unit,key,poly,low,high) in enumerate(horizontal_plates):
            for j in tree.query(poly,predicate="intersects"):
                other,tag,shape,z0,z1=horizontal_plates[j]
                if j<=i or other==unit:
                    continue
                thickness=min(z1,high)-max(z0,low)
                if thickness>MM_TOL:
                    overlap=poly.intersection(shape)
                    volume=overlap.area*thickness
                    if volume>1.0:
                        overlaps.append({"units":[unit,other],"plates":[key,tag],"volume_mm3":round(volume,3),
                                         "xy_bounds_mm":list(overlap.bounds),"overlap_depth_mm":round(thickness,4)})
    declared_clashes = json.loads(project_data.get("InterunitPlateClashes","[]"))
    measured_fit={"status":"fail" if fit_issues else "pass","shaft_plate_pairs":fit_counts["shaft_plate_pairs"],
                  "clear_pairs":fit_counts["clear_pairs"],"interferences":fit_issues}
    declared_fit=json.loads(project_data.get("BoltPlateFit","{}"))
    expect(measured_fit==declared_fit,"bolt and plate interference readback","project")
    declared_volumes = {tuple(sorted(r["occurrences"])):r["overlap_volume_mm3"] for r in declared_clashes}
    horizontal_ids = {r[1] for r in horizontal_plates}
    measured_volumes = {tuple(sorted(r["plates"])):r["volume_mm3"] for r in overlaps}
    expected_horizontal = {pair:v for pair,v in declared_volumes.items() if all(k in horizontal_ids for k in pair)}
    expect(set(expected_horizontal)==set(measured_volumes) and all(
        math.isclose(expected_horizontal[k],v,abs_tol=.01,rel_tol=1e-6) for k,v in measured_volumes.items() if k in expected_horizontal),
        "reported horizontal plate intersections against IFC solids", "project")
    dimensions = {}
    for unit, top in axis_tops.items():
        panels = footprints.get(unit,[])
        roof_faces=[(p,z0,z1) for role,p,z0,z1 in panels if "roof" in role or role=="amenity deck"]
        roof=[p for p,_,_ in roof_faces]
        columns = np.asarray(column_points.get(unit,[]))
        floors = {}
        for role,poly,z0,z1 in panels:
            if "floor" in role and abs(z1-z0)<1:
                floors.setdefault(round(z0),[]).append(poly)
        roof_union=unary_union(roof)
        widths={}
        if not roof_union.is_empty:
            xmin,ymin,xmax,ymax=roof_union.bounds
            for station in (.125,.5,.875):
                y=ymin+station*(ymax-ymin)
                section=roof_union.intersection(LineString([(xmin-1,y),(xmax+1,y)]))
                spans=sorted((line.bounds[0],line.bounds[2]) for line in
                             getattr(section,"geoms",(section,)) if line.geom_type=="LineString" and line.length>.02)
                joined=[]
                for start,end in spans:
                    if joined and start<=joined[-1][1]+.02:
                        joined[-1][1]=max(joined[-1][1],end)
                    else:
                        joined.append([start,end])
                widths[str(station)]={"segments":len(joined),"total_m":round(sum(b-a for a,b in joined)/1000,3)}
        dimensions[unit] = {
            "column_spans_mm": (columns.max(axis=0)-columns.min(axis=0)).round(3).tolist() if len(columns) else [],
            "maximum_steel_workline_z_mm": round(float(top),3),
            "roof_plan_union_m2": round(roof_union.area/1e6,3) if roof else None,
            "roof_transverse_sections_by_y_fraction":widths,
            "pitched_roof_panels": sum(1 for _,z0,z1 in roof_faces if abs(z1-z0)>10),
            "flat_roof_panels": sum(1 for _,z0,z1 in roof_faces if abs(z1-z0)<=10),
            "flat_roof_plan_union_m2":round(unary_union([p for p,z0,z1 in roof_faces if abs(z1-z0)<=10]).area/1e6,3),
            "pitched_roof_plan_union_m2":round(unary_union([p for p,z0,z1 in roof_faces if abs(z1-z0)>10]).area/1e6,3),
            "floor_net_plan_m2_by_elevation_mm": {str(z):round(unary_union(polys).area/1e6,3) for z,polys in sorted(floors.items())}}
    return dict(schema=model.schema, length_unit="mm", members=len(source["members"]), panels=len(source.get("panels",[])),
                member_voids=sum(len(m.get("member_voids",[])) for m in source["members"]),
                cutback_members=sum(any(m.get("end_cutbacks_mm",[])) for m in source["members"]),
                assemblies=len(source.get("connections",[])), parts=len(parts), storeys=len(storeys),
                tessellated_representations=len(cached_shapes), occurrence_placements=len(entities), schema_errors=len(errors),
                interunit_horizontal_plate_overlaps=overlaps, declared_design_status=project_data.get("DesignStatus"),
                separation_joints=gaps, independently_measured_gaps=measure(gaps,unit_solids,expect), declared_plate_clashes=declared_clashes,
                building_geometry=dimensions,bolt_plate_fit=measured_fit)
