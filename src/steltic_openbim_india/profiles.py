"""Source-dimensioned silhouettes. Local coordinates are section width and depth in mm."""

import math
from numbers import Real

from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def polygon(shell, holes=()):
    try:
        if any(len(pt) != 2 or any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v)
                                    for v in pt) for ring in (shell, *holes) for pt in ring):
            raise ValueError("expected finite 2D polygon coordinates")
        value = Polygon(shell, holes)
    except (TypeError, IndexError) as ex:
        raise ValueError("invalid profile or panel boundary") from ex
    if value.is_empty or value.area < 1e-6 or not value.is_valid:
        raise ValueError("invalid profile or panel polygon: " + explain_validity(value))
    return orient(value, sign=1)


def rectangle(b, d):
    return [(-b / 2, -d / 2), (b / 2, -d / 2), (b / 2, d / 2), (-b / 2, d / 2)]


def rounded_vertex(a, b, c, radius):
    """Tangent arc between two finite edges, sampled every 7.5 degrees or less."""
    if radius == 0:
        return [b]
    u = [(b[i] - a[i]) / math.dist(a, b) for i in range(2)]
    v = [(c[i] - b[i]) / math.dist(b, c) for i in range(2)]
    turn = math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
    distance = abs(radius * math.tan(turn / 2))
    if distance >= min(math.dist(a, b), math.dist(b, c)):
        raise ValueError("corner radius exceeds the section geometry")
    start = tuple(b[i] - distance * u[i] for i in range(2))
    sign = 1 if turn > 0 else -1
    center = (start[0] - sign * radius * u[1], start[1] + sign * radius * u[0])
    angle = math.atan2(start[1] - center[1], start[0] - center[0])
    count = max(1, math.ceil(abs(turn) / math.radians(7.5)))
    return [(center[0] + radius * math.cos(angle + turn * i / count),
             center[1] + radius * math.sin(angle + turn * i / count)) for i in range(count + 1)]


def rolled_outline(vertices, radii):
    pts = []
    for i, p in enumerate(vertices):
        pts.extend(rounded_vertex(vertices[i - 1], p, vertices[(i + 1) % len(vertices)], radii.get(i, 0)))
    return polygon(pts)


def section_polygons(profile):
    """One polygon per physical component, including all its internal voids."""
    family = profile["family"]
    dms = profile.get("dimensions_mm", {})
    if "contours_mm" in profile:
        contours = profile["contours_mm"]
        holes = profile.get("holes_mm", [[] for _ in contours])
        if not contours or len(contours) != len(holes):
            raise ValueError("contours_mm needs one holes_mm group per component")
        components = [polygon(ring, voids) for ring, voids in zip(contours, holes)]
        for i, component in enumerate(components):
            if any(component.intersection(other).area > 0.0001 for other in components[:i]):
                raise ValueError("section components overlap")
        return components
    if family == "POLYGON":
        raise ValueError("POLYGON requires contours_mm")
    if family in {"CHS", "ROD"}:
        dia = positive(dms.get("diameter", dms.get("d")), "diameter")
        def circle(r):
            return [(r * math.cos(i * math.tau / 96), r * math.sin(i * math.tau / 96)) for i in range(96)]
        holes = []
        if family == "CHS":
            t = positive(dms.get("t"), "tube wall")
            if 2 * t >= dia:
                raise ValueError("tube wall consumes the bore")
            holes = [circle(dia / 2 - t)]
        return [polygon(circle(dia / 2), holes)]
    d = positive(dms.get("d", dms.get("t") if family == "PLATE" else None), "section depth")
    b = positive(dms.get("b"), "section width")
    if family == "PLATE":
        return [polygon(rectangle(b, d))]
    tw = positive(dms.get("tw", dms.get("t")), "web thickness")
    tf = positive(dms.get("tf", dms.get("t")), "flange thickness")
    if tw >= b or tf >= d or (family != "L" and (2 * tf >= d or (family == "RHS" and 2 * tw >= b))):
        raise ValueError("section thickness consumes its void")
    h, w = d / 2, b / 2
    r = dms.get("r", dms.get("r1", 0))
    toe = dms.get("r2", 0)
    if not all(isinstance(x, Real) and not isinstance(x, bool) and math.isfinite(x) and x >= 0 for x in (r, toe)):
        raise ValueError("section radius must be finite and non-negative")
    if family == "RHS":
        if r:
            outer = rolled_outline(rectangle(b, d), dict.fromkeys(range(4), r + max(tw, tf)))
            inner = rolled_outline(rectangle(b - 2 * tw, d - 2 * tf), dict.fromkeys(range(4), r))
            return [polygon(outer.exterior.coords, [inner.exterior.coords])]
        return [polygon(rectangle(b, d), [rectangle(b - 2 * tw, d - 2 * tf)])]
    if family == "L":
        pts = [(-w, -h), (w, -h), (w, -h + tf), (-w + tw, -h + tf), (-w + tw, h), (-w, h)]
        return [rolled_outline(pts, {2: toe, 3: r, 4: toe})]
    if family == "I":
        slope = math.tan(math.radians(dms.get("slope_deg", 0.0)))
        edge = tf - b * slope / 4
        root = edge + (b - tw) * slope / 2
        if edge <= 0 or root * 2 >= d:
            raise ValueError("invalid rolled flange slope")
        pts = [(-w, -h), (w, -h), (w, -h + edge), (tw/2, -h + root), (tw/2, h - root),
               (w, h - edge), (w, h), (-w, h), (-w, h - edge), (-tw/2, h - root),
               (-tw/2, -h + root), (-w, -h + edge)]
        return [rolled_outline(pts, {2: toe, 3: r, 4: r, 5: toe, 8: toe, 9: r, 10: r, 11: toe})]
    if family not in {"C", "Z"}:
        raise ValueError(f"unsupported section family {family!r}")
    lip = dms.get("lip", 0)
    if not isinstance(lip, Real) or isinstance(lip, bool) or not math.isfinite(lip) or not 0 <= lip < d / 2:
        raise ValueError("section lip is outside the profile")
    if family == "C" and not lip and (not math.isclose(tw,tf) or dms.get("slope_deg") or toe):
        slope=math.tan(math.radians(dms.get("slope_deg",0)))
        edge=tf-b*slope/4
        middle=edge+(b-tw)*slope
        if edge<=0 or 2*middle>=d:
            raise ValueError("invalid channel flange slope")
        pts = [(-w, -h), (w, -h), (w, -h + edge), (-w + tw, -h + middle), (-w + tw, h - middle),
               (w, h - edge), (w, h), (-w, h)]
        return [rolled_outline(pts, {2: toe, 3: r, 4: r, 5: toe})]
    if not math.isclose(tw, tf):
        raise ValueError("folded or Z sections with unequal thicknesses require explicit contours")
    # Opposing Z flanges project one full b each from opposite faces of the web.
    web = -w + tw / 2 if family == "C" else 0
    lower = (w - tw/2 if lip else w) if family == "C" else -(b - tw)
    upper = (w - tw/2 if lip else w) if family == "C" else b - tw
    run = [(lower, -h + tf/2), (web, -h + tf/2), (web, h - tf/2), (upper, h - tf/2)]
    if lip:
        if lip <= tf:
            raise ValueError("lip must extend beyond the flange thickness")
        run = [(lower, -h + lip), *run, (upper, h - lip)]
    elif family == "Z":
        run[0] = (lower - tw/2, run[0][1])
        run[-1] = (upper + tw/2, run[-1][1])
    centerline = [run[0]]
    for i in range(1, len(run) - 1):
        centerline.extend(rounded_vertex(run[i-1], run[i], run[i+1], r + tw/2) if r else [run[i]])
    centerline.append(run[-1])
    shape = LineString(centerline).buffer(tw/2, cap_style="flat", join_style="mitre")
    return [polygon(shape.exterior.coords)]
