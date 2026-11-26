"""IFC4 native extrusions, plates and assemblies in project millimetres.

Stable occurrence IDs, source properties, material grouping and real grid axes
adapt the exchange conventions of Steltic/steltic_openBIM (c3796b8).
"""

import json
import math
import uuid
from hashlib import sha256
from collections import defaultdict

import ifcopenshell
import ifcopenshell.api.context
from shapely import set_precision, to_wkb

from .geometry import dot, frame, member_body_ends, project, sub, weld_outline
from .model import at_level, design_status, panel_shape, unit_levels
from .profiles import polygon, section_polygons


Z = (0., 0., 1.)
X = (1., 0., 0.)
ORIGIN = (0., 0., 0.)


def member_class(role):
    name = role.casefold()
    if any(k in name for k in ("brace","bracing","flange stay")):
        return "IfcMember"
    if any(k in name for k in ("column", "stud", "post", "stanchion", "jamb", "stilt")):
        return "IfcColumn"
    if any(k in name for k in ("beam", "rafter", "girder", "joist", "lintel", "purlin", "girt", "header", "stringer")):
        return "IfcBeam"
    return "IfcMember"


class Exchange:
    def __init__(self, data, digest, gaps, clashes, bolt_fit):
        self.m = ifcopenshell.file(schema="IFC4")
        self.data = data
        self.job = data["project"]
        self.digest = digest
        self.gaps = gaps
        self.clashes = clashes
        self.bolt_fit = bolt_fit
        self.unit_origins = {u["id"]:u["origin_mm"] for u in data.get("units",[])} or {None:ORIGIN}
        self.levels = {u["id"]:unit_levels(data,u) for u in data.get("units",[])} or {None:data["levels"]}
        self.pts, self.directions, self.properties = {}, {}, {}
        self.profiles, self.bodies, self.axes = {}, {}, {}
        self.shapes, self.panel_bodies, self.fastener_bodies = {}, {}, {}
        self.used_reps = set()
        self.contained, self.materials = defaultdict(list), defaultdict(list)
        self.storeys, self.elements = {}, {}
        self.origin = self.basis(ORIGIN)
        self.vertical = self.direction(Z)

    def root(self, kind, key, **attrs):
        name = "steltic:india:" + self.job["id"] + ":" + key
        guid = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, name).hex)
        return self.m.create_entity(kind, GlobalId=guid, **attrs)

    def point(self, xyz):
        key = tuple(map(float, xyz))
        if key not in self.pts:
            self.pts[key] = self.m.create_entity("IfcCartesianPoint", Coordinates=key)
        return self.pts[key]

    def direction(self, vector):
        key = tuple(map(float, vector))
        if key not in self.directions:
            self.directions[key] = self.m.create_entity("IfcDirection", DirectionRatios=key)
        return self.directions[key]

    def basis(self, origin, x=X, z=Z):
        return self.m.create_entity("IfcAxis2Placement3D", Location=self.point(origin),
                                    Axis=self.direction(z), RefDirection=self.direction(x))

    def placement(self, origin=ORIGIN, x=X, z=Z, relative=None):
        return self.m.create_entity("IfcLocalPlacement", PlacementRelTo=relative, RelativePlacement=self.basis(origin, x, z))

    def aggregate(self, parent, objects, key):
        if objects:
            self.root("IfcRelAggregates", "aggregate:" + key, RelatingObject=parent, RelatedObjects=objects)

    def props(self, obj, key, values):
        fields = []
        for k, value in values.items():
            if value is None:
                continue
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            typ = "IfcBoolean" if isinstance(value, bool) else "IfcInteger" if isinstance(value, int) else "IfcReal" if isinstance(value, float) else "IfcText"
            token = (k, typ, value)
            if token not in self.properties:
                nominal = self.m.create_entity(typ, value)
                self.properties[token] = self.m.create_entity("IfcPropertySingleValue", Name=k, NominalValue=nominal)
            fields.append(self.properties[token])
        pset = self.root("IfcPropertySet", "pset:" + key, Name="Steltic_India_Source", HasProperties=fields)
        self.root("IfcRelDefinesByProperties", "defines:" + key, RelatedObjects=[obj], RelatingPropertyDefinition=pset)

    def curve(self, coords):
        return self.m.create_entity("IfcPolyline", Points=[self.point(p) for p in coords])

    def area(self, name, shape):
        outer = self.curve(shape.exterior.coords)
        options = dict(ProfileType="AREA", ProfileName=name, OuterCurve=outer)
        holes = [self.curve(h.coords) for h in shape.interiors]
        if holes:
            return self.m.create_entity("IfcArbitraryProfileDefWithVoids", InnerCurves=holes, **options)
        return self.m.create_entity("IfcArbitraryClosedProfileDef", **options)

    def source_profiles(self, name):
        if name in self.profiles:
            return self.profiles[name]
        source = self.data["profiles"][name]
        dims = source.get("dimensions_mm", {})
        family = source["family"]
        options = dict(ProfileType="AREA", ProfileName=name)
        if family == "I" and "contours_mm" not in source:
            attributes = {"OverallDepth": float(dims["d"]), "OverallWidth": float(dims["b"]),
                          "WebThickness": float(dims["tw"]), "FlangeThickness": float(dims["tf"])}
            for key, value in (("FilletRadius", dims.get("r", dims.get("r1"))), ("FlangeEdgeRadius", dims.get("r2"))):
                if value is not None:
                    attributes[key] = float(value)
            if "slope_deg" in dims:
                attributes["FlangeSlope"] = math.radians(dims["slope_deg"])
            values = [self.m.create_entity("IfcIShapeProfileDef", **options, **attributes)]
        elif family in {"CHS", "ROD"} and "contours_mm" not in source:
            radius = float(dims.get("diameter", dims.get("d"))) / 2
            if family == "CHS":
                profile = self.m.create_entity("IfcCircleHollowProfileDef", Radius=radius,
                                               WallThickness=float(dims["t"]), **options)
            else:
                profile = self.m.create_entity("IfcCircleProfileDef", Radius=radius, **options)
            values = [profile]
        else:
            values = [self.area(name, shape) for shape in section_polygons(source)]
        self.profiles[name] = values
        return values

    def sweep(self, name, profiles, length, end_profiles=None):
        items = []
        taper = end_profiles is not None
        for i, profile in enumerate(profiles):
            kwargs = dict(SweptArea=profile, Position=self.origin, ExtrudedDirection=self.vertical, Depth=float(length))
            if taper:
                items.append(self.m.create_entity("IfcExtrudedAreaSolidTapered", EndSweptArea=end_profiles[i], **kwargs))
            else:
                items.append(self.m.create_entity("IfcExtrudedAreaSolid", **kwargs))
        return self.m.create_entity("IfcShapeRepresentation", ContextOfItems=self.body_context,
                                    RepresentationIdentifier="Body", RepresentationType="AdvancedSweptSolid" if taper else "SweptSolid", Items=items)

    def member_body(self, start_profile, end_profile, length):
        key = (start_profile, end_profile, length)
        if key not in self.bodies:
            end = self.source_profiles(end_profile) if end_profile and end_profile != start_profile else None
            start = self.source_profiles(start_profile)
            if end and any(not (a.is_a("IfcParameterizedProfileDef") and a.is_a() == b.is_a()) for a,b in zip(start, end)):
                # IFC4 permits tapered sweeps only for matching parameterized or
                # derived sections. Loft authored polygon loops as closed face sets.
                a = section_polygons(self.data["profiles"][start_profile])
                b = section_polygons(self.data["profiles"][end_profile])
                solids = [self.loft(p, q, length) for p, q in zip(a, b)]
                self.bodies[key] = self.m.create_entity("IfcShapeRepresentation", ContextOfItems=self.body_context,
                    RepresentationIdentifier="Body", RepresentationType="Tessellation", Items=solids)
            else:
                self.bodies[key] = self.sweep(start_profile, start, length, end)
        return self.bodies[key]

    def loft(self, start, end, length):
        points, faces = [], []
        caps = [[], []]
        def face(indices):
            return self.m.create_entity("IfcIndexedPolygonalFace", CoordIndex=indices)
        for a, b in zip((start.exterior, *start.interiors), (end.exterior, *end.interiors)):
            rings = []
            for ring, z in ((a, 0.), (b, float(length))):
                indices = []
                for x, y in list(ring.coords)[:-1]:
                    points.append((x, y, z))
                    indices.append(len(points))
                rings.append(indices)
            n = len(rings[0])
            for i in range(n):
                j = (i + 1) % n
                # Triangles remain planar even for non-affine profile changes.
                faces.extend([face([rings[0][i], rings[0][j], rings[1][j]]),
                              face([rings[0][i], rings[1][j], rings[1][i]])])
            caps[0].append(list(reversed(rings[0])))
            caps[1].append(rings[1])
        for outer, *holes in caps:
            if holes:
                faces.append(self.m.create_entity("IfcIndexedPolygonalFaceWithVoids", CoordIndex=outer, InnerCoordIndices=holes))
            else:
                faces.append(face(outer))
        return self.m.create_entity("IfcPolygonalFaceSet", Coordinates=self.m.create_entity("IfcCartesianPointList3D", CoordList=points),
                                    Faces=faces, Closed=True)

    def axis_rep(self, length, cutback=0.):
        key=(length,cutback)
        if key not in self.axes:
            curve = self.curve([(0.,0.,-float(cutback)), (0., 0., float(length-cutback))])
            self.axes[key] = self.m.create_entity("IfcShapeRepresentation", ContextOfItems=self.axis_context,
                                                      RepresentationIdentifier="Axis", RepresentationType="Curve3D", Items=[curve])
        return self.axes[key]

    def product_shape(self,representations):
        if not representations:
            return None
        token=tuple(r.id() for r in representations)
        if token in self.shapes:
            return self.shapes[token]
        assigned = []
        for rep in representations:
            # IFC4 IfcShapeModel.WR11 gives each representation a single owner.
            # Its immutable curves and solids may still be reused.
            if rep.id() in self.used_reps:
                rep = self.m.create_entity("IfcShapeRepresentation", ContextOfItems=rep.ContextOfItems,
                                         RepresentationIdentifier=rep.RepresentationIdentifier,
                                         RepresentationType=rep.RepresentationType, Items=rep.Items)
            self.used_reps.add(rep.id())
            assigned.append(rep)
        self.shapes[token] = self.m.create_entity("IfcProductDefinitionShape", Representations=assigned)
        return self.shapes[token]

    def product(self, kind, row, role, origin, x=X, z=Z, representations=(), parent=None, container=None, **extra):
        key = row["id"]
        uid = row.get("unit") if self.data.get("units") else None
        group = (uid,at_level(self.data,row,origin[2],self.levels[uid])) if container is None else container
        storey, base = self.storeys[group]
        place = self.placement(sub(origin,base), x, z, storey.ObjectPlacement)
        shape = self.product_shape(representations)
        obj = self.root(kind, "product:" + key, Name=key, Tag=key, ObjectType=role, ObjectPlacement=place,
                        Representation=shape, **extra)
        if parent is None:
            self.contained[group].append(obj)
        if "material" in row:
            self.materials[row["material"]].append(obj)
        if parent is None:
            self.elements[key] = obj
        return obj

    def source_props(self, row, role, **other):
        mat = self.data["materials"].get(row.get("material"), {})
        return dict(SourceId=row["id"], Role=role, Profile=row.get("profile"), EndProfile=row.get("end_profile"),
                    Material=row.get("material"), Grade=mat.get("grade"), Standard=mat.get("standard"), FyMPa=mat.get("fy_mpa"),
                    CheckIds=row.get("checks", []), Unit=row.get("unit"), **other)

    def member(self, row):
        a, b = row["start"], row["end"]
        x, y, z = frame(a, b, row.get("ref_direction"))
        length = math.dist(a, b)
        p,q=member_body_ends(row)
        body = self.member_body(row["profile"], row.get("end_profile"), math.dist(p,q))
        uid = row.get("unit") if self.data.get("units") else None
        level = at_level(self.data, row, min(a[2], b[2]),self.levels[uid])
        cutback=row.get("end_cutbacks_mm",[0,0])[0]
        obj = self.product(member_class(row["role"]), row, row["role"], p, x, z, [self.axis_rep(length,cutback), body], container=(uid,level))
        self.props(obj, row["id"], self.source_props(row, row["role"], WorklineLengthMm=length,
                   EndCutbacksMm=row.get("end_cutbacks_mm"),DrilledFeatures=len(row["member_voids"]) if row.get("member_voids") else None))
        for feature in row.get("member_voids",[]):
            self.member_void(obj,feature,p,(x,y,z))

    def member_void(self,obj,feature,host_origin,host_axes):
        def local(v):
            return tuple(dot(v,axis) for axis in host_axes)
        if feature["kind"]=="bore":
            a,b=feature["start"],feature["end"]
            x,_,z=frame(a,b)
            d=float(feature["diameter_mm"])
            length=math.dist(a,b)
            token=("bore",d,round(length,8))
            if token not in self.fastener_bodies:
                prof=self.m.create_entity("IfcCircleProfileDef",ProfileType="AREA",ProfileName="Drill",Radius=d/2)
                self.fastener_bodies[token]=self.sweep("Drill",[prof],length)
            shape=self.fastener_bodies[token]
        else:
            (a,x,_,z),section=panel_shape(feature)
            shape=self.panel_body(section,feature["thickness_mm"])
        key=f"{obj.Tag}/void/{feature['id']}"
        place=self.placement(local(sub(a,host_origin)),local(x),local(z),obj.ObjectPlacement)
        op=self.root("IfcOpeningElement","opening:"+key,Name=key,Tag=key,ObjectType=feature["kind"],
                     Description=feature.get("connection"),PredefinedType="OPENING",ObjectPlacement=place,
                     Representation=self.product_shape([shape]))
        self.root("IfcRelVoidsElement","void:"+key,RelatingBuildingElement=obj,RelatedOpeningElement=op)

    def panel_body(self, shape, depth):
        signature=sha256(to_wkb(set_precision(shape,1e-7,mode="pointwise"))).digest()
        key=(signature,float(depth))
        if key not in self.panel_bodies:
            label="SECTION-"+signature.hex()[:16]
            self.panel_bodies[key]=self.sweep(label,[self.area(label,shape)],depth)
        return self.panel_bodies[key]

    def plate(self, row, kind, role, parent=None, level=None):
        basis, shape = panel_shape(row)
        origin, x, _, z = basis
        depth = row["thickness_mm"]
        rep = self.panel_body(shape,depth)
        obj = self.product(kind, row, role, origin, x, z, [rep], parent, level)
        self.props(obj, row["id"], self.source_props(row, role, ThicknessMm=depth))
        for i, hole in enumerate(row.get("openings", []), 1):
            oid = f"{row['id']}/opening/{i}"
            rep = self.panel_body(polygon(project(hole,basis)),depth)
            opening = self.root("IfcOpeningElement", "opening:" + oid, Name=oid, Tag=oid,
                                PredefinedType="OPENING", ObjectPlacement=obj.ObjectPlacement,
                                Representation=self.product_shape([rep]))
            self.root("IfcRelVoidsElement", "void:" + oid, RelatingBuildingElement=obj, RelatedOpeningElement=opening)
        return obj

    def panel(self, row):
        role = row["role"]
        lower = role.lower()
        kind = "IfcWall" if "wall" in lower else "IfcSlab" if any(v in lower for v in ("floor", "slab", "deck")) else "IfcRoof" if "roof" in lower else "IfcPlate"
        return self.plate(row, kind, role)

    def connection(self, row):
        key = row["id"]
        obj = self.product("IfcElementAssembly", row, row["type"], row["at"], PredefinedType="USERDEFINED")
        parts = []
        uid = row.get("unit") if self.data.get("units") else None
        level = (uid,at_level(self.data, row, row["at"][2],self.levels[uid]))
        for part in row.get("parts", []):
            if uid is not None:
                part=dict(part,unit=uid)
            kind = part["kind"]
            if kind == "plate":
                p = self.plate(part, "IfcPlate", kind, obj, level)
            else:
                a, b = part["start"], part["end"]
                x, _, z = frame(a, b, part.get("ref_direction"))
                if kind == "bolt":
                    diameter = float(part["diameter_mm"])
                    cls, subtype = "IfcMechanicalFastener", "BOLT"
                    sizes = (diameter,)
                    label = f"BOLT-{diameter:g}"
                    metadata = {"NominalDiameterMm": diameter}
                else:
                    cls, subtype = "IfcFastener", "WELD"
                    if part.get("weld_type") == "cjp":
                        throat = part["throat_mm"]
                        width = part.get("width_mm", throat)
                        sizes = ("cjp", throat, width)
                        label = f"CJP-{throat:g}x{width:g}"
                        metadata = {"WeldType": "CJP", "EffectiveThroatMm": throat, "EffectiveWidthMm": width}
                    else:
                        leg = part["leg_mm"]
                        sizes = ("fillet", leg)
                        label = f"FILLET-{leg:g}"
                        metadata = {"WeldType": "FILLET", "FilletLegMm": leg}
                length=math.dist(a,b)
                shape_key=(kind,sizes,round(length,7))
                if shape_key not in self.fastener_bodies:
                    area=(self.m.create_entity("IfcCircleProfileDef",ProfileType="AREA",ProfileName=label,Radius=diameter/2)
                          if kind=="bolt" else self.area(label,polygon(weld_outline(part))))
                    self.fastener_bodies[shape_key]=self.sweep(label,[area],length)
                rep=self.fastener_bodies[shape_key]
                p = self.product(cls, part, kind, a, x, z, [rep], obj, level, PredefinedType=subtype)
                self.props(p, part["id"], self.source_props(part, kind, **metadata))
            parts.append(p)
        self.aggregate(obj, parts, "parts:" + key)
        for target in row["members"]:
            self.root("IfcRelConnectsElements", f"receives:{key}:{target}",
                      RelatingElement=self.elements[target], RelatedElement=obj)
        self.props(obj, key, self.source_props(row, row["type"], ConnectedMembers=row["members"],
                                               Description=row.get("description"), Parameters=row.get("parameters"),
                                               GeometryScope="Declared parts" if parts else "Located specification only"))

    def grids(self, building):
        gs = self.data["grids"]
        bounds = {k: (min(g["coordinate_mm"] for g in gs[k]), max(g["coordinate_mm"] for g in gs[k])) for k in ("x","y")}
        # A single labelled datum remains a valid grid, including line-structure
        # examples. Extend its drawn extent to the physical member bounds.
        for i, k in enumerate(("x", "y")):
            values = [p[i] for m in self.data["members"] for p in (m["start"], m["end"])]
            lo, hi = bounds[k]; lo, hi = min(lo, min(values)), max(hi, max(values))
            bounds[k] = (lo, hi) if hi > lo else (lo - 500, hi + 500)
        def grid_axis(row, k):
            pos = row["coordinate_mm"]
            ends = [(pos, v) for v in bounds["y"]] if k == "x" else [(v, pos) for v in bounds["x"]]
            return self.m.create_entity("IfcGridAxis", AxisTag=row["id"], AxisCurve=self.curve(ends), SameSense=True)
        grid = self.root("IfcGrid", "grid", Name="Structural reference grid", ObjectPlacement=self.placement(),
                         UAxes=[grid_axis(row, "x") for row in gs["x"]], VAxes=[grid_axis(row, "y") for row in gs["y"]])
        self.root("IfcRelContainedInSpatialStructure", "grid-container", RelatedElements=[grid], RelatingStructure=building)

    def write(self, target):
        project = self.root("IfcProject", "project", Name=self.job["name"])
        length_unit = self.m.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
        angle_unit = self.m.create_entity("IfcSIUnit", UnitType="PLANEANGLEUNIT", Name="RADIAN")
        project.UnitsInContext = self.m.create_entity("IfcUnitAssignment", Units=[length_unit, angle_unit])
        context = ifcopenshell.api.context.add_context(self.m, context_type="Model")
        self.body_context = ifcopenshell.api.context.add_context(self.m, context_type="Model", context_identifier="Body",
                                                                 target_view="MODEL_VIEW", parent=context)
        self.axis_context = ifcopenshell.api.context.add_context(self.m, context_type="Model", context_identifier="Axis",
                                                                target_view="GRAPH_VIEW", parent=context)
        site = self.root("IfcSite", "site", Name=self.job.get("site", self.job["id"]), ObjectPlacement=self.placement())
        self.aggregate(project, [site], "site")
        buildings=[]
        unit_info={u["id"]:u for u in self.data.get("units",[])}
        for uid,origin in self.unit_origins.items():
            building=self.root("IfcBuilding","building:"+str(uid),Name=uid or self.job["id"],LongName=unit_info.get(uid,{}).get("name",self.job["name"]),
                               ObjectPlacement=self.placement(origin,relative=site.ObjectPlacement))
            buildings.append(building)
            levels=[]
            for row in self.levels[uid]:
                name,height=row["id"],float(row["elevation_mm"])
                level=self.root("IfcBuildingStorey",f"storey:{uid}:{name}",Name=name,Elevation=height,
                                ObjectPlacement=self.placement((0,0,height-origin[2]),relative=building.ObjectPlacement))
                self.storeys[uid,name]=(level,(origin[0],origin[1],height))
                levels.append(level)
            self.aggregate(building,levels,"levels:"+str(uid))
        self.aggregate(site,buildings,"buildings")
        self.grids(site if self.data.get("units") else buildings[0])
        self.props(project, "project", dict(ProjectId=self.job["id"], Module=self.job["module"], Units="mm", SourceSHA256=self.digest,
                                            DesignBasis=self.job.get("design_basis", []), Checks=self.data.get("checks", []),
                                            Assumptions=self.data.get("assumptions", []), DesignStatus=design_status(self.data,[*self.gaps,*self.clashes,self.bolt_fit]),
                                            BoltPlateFit=self.bolt_fit,
                                            UnitsSetout=self.data.get("units",[]), SeparationJoints=self.gaps, InterunitPlateClashes=self.clashes,
                                            SourceEvidence=self.data.get("source_evidence")))
        for row in self.data["members"]:
            self.member(row)
        for row in self.data.get("panels", []):
            self.panel(row)
        for row in self.data.get("connections", []):
            self.connection(row)
        for (uid,name), products in self.contained.items():
            self.root("IfcRelContainedInSpatialStructure", f"contain:{uid}:{name}", RelatedElements=products, RelatingStructure=self.storeys[uid,name][0])
        for key, products in self.materials.items():
            row = self.data["materials"][key]
            mat = self.m.create_entity("IfcMaterial", Name=key, Description=f"{row['standard']} | {row['grade']}")
            self.root("IfcRelAssociatesMaterial", "material:" + key, RelatedObjects=products, RelatingMaterial=mat)
        header = self.m.header.file_name
        header.name = "model.ifc"
        header.time_stamp = self.job.get("issue_timestamp", "1970-01-01T00:00:00Z")
        header.author = ("Steltic",)
        header.organization = ("Steltic",)
        header.originating_system = "Steltic openBIM India 0.1.0"
        self.m.write(str(target))


def write_ifc(data, digest, target, gaps=(),clashes=(),bolt_fit=None):
    from .bolt_fit import from_source
    Exchange(data, digest, gaps,clashes,bolt_fit or from_source(data)).write(target)
