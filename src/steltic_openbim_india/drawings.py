"""Dimensioned metric A1 sheets derived from the same occurrences as IFC.

The series, scale selection, dimension witnesses, vector tags and paginated
schedules adapt the design_pdf and cfs_native_pdf workflows in the Steltic
openBIM reference at c3796b8. Coordinates remain metric throughout.
"""

import json
import math
from collections import Counter, defaultdict

from reportlab.lib.pagesizes import A1, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from shapely.geometry import MultiPoint

from .geometry import frame, plane
from .model import design_status, unit_levels
from .profiles import section_polygons


W, H = landscape(A1)
MM = 72 / 25.4
INK, MUTED, LIGHT, BLUE, RED = "#263a46", "#5a6c75", "#bcc9cf", "#1a617c", "#943f26"
SCALES = (1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 750, 1000, 1500, 2000)


def printed(value):
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".") or "0"
    value = str(value).replace("−", "-").replace("→", " to ").replace("≤", "<=").replace("≥", ">=").replace("₂","2")
    value = value.replace("Δ", "delta").replace("φ", "phi").replace("θ", "theta").replace("μ", "mu")
    return value.encode("cp1252", "replace").decode("cp1252")


def wrap(value, width, size, font="Helvetica"):
    rows, line = [], ""
    for word in printed(value).split():
        # Long calculation IDs also have to fit the printed cell.
        while stringWidth(word, font, size) > width:
            if line:
                rows.append(line); line = ""
            cut = max(1, int(len(word) * width / stringWidth(word, font, size)) - 1)
            rows.append(word[:cut]); word = word[cut:]
        trial = (line + " " + word).strip()
        if line and stringWidth(trial, font, size) > width:
            rows.append(line); line = word
        else:
            line = trial
    if line or not rows:
        rows.append(line)
    return rows


def coord(v):
    return ", ".join(printed(float(t)) for t in v)


def bounds(points):
    return [(min(p[i] for p in points), max(p[i] for p in points)) for i in range(2)]


def fit(ranges, box):
    x, y, w, h = box
    dw, dh = (b - a for a, b in ranges)
    need = max(dw * MM / w, dh * MM / h)
    den = next((k for k in SCALES if k >= need), math.ceil(need / 500) * 500)
    s = MM / den
    off = [x + (w - dw*s)/2 - ranges[0][0]*s, y + (h - dh*s)/2 - ranges[1][0]*s]
    return den, s, off


def mark_groups(members):
    groups = defaultdict(list)
    for m in members:
        groups[(m["role"], m["profile"], m.get("end_profile", ""), m["material"])].append(m)
    marks, rows = {}, []
    for i, (key, members) in enumerate(sorted(groups.items()), 1):
        role, profile, end_profile, material = key
        mark = f"M{i:03}"
        lengths = [math.dist(m["start"], m["end"]) for m in members]
        rows.append(dict(mark=mark, role=role, profile=profile, end_profile=end_profile or None, material=material,
                         count=len(members), min_length_mm=min(lengths), max_length_mm=max(lengths)))
        marks.update({m["id"]:mark for m in members})
    return marks, rows


class Sheets:
    def __init__(self, data, digest, target, gaps, clashes, bolt_fit):
        self.data, self.job, self.digest = data, data["project"], digest
        self.c = Canvas(str(target), pagesize=(W, H), pageCompression=1, invariant=1)
        self.c.setTitle(self.job["name"] + " | Structural drawings")
        self.c.setAuthor("Steltic openBIM India")
        self.marks, self.member_rows = mark_groups(data["members"])
        self.members = {m["id"]:m for m in data["members"]}
        self.sheets, self.views, self.dimensions, self.detail_register = [], [], [], []
        self.current = ""
        self.gaps = gaps
        self.clashes = clashes
        self.bolt_fit = bolt_fit
        self.design_status = design_status(data,[*gaps,*clashes,bolt_fit])
        self.shapes = {k:section_polygons(p) for k,p in data["profiles"].items()}
        self.silhouettes = {}
        self.plan_number = self.elevation_number = 0

    def text(self, x, y, value, size=13, *, color=INK, bold=False, align="left"):
        self.c.setFillColor(color)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        writer = {"left":self.c.drawString, "center":self.c.drawCentredString, "right":self.c.drawRightString}[align]
        writer(x, y, printed(value))

    def line(self, a, b, color=INK, width=0.9, dash=None):
        self.c.setStrokeColor(color); self.c.setLineWidth(width); self.c.setDash(dash or ())
        self.c.line(*a, *b); self.c.setDash(())

    def sheet(self, number, title, kind, scale=None):
        if self.sheets:
            self.c.showPage()
        self.current = number
        self.sheets.append(dict(page=len(self.sheets)+1, number=number, title=title, kind=kind, scale=scale))
        self.c.bookmarkPage(number)
        self.c.addOutlineEntry(f"{number}  {printed(title)}", number)
        self.c.setStrokeColor(INK); self.c.setLineWidth(1); self.c.rect(34, 34, W-68, H-68)
        self.text(62, H-77, title, 25, bold=True)
        self.text(W-62, H-75, number, 25, bold=True, align="right")
        self.line((34,H-95),(W-34,H-95),LIGHT)
        self.line((34,113),(W-34,113),INK,1)
        self.text(62,81,self.job["name"],17,bold=True)
        self.text(62,54,f"{self.job['id']}  |  {self.job['module']}  |  Structural design coordination  |  Dimensions in mm",12)
        self.text(W-65,81,"Steltic openBIM India   /   A1" + (f"   /   1:{scale}" if scale else ""),15,bold=True,align="right")
        self.text(W-65,55,f"Source {self.digest[:20]}   /   Page {len(self.sheets)}",12,align="right")
        status = {"pass":"SOURCE CHECKS PASS / DESIGN COORDINATION",
                  "review":"DESIGN REVIEW / COORDINATION CANDIDATE", "fail":"DESIGN FAIL / COORDINATION CANDIDATE"}[self.design_status]
        self.text(W*.59,64,status,14,bold=True,color=BLUE if self.design_status=="pass" else RED,align="center")

    def table(self, prefix, title, kind, columns, rows):
        """Paginate wrapped cells; continuation pages preserve every cell."""
        widths = [v*(W-150) for _,v in columns]
        page, y = 0, 0
        def next_page():
            nonlocal page, y
            page += 1
            self.sheet(prefix if page == 1 else f"{prefix}-{page}", title if page == 1 else f"{title} (continued {page})", kind)
            x = 75; y = H-145
            for (label,_), width in zip(columns, widths):
                self.text(x, y, label, 14, bold=True, color=BLUE); x += width
            y -= 14; self.line((72,y),(W-72,y),MUTED); y -= 28
        for row in rows:
            cells = [wrap(s, w-20, 13) for s,w in zip(row,widths)]
            pos, count = 0, max(map(len,cells))
            while pos < count:
                if y < 175:
                    next_page()
                space = max(1, int((y-145)/18))
                if count < 70 and pos == 0 and count > space:
                    next_page(); space = int((y-145)/18)
                used = min(count-pos,space)
                x = 75
                for cell, width in zip(cells, widths):
                    for j, line in enumerate(cell[pos:pos+used]):
                        self.text(x, y-18*j, line)
                    x += width
                y -= 18*used + 16; pos += used
                self.line((72,y+17),(W-72,y+17),LIGHT,.4)
        return page

    def dimension(self, a, b, value, offset, source):
        tag = "D" + str(len(self.dimensions)+1)
        dist = math.dist(a,b)
        if dist < .05:
            return
        ux, uy = (b[0]-a[0])/dist, (b[1]-a[1])/dist
        nx, ny = -uy, ux
        p, q = [(x+nx*offset,y+ny*offset) for x,y in (a,b)]
        label = printed(round(float(value), 2))
        self.c.addLiteral(f"/StelticDim << /ID /{tag} >> BDC")
        for s,t in ((a,p),(b,q)):
            self.line(s,t,MUTED,.45)
            self.line((t[0]-3*ux-3*nx,t[1]-3*uy-3*ny),(t[0]+3*ux+3*nx,t[1]+3*uy+3*ny),INK,.65)
        self.line(p,q,MUTED,.6)
        self.c.saveState(); self.c.translate((p[0]+q[0])/2,(p[1]+q[1])/2)
        self.c.rotate(math.degrees(math.atan2(uy,ux)))
        self.text(0,4,label,10,align="center"); self.c.restoreState()
        self.c.addLiteral("EMC")
        self.dimensions.append(dict(id=tag,sheet=self.current,text=label,value_mm=value,witnesses_pt=[a,b],line_pt=[p,q],source=source))

    def polyline(self, pts, color, width, *, dashed=False):
        if len(pts)<2:
            return
        path = self.c.beginPath(); path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        path.close()
        self.c.setStrokeColor(color); self.c.setLineWidth(width); self.c.setDash((5,3) if dashed else ())
        self.c.drawPath(path); self.c.setDash(())

    def basis(self):
        data = self.data
        checks = Counter(c["status"] for c in data.get("checks",[]))
        open_joints = sum(not c.get("parts") for c in data.get("connections",[]))
        basis = [("Drawing scope", "Located member worklines, sections, storeys, grids and fabrication details explicitly supplied by the design producer. Member lengths in the schedules are workline lengths."),
                 ("Geometry",f"{len(data['members'])} members / {len(data.get('panels',[]))} panels / {len(data.get('connections',[]))} located connections. {open_joints} connection specifications await physical part geometry."),
                 ("Reported design checks",f"{checks['pass']} pass / {checks['review']} review / {checks['fail']} fail. See K-series for the calculation records and G-series assumptions."),
                 ("Drawing series","S - framing plans and frame elevations. M - member and section schedules. P - cross sections. A - panels and openings. C and D - connection schedules and details. K - reported design checks."),
                 ("Section basis","Sections use the dimensions in the source handoff. Undeclared rolling/bend radii and local fabrication fit are omitted; consult the component producer for those dimensions.")]
        basis += [("Design basis",v) for v in self.job.get("design_basis",[])]
        evidence=data.get("source_evidence",{})
        if evidence.get("producer"):
            basis.append(("Design producer",evidence["producer"]))
        if evidence.get("native_status"):
            basis.append(("Native job status",json.dumps(evidence["native_status"],ensure_ascii=False,sort_keys=True)))
        for item in evidence.get("open_items",[]):
            basis.append(("Producer open item",item if isinstance(item,str) else json.dumps(item,ensure_ascii=False,sort_keys=True)))
        basis += [(k,f"{v['grade']} / {v['standard']}" + (f" / fy {printed(v['fy_mpa'])} MPa" if "fy_mpa" in v else "")) for k,v in data["materials"].items()]
        basis += [("Assumption",v) for v in data.get("assumptions",[])]
        self.table("G-001","General notes, design basis and materials","basis",[("Item",.20),("Declared basis",.80)],basis)
        if self.bolt_fit["interferences"]:
            rows=[(r["connection"],r["bolt"],r["plate"],r["material_penetration_mm"],r["cross_section_overlap_mm2"])
                  for r in self.bolt_fit["interferences"]]
            self.table("G-006","Bolt shafts intersecting plate material","bolt_fit",
                       [("Connection",.22),("Bolt",.22),("Plate",.22),("Radial shortfall (mm)",.17),("Overlap area (mm²)",.17)],rows)

    def composite(self):
        units=self.data.get("units",[])
        if len(units)<2:
            return
        grid=[[(r["id"],r["coordinate_mm"]) for r in self.data["grids"][k]] for k in ("x","y")]
        self.view("G-002","Structural units and separation joints","key_plan",(0,1),self.data["members"],self.data.get("panels",[]),grid)
        rows=[(u["id"],u["name"],coord(u["origin_mm"]),", ".join(level["id"] for level in unit_levels(self.data,u))) for u in units]
        self.table("G-003","Structural unit set-out","unit_setout",[("Unit",.16),("Name",.22),("Origin X, Y, Z (mm)",.23),("Storeys",.39)],rows)
        rows=[]
        for j in self.gaps:
            def dim(key):
                v=j.get(key)
                return "-" if v is None else printed(round(v,2))
            rows.append((j["id"]," / ".join(j["units"]),j["axis"].upper(),dim("declared_gap_mm"),dim("required_gap_mm"),dim("measured_gap_mm"),
                         j["status"].upper()," / ".join(k or "-" for k in j["limiting_occurrences"]),j.get("reference","-")))
        if rows:
            self.table("G-004","Separation between outermost modelled faces","joint_clearance",
                       [("Joint",.10),("Units",.15),("Axis",.05),("Declared (mm)",.10),("Required (mm)",.10),("Measured (mm)",.10),
                        ("Status",.08),("Limiting occurrences",.20),("Basis",.12)],rows)
        if self.clashes:
            rows=[(" / ".join(r["units"])," / ".join(r["occurrences"]),printed(round(r["overlap_area_mm2"],2)),
                   printed(round(r["overlap_depth_mm"],2)),printed(round(r["overlap_volume_mm3"],2))) for r in self.clashes]
            self.table("G-005","Intersections of plates in separate units","plate_clashes",[("Units",.17),("Plate pair",.32),
                       ("Intersection area (mm²)",.17),("Overlap depth (mm)",.16),("Common volume (mm³)",.18)],rows)

    def physical_outline(self,m,axes,tr,scale):
        """Projected outside envelope; end-on sections retain their open folds and bores."""
        a,b=m["start"],m["end"]
        x,y,z=frame(a,b,m.get("ref_direction"))
        offset=tuple(b[i]-a[i] for i in axes)
        key=(m["profile"],m.get("end_profile"),tuple(axes),x,y,offset)
        if key not in self.silhouettes:
            out=[]
            def local(ring,increment=(0,0)):
                return [(u*x[axes[0]]+v*y[axes[0]]+increment[0],u*x[axes[1]]+v*y[axes[1]]+increment[1]) for u,v in ring.coords]
            for p,q in zip(self.shapes[m["profile"]],self.shapes[m.get("end_profile",m["profile"])]):
                if math.hypot(*offset)<.01:
                    for ring in (p.exterior,*p.interiors):
                        out.append(local(ring))
                else:
                    hull=MultiPoint(local(p.exterior)+local(q.exterior,offset)).convex_hull
                    if hull.geom_type=="Polygon":
                        out.append(list(hull.exterior.coords))
            self.silhouettes[key]=out
        origin=tr(a)
        for ring in self.silhouettes[key]:
            paper=[(origin[0]+u*scale,origin[1]+v*scale) for u,v in ring]
            self.polyline(paper,MUTED,.45)

    def view(self, number, title, kind, axes, members, panels, datums, **identity):
        pts = [tuple(p[i] for i in axes) for m in members for p in (m["start"],m["end"])]
        pts += [tuple(p[i] for i in axes) for panel in panels for p in panel["outline"]]
        if not pts:
            return
        ranges = bounds(pts)
        # Keep the full source grid on plans while restricting frame elevations to
        # occupied levels and stations, particularly at setbacks.
        for i in range(2):
            values = [coord for _,coord in datums[i]]
            if values and kind=="plan":
                ranges[i] = min(ranges[i][0],min(values)),max(ranges[i][1],max(values))
        den, s, off = fit(ranges,(230,340,W-530,H-630))
        self.sheet(number,title,kind,den)
        def translate(v):
            return [off[i]+v[i]*s for i in range(2)]
        def tr(p):
            return translate([p[i] for i in axes])
        low, high = [translate([r[t] for r in ranges]) for t in (0,1)]
        projection = dict(sheet=number, axes=list(axes), origin_pt=off, points_per_mm=s, bounds_mm=ranges,
                          member_ids=[m["id"] for m in members], panel_ids=[p["id"] for p in panels], **identity)
        self.views.append(projection)
        for i in (0,1):
            selected = [(k,v) for k,v in sorted(datums[i],key=lambda t:t[1]) if ranges[i][0]-.01 <= v <= ranges[i][1]+.01]
            last = None
            for key, val in selected:
                p, q = list(low), list(high)
                p[i] = q[i] = off[i]+val*s
                self.line(p,q,LIGHT,.55,[9,4])
                if last is None or (val-last)*s >= 30:
                    if i==0:
                        self.text(p[0], high[1]+18,key,11,color=MUTED,align="center")
                    else:
                        self.text(high[0]+12,p[1]-4,key,11,color=MUTED)
                    last=val
            for j,((ka,a),(kb,b)) in enumerate(zip(selected,selected[1:])):
                pos, end = list(low),list(low)
                pos[i],end[i] = off[i]+a*s,off[i]+b*s
                # Alternate lanes for tightly spaced grid intervals.
                offset = 30 + (j%3)*16 if (b-a)*s<55 else 30
                self.dimension(pos,end,b-a,-offset if i==0 else offset,dict(kind="datum_interval",axis=axes[i],start=ka,end=kb))
            if len(selected)>2:
                a,b=selected[0],selected[-1]; pos,end=list(low),list(low)
                pos[i],end[i]=off[i]+a[1]*s,off[i]+b[1]*s
                self.dimension(pos,end,b[1]-a[1],-86 if i==0 else 86,dict(kind="datum_overall",axis=axes[i],start=a[0],end=b[0]))
        for p in panels:
            self.polyline([tr(v) for v in p["outline"]],MUTED,.9)
            for ring in p.get("openings",[]):
                self.polyline([tr(v) for v in ring],RED,1.2,dashed=True)
        groups = defaultdict(list)
        for i,m in enumerate(members):
            p,q=tr(m["start"]),tr(m["end"])
            self.physical_outline(m,axes,tr,s)
            color=BLUE if any(k in m["role"].lower() for k in ("brace","strap","tie","rod")) else INK
            self.c.addLiteral(f"/StelticAxis << /ID /A{i+1} >> BDC")
            self.line(p,q,color,1.15 if color==INK else .85)
            if math.dist(p,q)<2:
                self.c.setStrokeColor(color); self.c.rect(p[0]-2.5,p[1]-2.5,5,5)
            self.c.addLiteral("EMC")
            groups[self.marks[m["id"]]].append((p,q))
        occupied = []
        for mark, candidates in sorted(groups.items()):
            for p,q in sorted(candidates,key=lambda seg:-math.dist(*seg)):
                x,y=(p[0]+q[0])/2+4,(p[1]+q[1])/2+5
                if all(abs(x-u)>42 or abs(y-v)>16 for u,v in occupied):
                    self.text(x,y,mark,10,color=BLUE,bold=True); occupied.append((x,y)); break
        self.text(72,192,f"{len(members)} member occurrences  /  {len(panels)} panel boundaries  /  reference grid and worklines in mm",13)
        self.text(72,159,"Member axes and outer envelopes are shown. Member marks refer to the M-series. Dashed red outlines indicate panel openings.",12,color=MUTED)

    def framing(self,unit=None):
        data=self.data; ms=data["members"]; panels=data.get("panels",[])
        grid=[[(r["id"],r["coordinate_mm"]) for r in data["grids"][k]] for k in ("x","y")]
        prefix=""
        identity={}
        if unit:
            uid=unit["id"]
            ms=[m for m in ms if m["unit"]==uid]
            panels=[p for p in panels if p["unit"]==uid]
            footprint=[point for m in ms for point in (m["start"],m["end"])]
            if not footprint:
                return
            local_bounds=bounds(footprint)
            grid=[[(lab,pos) for lab,pos in grid[i] if local_bounds[i][0]-.1 <= pos <= local_bounds[i][1]+.1] for i in (0,1)]
            prefix=unit["name"]+" / "; identity={"unit":uid}
        levels=sorted(unit_levels(data,unit), key=lambda r:r["elevation_mm"])
        datums=[(r["id"],r["elevation_mm"]) for r in levels]
        plan_members=defaultdict(list); plan_panels=defaultdict(list)
        for row,group,points in [(r,plan_members,[r["start"],r["end"]]) for r in ms]+[(r,plan_panels,r["outline"]) for r in panels]:
            a,b=min(p[2] for p in points),max(p[2] for p in points)
            targets=set()
            if row.get("level"):
                targets.add(row["level"])
            target=next((lv for lv,z in datums if z>=b-.01),datums[-1][0])
            targets.add(target)
            vertical=all(math.dist(p[:2],points[0][:2])<.01 for p in points)
            if vertical:
                targets.update(lv for lv,z in datums if a-.01<=z<=b+.01)
            for lv in targets:
                group[lv].append(row)
        for i,(lv,z) in enumerate(datums,1):
            self.plan_number+=1
            self.view(f"S-1{self.plan_number:02}",f"{prefix}{lv} framing plan  /  EL {printed(z)} mm","plan",(0,1),
                      plan_members[lv],plan_panels[lv],grid,level=lv,**identity)
        seen=set()
        for axis in (0,1):
            for label,pos in grid[axis]:
                mm=[m for m in ms if all(abs(p[axis]-pos)<.1 for p in (m["start"],m["end"]))]
                pp=[p for p in panels if all(abs(v[axis]-pos)<.1 for v in p["outline"])]
                if not mm and not pp:
                    continue
                self.elevation_number+=1
                self.view(f"S-2{self.elevation_number:02}",f"{prefix}Frame elevation on {'XY'[axis]} grid {label}","elevation",
                          (1-axis,2),mm,pp,[grid[1-axis],datums],grid_axis=axis,grid_id=label,**identity)
                seen.update(m["id"] for m in mm)
        offgrid=[m for m in ms if m["id"] not in seen]
        if offgrid:
            for axis in (0,1):
                self.elevation_number+=1
                self.view(f"S-2{self.elevation_number:02}",f"{prefix}Off-grid framing projection along {'XY'[axis]}","elevation",
                          (1-axis,2),offgrid,[],[grid[1-axis],datums],off_grid=True,**identity)

    def schedules(self):
        member_values=[(m["mark"],m["role"],m["profile"],m["end_profile"] or "-",m["material"],m["count"],
                        printed(round(m["min_length_mm"],1)),printed(round(m["max_length_mm"],1))) for m in self.member_rows]
        self.table("M-001","Member schedule","members",[("Mark",.08),("Role",.18),("Start section",.17),("End section if tapered",.17),
                   ("Material",.15),("Count",.07),("Min length (mm)",.09),("Max length (mm)",.09)],member_values)
        checks=self.data.get("checks",[])
        if checks:
            rows=[(r["id"],r["description"],r["status"].upper(),printed(r["utilization"]) if r.get("utilization") is not None else "-",
                   r.get("reference","-")) for r in checks]
            self.table("K-001","Reported design checks","checks",[("Check ID",.16),("Calculation or open item",.43),("Status",.075),
                       ("Utilization",.075),("Source reference",.26)],rows)
        rows=[]
        for p in self.data.get("panels",[]):
            rows.append((p["id"],p["role"],p["material"],p["thickness_mm"],len(p.get("openings",[])),coord(p["outline"][0])))
        if rows:
            self.table("A-001","Panel and sheathing schedule","panels",[("Panel",.18),("Role",.22),("Material",.14),
                       ("Thickness (mm)",.13),("Openings",.11),("First vertex X, Y, Z (mm)",.22)],rows)
        rows=[]
        for p in self.data.get("panels",[]):
            for i,h in enumerate(p.get("openings",[]),1):
                rows.append((p["id"],i," / ".join(coord(v) for v in h)))
        if rows:
            self.table("A-002","Hosted opening set-out","openings",[("Host panel",.18),("Opening",.09),("Perimeter X, Y, Z (mm)",.73)],rows)

    def sections(self):
        profiles=list(self.data["profiles"].items())
        for page, start in enumerate(range(0,len(profiles),6),1):
            self.sheet(f"P-{page:03}","Section profiles and dimensions","profiles")
            for j,(name,record) in enumerate(profiles[start:start+6]):
                col, row = j%3,j//3
                x=67+col*(W-130)/3; y=H-148-row*660
                self.text(x,y,name,16,bold=True)
                shapes=section_polygons(record)
                pts=[v for sh in shapes for v in sh.exterior.coords]
                ranges=bounds(pts); den,s,off=fit(ranges,(x+86,y-408,530,305))
                def tr(pt):
                    return [off[i]+pt[i]*s for i in range(2)]
                for shape in shapes:
                    for ring in (shape.exterior,*shape.interiors):
                        self.polyline([tr(v) for v in ring.coords],INK,1.25)
                lo=[r[0] for r in ranges]; hi=[r[1] for r in ranges]
                self.dimension(tr(lo),tr([hi[0],lo[1]]),hi[0]-lo[0],-26,dict(kind="section_width",profile=name))
                self.dimension(tr(lo),tr([lo[0],hi[1]]),hi[1]-lo[1],26,dict(kind="section_depth",profile=name))
                lab=record.get("dimensions_mm",{})
                content=f"{record['family']}   /   1:{den}   /   " + ", ".join(f"{k} {printed(v)}" for k,v in lab.items())
                for n,line in enumerate(wrap(content,660,12)):
                    self.text(x,y-480-18*n,line,12)

    def connections(self):
        cs = self.data.get("connections",[])
        if not cs:
            return
        groups=defaultdict(list)
        for c in cs:
            def normalize(p):
                return [round(x-y,5) for x,y in zip(p,c["at"])]
            normalized=[]
            for p in c.get("parts",[]):
                item={k:v for k,v in p.items() if k not in {"id","start","end","outline","openings"}}
                for k in ("start","end"):
                    if k in p: item[k]=normalize(p[k])
                if "outline" in p: item["outline"]=[normalize(v) for v in p["outline"]]
                if "openings" in p: item["openings"]=[[normalize(v) for v in ring] for ring in p["openings"]]
                normalized.append(item)
            key=json.dumps([c["type"],c.get("description"),c.get("parameters"),normalized],sort_keys=True,ensure_ascii=False)
            groups[key].append(c)
        types = {}
        for n, group in enumerate(groups.values(),1):
            no=f"D-{n:03}"
            types.update({c["id"]:no for c in group})
        rows=[(c["id"],c["type"],coord(c["at"]),", ".join(c["members"]),types[c["id"]],", ".join(c.get("checks",[])) or "-") for c in cs]
        self.table("C-001","Connection locations and receivers","connections",[("Connection",.16),("Type",.16),("X, Y, Z (mm)",.19),
                   ("Receiving members",.28),("Detail",.08),("Check records",.13)],rows)
        for n,group in enumerate(groups.values(),1):
            self.detail(f"D-{n:03}",group)

    def detail(self, number, group):
        c=group[0]
        self.sheet(number,f"Connection detail  /  {c['type']}","details")
        detail=dict(sheet=number,representative=c["id"],occurrences=[r["id"] for r in group],
                    part_ids=[p["id"] for p in c.get("parts",[])],projections=[])
        self.detail_register.append(detail)
        self.text(73,H-145,f"{c['id']}  /  joint {coord(c['at'])} mm  /  {len(group)} occurrence(s) of this detail",16,bold=True)
        y=H-183
        selected = c.get("description","")
        for txt in [selected, "Connected members: "+", ".join(c["members"]),
                    "Selected parameters: "+json.dumps(c.get("parameters",{}),sort_keys=True,ensure_ascii=False)]:
            for line in wrap(txt,W-145,14):
                self.text(73,y,line,14); y-=20
        parts=c.get("parts",[])
        if not parts:
            self.text(73,y-15,"Located connection specification. Plate, fastener and weld geometry has not been supplied.",15,color=RED,bold=True)
        # Project the supplied part geometry onto three orthogonal planes, with
        # receiver arms at the actual workpoint for an undeveloped joint.
        outlines=[]
        for part in parts:
            if part["kind"]=="plate":
                ring=part["outline"]; normal=plane(ring)[3]; h=part["thickness_mm"]
                for ring in [ring,*part.get("openings",[])]:
                    top=[[p[i]+normal[i]*h for i in range(3)] for p in ring]
                    outlines.extend([(ring,True),(top,True)])
                    outlines.extend([([a,b],False) for a,b in zip(ring,top)])
            else:
                a,b=part["start"],part["end"]; xvec,yvec,_=frame(a,b,part.get("ref_direction"))
                if part["kind"]=="bolt":
                    r=part["diameter_mm"]/2
                    points=[(r*math.cos(i*math.tau/24),r*math.sin(i*math.tau/24)) for i in range(24)]
                else:
                    leg=part["leg_mm"]; points=[(0.,0.),(leg,0.),(0.,leg)]
                rings=[[[p[i]+x*xvec[i]+v*yvec[i] for i in range(3)] for x,v in points] for p in (a,b)]
                outlines.extend([(ring,True) for ring in rings])
                outlines.extend([([a_,b_],False) for a_,b_ in zip(*rings)])
        if not outlines:
            lines=[]
            for mid in c["members"]:
                m=self.members[mid]; a,b=m["start"],m["end"]
                # Only a finite portion of the actual receiving axis is shown.
                delta=[b[i]-a[i] for i in range(3)]; length=math.hypot(*delta)
                station=sum((c["at"][i]-a[i])*delta[i] for i in range(3))/length**2
                center=max(0,min(1,station)); spread=min(.5,700/length)
                pa,pb=max(0,center-spread),min(1,center+spread)
                lines.append(([[a[i]+f*delta[i] for i in range(3)] for f in (pa,pb)],False))
            outlines=lines
        for j,axes in enumerate(((0,1),(0,2),(1,2))):
            k,l=axes; pts=[(p[k],p[l]) for ring,_ in outlines for p in ring]
            pts.append((c["at"][k],c["at"][l]))
            ranges=bounds(pts); x=83+j*(W-135)/3
            den,s,off=fit(ranges,(x+40,530,(W-300)/3,420))
            detail["projections"].append(dict(axes=axes,origin_pt=off,points_per_mm=s))
            def tr(p): return [off[0]+p[k]*s,off[1]+p[l]*s]
            for ring,closed in outlines:
                xy=[tr(p) for p in ring]
                if closed:self.polyline(xy,INK,.8)
                else:self.line(xy[0],xy[-1],BLUE,.85)
            q=tr(c["at"]); self.line([q[0]-5,q[1]],[q[0]+5,q[1]],RED,.8); self.line([q[0],q[1]-5],[q[0],q[1]+5],RED,.8)
            if parts:
                low=[r[0] for r in ranges]; high=[r[1] for r in ranges]
                a=[off[i]+low[i]*s for i in (0,1)]
                for i in (0,1):
                    b=a.copy(); b[i]=off[i]+high[i]*s
                    self.dimension(a,b,high[i]-low[i],-22 if i==0 else 22,dict(kind="assembly_envelope",connection=c["id"],axis=axes[i]))
            self.text(x,455,f"{'XYZ'[k]}-{'XYZ'[l]} projection   /   1:{den}",14,bold=True)
        if parts:
            rows=[]
            for p in parts:
                dims=(f"thickness {printed(p['thickness_mm'])} mm" if p["kind"]=="plate" else
                      f"diameter {printed(p['diameter_mm'])} mm" if p["kind"]=="bolt" else f"leg {printed(p['leg_mm'])} mm")
                location=("Outline "+ " / ".join(coord(pt) for pt in p["outline"]) if p["kind"]=="plate" else
                          f"{coord(p['start'])} to {coord(p['end'])} / length {printed(round(math.dist(p['start'],p['end']),2))} mm")
                rows.append((p["id"],p["kind"],p["material"],dims,location))
            self.table(number+"-P","Connection part schedule  /  "+c["id"],"parts",[("Part",.16),("Kind",.1),("Material",.15),
                       ("Selected dimension",.17),("Representative global set-out X, Y, Z (mm)",.42)],rows)

    def generate(self):
        self.basis(); self.composite()
        for unit in self.data.get("units",[]) or [None]:
            self.framing(unit)
        self.schedules(); self.sections(); self.connections()
        self.c.save()
        return dict(schema_version="1.0",project_id=self.job["id"],source_sha256=self.digest,
                    sheets=self.sheets,views=self.views,dimensions=self.dimensions,marks=self.marks,
                    member_schedule=self.member_rows,connection_details=self.detail_register,design_status=self.design_status,
                    units=self.data.get("units",[]),separation_joints=self.gaps,interunit_plate_clashes=self.clashes,
                    bolt_plate_fit=self.bolt_fit)


def write_drawings(data,digest,target,gaps=(),clashes=(),bolt_fit=None):
    from .bolt_fit import from_source
    return Sheets(data,digest,target,gaps,clashes,bolt_fit or from_source(data)).generate()
