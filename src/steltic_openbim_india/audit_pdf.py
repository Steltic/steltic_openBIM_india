"""Read actual PDF operators, printed schedules and a raster of every page."""
from collections import Counter, defaultdict
import math
import re

import numpy as np
import pymupdf

from .audit_details import check_detail


POINT_TOL = .12


def normal(text):
    return " ".join(text.replace("\u2013", "-").replace("\u2212", "-").split()).casefold()


def schedule_rows(page, kind):
    """Read data by its printed row baseline and column positions in the PDF."""
    spans = [s for b in page.get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]]
    headings = {s["text"]:s["origin"][0] for s in spans if 130 < s["origin"][1] < 160}
    titles = {"checks":["Check ID","Calculation or open item","Status","Utilization","Source reference"],
              "members":["Mark","Role","Start section","End section if tapered","Material","Count","Min length (mm)","Max length (mm)"],
              "preparation":["Member occurrence","Start cutback (mm)","End cutback (mm)","Physical length (mm)","Operations","Set-out"],
              "machining":["Set-out","Operation","Tool","Diameter or depth (mm)","Local X, Y, Z (mm)"]}[kind]
    starts = [headings[t] for t in titles] + [page.rect.width-45]
    cols = [[] for _ in titles]
    for span in spans:
        x, y = span["origin"]
        if 160 < y < page.rect.height-125:
            for i, (a,b) in enumerate(zip(starts, starts[1:])):
                if a-.5 <= x < b-.5:
                    cols[i].append((y,span["text"].strip()))
                    break
    anchor = cols[2] if kind == "checks" else cols[1] if kind in ("preparation","machining") else cols[0]
    starts_y = sorted(y for y,t in anchor if kind != "checks" or normal(t) in ("pass","fail","review"))
    result = {}
    for lo, hi in zip(starts_y, starts_y[1:]+[page.rect.height-124]):
        cells = ["".join(t for y,t in sorted(column) if lo-.4 <= y < hi-.4) for column in cols]
        result[(cells[0],cells[1]) if kind=="machining" else cells[0]] = cells
    return result


class Strokes:
    """Index PDF line segments by first endpoint in bottom-left PDF coordinates."""
    def __init__(self, page):
        self.height = page.rect.height
        self.edges = defaultdict(list)
        self.total = 0
        for path in page.get_drawings():
            for item in path["items"]:
                if item[0] == "l":
                    self.add(item[1],item[2])
                elif item[0] == "re":
                    r = item[1]
                    for a,b in [(r.tl,r.tr),(r.tr,r.br),(r.br,r.bl),(r.bl,r.tl)]:
                        self.add(a,b)
                elif item[0] == "qu":
                    q = item[1]
                    for a,b in ((q.ul,q.ur),(q.ur,q.lr),(q.lr,q.ll),(q.ll,q.ul)):
                        self.add(a,b)

    def add(self, first, second):
        a = (first.x,self.height-first.y)
        b = (second.x,self.height-second.y)
        self.total += 1
        for p,q in ((a,b),(b,a)):
            self.edges[(math.floor(p[0]),math.floor(p[1]))].append((p,q))

    def has(self, a, b):
        for x in range(math.floor(a[0]-POINT_TOL),math.floor(a[0]+POINT_TOL)+1):
            for y in range(math.floor(a[1]-POINT_TOL),math.floor(a[1]+POINT_TOL)+1):
                for p,q in self.edges.get((x,y), ()):
                    if math.dist(a,p)<=POINT_TOL and math.dist(b,q)<=POINT_TOL:
                        return True
        return False


def audit_pdf(source, path, register, expect):
    members = {r["id"]:r for r in source["members"]}
    groups = register.get("member_schedule", [])
    marks = register.get("marks", {})
    expect(set(marks)==set(members), "occurrence to drawing mark", "register")
    expected_marks = Counter(marks.values())
    expect({r["mark"]:r["count"] for r in groups}==dict(expected_marks),"member schedule quantities","register")
    by_mark = defaultdict(list)
    for uid, mark in marks.items():
        if uid in members:
            by_mark[mark].append(members[uid])
    for row in groups:
        group = by_mark[row["mark"]]
        lengths = [math.dist(m["start"],m["end"]) for m in group]
        expect(group and all(row["profile"]==m["profile"] and row["material"]==m["material"] and
               row["role"]==m["role"] and (row.get("end_profile") or m["profile"])==(m.get("end_profile") or m["profile"]) for m in group),
               "mark selected properties",row["mark"])
        if lengths:
            expect(abs(min(lengths)-row["min_length_mm"])<.02 and abs(max(lengths)-row["max_length_mm"])<.02,"mark cut lengths",row["mark"])
    by_sheet, dim_sheets = defaultdict(list), defaultdict(list)
    for view in register.get("views",[]):
        by_sheet[view["sheet"]].append(view)
    for dim in register.get("dimensions",[]):
        dim_sheets[dim["sheet"]].append(dim)
    all_views = set()
    datums = [{r["id"]:r["coordinate_mm"] for r in source["grids"][axis]} for axis in ("x","y")]
    datums.append({r["id"]:r["elevation_mm"] for r in source["levels"]})
    panels={r["id"]:r for r in source.get("panels",[])}
    text_pages = []
    details = {r["sheet"]:r for r in register.get("connection_details",[])}
    joints = {c["id"]:c for c in source.get("connections",[])}
    represented = [occ for d in details.values() for occ in d["occurrences"]]
    expect(Counter(represented)==Counter(joints.keys()),"connection detail occurrence coverage","register")
    detail_edges = 0
    tables = {"checks": {}, "members": {}, "preparation":{}, "machining":{}}
    banner = {"pass":"source checks pass / design coordination", "review":"design review / coordination candidate",
              "fail":"design fail / coordination candidate"}[register["design_status"]]
    drawn_lines = measured = raster_pages = 0
    with pymupdf.open(path) as doc:
        sheets = register["sheets"]
        expect(len(doc)==len(sheets) and len(set(r["number"] for r in sheets))==len(sheets), "PDF page and sheet count","register")
        for i,page in enumerate(doc):
            if i >= len(sheets):
                break
            row = sheets[i]
            sheet = row["number"]
            text = normal(page.get_text())
            text_pages.append((row["kind"],text))
            expect(row["page"]==i+1 and normal(sheet) in text and normal(row["title"]) in text, "printed sheet identity",sheet)
            expect(banner in text and register["source_sha256"][:20] in text,"printed engineering status and revision",sheet)
            if row["kind"] in tables:
                tables[row["kind"]].update(schedule_rows(page,row["kind"]))
            for block in page.get_text("blocks"):
                if block[0]<-.2 or block[1]<-.2 or block[2]>page.rect.width+.2 or block[3]>page.rect.height+.2:
                    expect(False,"text outside crop",sheet)
                    break
            pixel = page.get_pixmap(matrix=pymupdf.Matrix(.24,.24),colorspace=pymupdf.csGRAY,alpha=False)
            ink = float(np.count_nonzero(np.frombuffer(pixel.samples,dtype=np.uint8)<200)) / (pixel.width*pixel.height)
            expect(.0005 < ink < .95, "rendered sheet ink coverage",sheet)
            raster_pages += 1
            if not by_sheet[sheet] and not dim_sheets[sheet] and sheet not in details:
                continue
            strokes = Strokes(page)
            expect(strokes.total > 0, "vector sheet content",sheet)
            if sheet in details:
                detail = details[sheet]
                detail_edges += check_detail(joints[detail["representative"]],detail,strokes,expect,members)
            for view in by_sheet[sheet]:
                axes,origin,k = view["axes"],view["origin_pt"],view["points_per_mm"]
                expect(k>0,"positive drawing scale",sheet)
                def project(point):
                    return [origin[j]+k*point[axis] for j,axis in enumerate(axes)]
                for mid in view["member_ids"]:
                    if mid not in members:
                        expect(False,"drawing member missing at source",mid)
                        continue
                    m = members[mid]
                    a,b = project(m["start"]),project(m["end"])
                    all_views.add(mid)
                    if math.dist(a,b) < .02:
                        continue
                    expect(strokes.has(a,b),"drawn member line",f"{sheet} / {mid}")
                    expect(all(-POINT_TOL<=p[0]<=page.rect.width+POINT_TOL and -POINT_TOL<=p[1]<=page.rect.height+POINT_TOL for p in (a,b)),
                           "drawn member inside sheet", f"{sheet} / {mid}")
                    drawn_lines += 1
                for pid in view.get("panel_ids",[]):
                    p=panels[pid]
                    for ring in [p["outline"],*p.get("openings",[])]:
                        for first,last in zip(ring,ring[1:]+ring[:1]):
                            a,b=project(first),project(last)
                            if math.dist(a,b)>.02:
                                expect(strokes.has(a,b),"drawn panel edge or opening",f"{sheet} / {pid}")
            for dim in dim_sheets[sheet]:
                start,end = dim["line_pt"]
                witness_a,witness_b = dim["witnesses_pt"]
                subject=f"{sheet} / {dim['id']}"
                expect(strokes.has(start,end) and strokes.has(witness_a,start) and strokes.has(witness_b,end)
                       and normal(dim["text"]) in text, "printed dimension text, witnesses and vector",subject)
                origin=dim["source"]
                if origin["kind"].startswith("datum_"):
                    axis=origin["axis"]
                    delta=abs(datums[axis][origin["start"]]-datums[axis][origin["end"]])
                    expect(abs(delta-dim["value_mm"])<.02 and any(abs(math.dist(start,end)/v["points_per_mm"]-delta)<.02 for v in by_sheet[sheet]),
                           "dimension against source datums and drawing scale",subject)
                elif origin["kind"] in ("section_width","section_depth"):
                    profile=source["profiles"][origin["profile"]]
                    dims=profile.get("dimensions_mm",{})
                    index=int(origin["kind"]=="section_depth")
                    if "contours_mm" in profile:
                        coords=[p[index] for ring in profile["contours_mm"] for p in ring]
                        delta=max(coords)-min(coords)
                    elif profile["family"] in ("ROD","CHS"):
                        delta=dims.get("diameter",dims.get("d"))
                    elif index:
                        delta=dims.get("d",dims.get("t"))
                    elif profile["family"]=="Z":
                        delta=2*dims["b"]-dims.get("tw",dims.get("t"))
                    else:
                        delta=dims["b"]
                    expect(abs(delta-dim["value_mm"])<.02,"dimension against section envelope",subject)
                expect(abs(float(dim["text"].replace(",",""))-dim["value_mm"])<=.011,"dimension printed value",subject)
                measured += 1
    expect(all_views==set(members), "member coverage across views","register")
    for row in groups:
        cells = tables["members"].get(row["mark"])
        expect(cells and cells[2] == row["profile"] and cells[3] == (row.get("end_profile") or "-")
               and cells[4] == row["material"] and int(cells[5]) == row["count"] and
               abs(float(cells[6])-row["min_length_mm"])<=.051 and abs(float(cells[7])-row["max_length_mm"])<=.051,
               "printed member schedule",row["mark"])
    for check in source.get("checks",[]):
        cells = tables["checks"].get(check["id"])
        dc = check.get("utilization")
        expect(cells and cells[2].lower() == check["status"] and
               (cells[3]=="-" if dc is None else abs(float(cells[3])-dc)<=.000051), "printed calculation decision and value",check["id"])
    for m in members.values():
        if not (m.get("member_voids") or m.get("end_cutbacks_mm")):
            continue
        cells=tables["preparation"].get(m["id"])
        cuts=m.get("end_cutbacks_mm",[0.,0.])
        length=math.dist(m["start"],m["end"])-sum(cuts)
        features=m.get("member_voids",[])
        if not cells:
            expect(False,"printed member preparation",m["id"])
            continue
        expect(np.allclose([float(v) for v in cells[1:5]],[*cuts,length,len(features)],atol=.00006,rtol=0),
               "physical length, cutbacks and machining count on PDF",m["id"])
        z=np.asarray(m["end"])-np.asarray(m["start"]);z=z/np.linalg.norm(z)
        ref=np.asarray(m.get("ref_direction",(-z[1],z[0],0.) if math.hypot(z[0],z[1])>1e-9 else (1.,0.,0.)))
        x=ref-np.dot(ref,z)*z;x=x/np.linalg.norm(x)
        mat=np.asarray([x,np.cross(z,x),z])
        required=[]
        for f in features:
            pts=([f["start"],f["end"]] if f["kind"]=="bore" else
                 [pt for ring in [f["outline"],*f.get("openings",[])] for pt in ring])
            coords=[round(float(v),2) for pt in pts for v in (mat@(np.asarray(pt)-m["start"]))]
            required.append((f["kind"],round(f.get("diameter_mm",f.get("thickness_mm")),2),*coords))
        actual=[]
        for i in range(1,len(features)+1):
            operation=tables["machining"].get((cells[5],str(i)))
            if operation:
                values=[float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+)",operation[4])]
                actual.append((operation[2],float(operation[3]),*values))
        a,b=sorted(actual),sorted(required)
        expect(len(a)==len(b) and all(p[0]==q[0] and len(p)==len(q) and np.allclose(p[1:],q[1:],atol=.011,rtol=0)
                                      for p,q in zip(a,b)), "printed machining features in member axes",m["id"])
    return dict(sheets=len(text_pages), sheet_types=dict(Counter(kind for kind,_ in text_pages)), rasterized_pages=raster_pages,
                projected_member_lines=drawn_lines, dimension_lines=measured, represented_member_ids=len(all_views),
                connection_projection_edges=detail_edges)
