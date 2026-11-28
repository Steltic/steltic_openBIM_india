"""Prepare public calculation reports and physical/analytical views at the existing site routes."""

import argparse
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
from string import Template
import tarfile
from urllib.parse import urlsplit, unquote

from scene import digest


HERE = Path(__file__).resolve().parent
ASSET = PurePosixPath("solutions_india/openbim")
VALIDATED_REVISION = "b566ee4913989b0bc4ba58926b6162d7ed50640f"
REPO = "https://github.com/Steltic/steltic_openBIM_india"
PROOF = f"{REPO}/blob/{VALIDATED_REVISION}/validation"
MATHJAX_TGZ = "1b9c0a1c44df864e915690558e72adb9cc5203360daefd385084ced3b6c64c09"
DOWNLOAD_FIELDS = ("std", "reactions", "bom", "anchors")
ASSET_NAMES = {"model.std", "design/anchor_bolt_plan.svg", "design/bom.csv", "design/reactions.csv"}
HR_TITLES = (
    "Factory portal shed, Bengaluru",
    "Multi-span logistics warehouse, Bhiwandi",
    "Crane shed, Nagpur",
    "Fulfilment warehouse, Farrukhnagar",
    "Rooftop solar retrofit, Bengaluru",
    "Warehouse and storage mezzanine, Hyderabad",
    "Industrial crane bay, Visakhapatnam",
    "Industrial portal shed, Chennai",
    "Warehouse and lean-to office, Shimla",
    "Retail hall, Indore",
    "Office and workshop, Jaipur",
    "Three-wing school, Chandigarh",
    "Five-storey office, New Delhi",
    "Eight-storey hospital, Kolkata",
    "Stepped office, Pune",
    "Nine-storey office, Mumbai",
    "Laboratory and office, Ahmedabad",
    "Podium office, Kochi",
    "Residential towers, Guwahati",
    "Eighteen-storey office tower, Noida",
    "Angle-truss shed, Hosur",
)


def read(path):
    return json.loads(path.read_bytes())


def relative(target, parent):
    return posixpath.relpath(str(target), str(parent))


def write(target, text):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf8", newline="\n")


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.relative = set()

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k not in ("href", "src") or not v:
                continue
            link = urlsplit(v)
            if link.netloc or link.scheme in ("http", "https", "data", "mailto") or not link.path:
                continue
            name = unquote(link.path)
            if (
                ".." in PurePosixPath(name).parts
                or name.startswith(("/", "\\"))
                or "\\" in name
                or link.scheme
            ):
                raise ValueError(f"Unexpected native dependency: {v}")
            self.relative.add(name)


def allowed_asset(name):
    parts = PurePosixPath(name).parts
    return (
        name in ASSET_NAMES
        or len(parts) == 2
        and parts[0] == "figs"
        and PurePosixPath(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".webp"}
    )


def runtime(args):
    root = args.stage / ASSET
    for name in ("model.js", "model.css", "report.css"):
        copy(HERE / name, root / name)
    if digest(args.mathjax) != MATHJAX_TGZ:
        raise ValueError("Use the published npm archive mathjax-3.2.2.tgz")
    with tarfile.open(args.mathjax, "r:gz") as package:
        for key, dest in [
            ("package/es5/tex-svg-full.js", "tex-svg-full.js"),
            ("package/LICENSE", "LICENSE.txt"),
        ]:
            target = root / "mathjax" / dest
            target.parent.mkdir(exist_ok=True)
            with package.extractfile(key) as source, target.open("wb") as stream:
                shutil.copyfileobj(source, stream)
    copy(args.validation / "hr/IN_Ex5/solar-installer-note.pdf", root / "solar-installer-note.pdf")
    return {
        ASSET / name
        for name in (
            "model.js",
            "model.css",
            "report.css",
            "mathjax/tex-svg-full.js",
            "mathjax/LICENSE.txt",
            "solar-installer-note.pdf",
        )
    }


def archive_url(case):
    return f"https://raw.githubusercontent.com/Steltic/steltic_openBIM_india/{VALIDATED_REVISION}/validation/{case['archive']}"


def notes(case, unit):
    identity = case["id"]
    if identity == "IN_Ex12" and unit == "Gym":
        yield "The native serviceability review flags footfall vibration. Confirm which occupied floor and supporting members are in scope before closing that item for the gym."
    if identity == "IN_Ex21":
        yield "The 18 longitudinal CHS 168.3 × 8 ties are each 6 m long. Their native analysis force is zero. Verify the required restraint force and its transfer into the supporting connections."
    if (identity == "IN_Ex12" and unit == "Link") or identity in ("IN_Ex16", "IN_Ex18"):
        thickness = 500 if identity == "IN_Ex18" else 470
        yield f"The modeled fixed bases rely on {thickness} mm finished weldments, qualified full-depth welds and 40 anchors. Confirm the 4.5 m embedment, anchor-group resistance, pedestal, grout and foundation capacity before crediting base fixity."
    if identity == "IN_Ex15":
        yield "The issued Pune design includes a companion run with 100% of the imposed floor loads across the stepped column stacks."
    for joint in case["measured_joints"]:
        yield f"The complete-building IFC records {joint['ifc_gap_mm']:g} mm clear at separation joint {joint['id']}. The two sides are independent structural units."


def report_header(case, row, destination, directory, val, companion):
    unit = row["unit"]
    module = case["module"].lower()

    def link(path):
        return escape(relative(path, directory), quote=True)

    panel = case["coordination"]
    title = "Building coordination requires review"
    sections = []
    if companion:
        sections.append(
            "This companion report covers the hot-rolled lateral frame within the cold-formed building."
        )
    else:
        sections.append("The native design calculation is complete for this structural unit.")
    if panel == "fail":
        failure = next(c for c in case["outstanding_checks"] if c["status"] == "fail")
        pv = read(val / "hr/IN_Ex5/solar-capacity.json")
        title = f"Proposed PV loading fails the purlin check · D/C {failure['utilization']:.3f}"
        sections += [
            f"The proposed {pv['covered_load_kNm2']:g} kN/m² array covers 75% of the roof. {pv['proposed_failure_count']} purlins exceed their IS 801 limit. The primary frame was checked separately at the area-averaged load of {pv['average_frame_load_kNm2']:g} kN/m².",
            f"With the existing sections, the last passing uniform-load trial was {pv['last_passing_kNm2']:g} kN/m² and the first failing trial was {pv['first_failing_kNm2']:g} kN/m². Strengthening or a revised array requires a further design check.",
        ]
    sections.extend(notes(case, unit))
    engineering = "".join(f"<p>{escape(s)}</p>" for s in sections)
    download = escape(archive_url(case), quote=True)
    links = [
        f'<a class="current-model" href="{link(destination / "viewer_3d.html")}">Physical model</a>',
        f'<a href="{link(destination / "analysis.html")}">Analytical view</a>',
    ]
    if companion:
        links.append(f'<a href="{link(destination / "report.html")}">Parent design report</a>')
    links.append(f'<a href="{download}">Download IFC and {case["sheets"]:,} drawing sheets (ZIP)</a>')
    if panel == "fail":
        links.append(
            f'<a href="{link(ASSET / "solar-installer-note.pdf")}">PV assessment for the installer (PDF)</a>'
        )
    links.append(f'<a href="{PROOF}/{case["native_evidence"]}">Design evidence</a>')
    out = case["outstanding_checks"]
    items = "".join(
        f'<li><strong>{escape(v["status"].capitalize())}</strong> · {escape(v["description"].replace("supplier and foundation EOR", "the supplier and the engineer responsible for the foundations"))}'
        + (f' · D/C {v["utilization"]:.3f}' if isinstance(v.get("utilization"), (int, float)) else "")
        + "</li>"
        for v in out
    )
    assumptions = "".join(f"<li>{escape(a)}</li>" for a in case["declared_assumptions"])
    joints = case["located_joints_without_parts"]
    counts = case["design_check_counts"]
    summary = ", ".join(
        f"{counts[k]} {label}"
        for k, label in [("pass", "passed"), ("review", "for review"), ("fail", "failed")]
        if counts.get(k)
    )
    return (
        f'<section id="coordination" class="publication {panel}" aria-label="Issued design and building coordination"><h2>{title}</h2>{engineering}'
        f'<p class="minor">Whole-building coordination checks: {summary}. Connections awaiting shop geometry: {joints:,}.</p><nav>{"".join(links)}</nav>'
        f"<details><summary>Open checks and assumptions for the whole building</summary><ul>{items}</ul><h3>Design assumptions</h3><ul>{assumptions}</ul></details>"
        f'<p class="minor">{escape(case["id"])} · {escape(unit)} · <a href="{PROOF}/{module}/README.md">Reproduce the native calculation</a></p></section>'
    )


def prepare_report(args, case, row, src, dest, parent, companion=False):
    native = (src / "report.html").read_text("utf8")
    written = {dest / "report.html"}
    parser = Links()
    parser.feed(native)
    parser.close()
    for path in parser.relative:
        if allowed_asset(path):
            copy(src / path, args.stage / dest / path)
            written.add(dest / path)
        elif path in {"report.html", "viewer_3d.html"}:
            continue
        elif (
            not companion
            and row.get("native_lateral_folder")
            and path
            == relative(PurePosixPath(row["native_lateral_folder"]) / "report.html", row["native_folder"])
        ):
            continue
        else:
            raise ValueError(f"Unexpected native report attachment: {src.name}/{path}")
    assets = relative(ASSET, dest)
    native = native.replace(
        "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js", assets + "/mathjax/tex-svg-full.js"
    )
    native = native.replace(
        "</head>",
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="{assets}/report.css"></head>',
        1,
    )
    # Retain every native technical table, numerical result and activity-log entry.
    label = "Native lateral-frame calculation" if companion else "Native calculation"
    native = native.replace("Design status: COMPLETE", label + ": COMPLETE").replace(
        "Design status: <b>COMPLETE", label + ": <b>COMPLETE"
    )
    native = native.replace("<b>Headline:</b>", "<b>Native member checks:</b>", 1)
    old = " not found -- write the building&#x27;s cfg (including any custom_build) to FIRST and keep it; the saved OpenSees model must be reproducible and editable for later studies."
    family = case["module"].lower()
    native = native.replace(
        old,
        f'The per-job editable input file was absent in the native check. The versioned input recipe and replay procedure are available in the <a href="{PROOF}/{family}/README.md">design reproduction guide</a>.',
    )
    content, n = re.subn(
        r"</h1>",
        lambda m: m.group() + report_header(case, row, parent, dest, args.validation, companion),
        native,
        count=1,
        flags=re.I,
    )
    if n != 1:
        raise ValueError("Expected one report heading")
    if case["coordination"] == "fail":
        content = content.replace("<title>", "<title>PV assessment fails · ", 1)
    write(args.stage / dest / "report.html", content)
    return written


def redirect(target, parent):
    url = escape(relative(target, parent), quote=True)
    return f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Current frame calculation · Steltic India</title><meta http-equiv="refresh" content="0;url={url}"><a href="{url}">Open the current frame calculation</a></html>\n'


def analytical_page(source, target, parent_link, case):
    content = source.read_bytes().decode("utf8")
    nav = (
        f'<nav class="publication-links" aria-label="Example documents"><a href="{parent_link}">Physical model</a>'
        ' · <a href="report.html">Design report</a>'
    )
    if case["coordination"] == "fail":
        nav += '<br><a class="pv-decision" href="report.html#coordination">Proposed PV purlin loading fails · D/C 1.025</a>'
    nav += "</nav>"
    is_portal = case["id"] == "IN_CFS_Ex3"
    anchor = "</header>" if is_portal else '<div class="modelline" id="modelLine"></div>'
    if content.count(anchor) != 1:
        raise ValueError(f"Unexpected analytical viewer navigation layout: {source.name}")
    color = "#175b57" if is_portal else "#aadaea"
    meta = f'<meta name="steltic-native-viewer-sha256" content="{digest(source)}">'
    css = f"<style>.publication-links{{font:600 12px/1.6 system-ui,sans-serif;margin:5px 0}}.publication-links a{{color:{color}}}.publication-links .pv-decision{{color:#ffd1a5}}</style>"
    if 'name="viewport"' not in content and "name='viewport'" not in content:
        meta += '<meta name="viewport" content="width=device-width,initial-scale=1">'
    content = content.replace("</head>", meta + css + "</head>", 1)
    content = content.replace(anchor, nav + anchor if is_portal else anchor + nav, 1)
    # Keep the native embedded scripts, including their line endings, byte-identical.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf8"))


def validate_route(row, family):
    paths = {
        k: PurePosixPath(v) for k, v in row.items() if k.endswith("folder") or k in ("report", "viewer")
    }
    for k, path in paths.items():
        if str(path) != row[k] or not all(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", bit) for bit in path.parts
        ):
            raise ValueError(f"Invalid public path in route map: {row[k]}")
    dest = paths["public_folder"]
    source = paths["native_folder"]
    if (
        dest.parts[:2] != ("solutions_india", family.lower())
        or len(dest.parts) < 3
        or source.parts[:2] != (family, row["id"])
    ):
        raise ValueError("Unexpected website or native directory")
    if paths["report"] != dest / "report.html" or paths["viewer"] != dest / "viewer_3d.html":
        raise ValueError("The public report and viewer must belong to the same structural unit")
    if "native_lateral_folder" in paths:
        for k, base in [
            ("native_lateral_folder", source),
            ("fresh_lateral_folder", dest),
            ("existing_lateral_folder", dest),
        ]:
            if paths[k].parent != base / "lateral":
                raise ValueError("Unexpected companion report directory")


def prepare(args):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .·/-]{0,119}", args.revision):
        raise ValueError("Specify a short publication revision")
    cases = {c["id"]: c for c in read(args.validation / "acceptance.json")["cases"]}
    routes = read(args.routes)
    expected = {(c["id"], u) for c in cases.values() for u in c["native"]}
    if len(routes) != len(expected) or {(r["id"], r["unit"]) for r in routes} != expected:
        raise ValueError("Map every independently calculated unit exactly once")
    for root in (
        args.validation,
        args.hr_jobs,
        args.cfs_jobs,
        args.hr_views,
        args.cfs_views,
        args.catalogs,
    ):
        if args.stage.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(
            args.stage.resolve()
        ):
            raise ValueError("Use a separate publication directory")
    written = runtime(args)
    catalog = {}
    for family in ("hr", "cfs"):
        q = PurePosixPath("solutions_india") / family / "index.json"
        copy(args.catalogs / q, args.stage / q)
        written.add(q)
        for entry in read(args.stage / q)["examples"]:
            catalog[str(q.parent / entry["report"])] = entry
    template = Template((HERE / "physical.html").read_text("utf8"))
    for row in routes:
        case = cases[row["id"]]
        family = case["module"]
        unit = row["unit"]
        validate_route(row, family)
        base = args.hr_jobs if family == "HR" else args.cfs_jobs
        source = base.joinpath(*PurePosixPath(row["native_folder"]).parts[1:])
        dest = PurePosixPath(row["public_folder"])
        entry = catalog[row["report"]]
        if (
            digest(source / "report.html") != entry["native_report_sha256"]
            or entry["handoff_sha256"] != case["sha256"]["handoff.json"]
        ):
            raise ValueError(f"{dest}: native report or issued handoff digest mismatch")
        written.update(prepare_report(args, case, row, source, dest, dest))
        for k in DOWNLOAD_FIELDS:
            if k in entry:
                attachment = relative(PurePosixPath("solutions_india") / family.lower() / entry[k], dest)
                if attachment not in ASSET_NAMES:
                    raise ValueError(f"Unsupported report download {attachment}")
                copy(source / attachment, args.stage / dest / attachment)
                written.add(dest / attachment)
        scene = ASSET / f'{case["id"]}-{unit}.glb'
        if not (args.stage / scene).is_file():
            raise FileNotFoundError(scene)
        written.add(scene)
        title = HR_TITLES[case["number"] - 1] if family == "HR" else entry["title"].split(" · ", 1)[-1]
        info = {
            "title": title,
            "case_display": f"{family} example {case['number']}",
            "unit_display": "Main structure" if unit == "Main" else unit,
            "case": case["id"],
            "unit": unit,
            "family": "Hot-rolled steel" if family == "HR" else "Cold-formed steel",
            "assets": relative(ASSET, dest),
            "scene": relative(scene, dest),
            "home": relative("india.html", dest),
            "download": archive_url(case),
            "status": case["coordination"],
            "decision": (
                "PV purlin check fails · D/C 1.025"
                if case["coordination"] == "fail"
                else "Coordination under review"
            ),
            "analysis_label": (
                "Portal elevation & checks" if case["id"] == "IN_CFS_Ex3" else "Analytical model"
            ),
        }
        write(
            args.stage / dest / "viewer_3d.html",
            template.substitute({k: escape(v, quote=True) for k, v in info.items()}),
        )
        written.add(dest / "viewer_3d.html")
        if not args.pages_only:
            analysis = (
                args.hr_views / case["id"] / (unit + ".html")
                if family == "HR"
                else args.cfs_views / case["id"] / "viewer_3d.html"
            )
            analytical_page(analysis, args.stage / dest / "analysis.html", "viewer_3d.html", case)
            written.add(dest / "analysis.html")
        if row.get("native_lateral_folder"):
            short = PurePosixPath(row["fresh_lateral_folder"])
            historical = PurePosixPath(row["existing_lateral_folder"])
            subdir = short.relative_to(dest)
            written.update(prepare_report(args, case, row, source / subdir, short, dest, True))
            if not args.pages_only:
                analytical_page(
                    args.cfs_views / case["id"] / subdir / "viewer_3d.html",
                    args.stage / short / "viewer_3d.html",
                    relative(dest / "viewer_3d.html", short),
                    case,
                )
                written.add(short / "viewer_3d.html")
            if short != historical:
                for n in ("report.html", "viewer_3d.html"):
                    write(args.stage / historical / n, redirect(short / n, historical))
                    written.add(historical / n)
    if not args.pages_only:
        actual = {
            PurePosixPath(p.relative_to(args.stage).as_posix())
            for p in (args.stage / "solutions_india").rglob("*")
            if p.is_file()
        }
        if actual != written:
            raise ValueError(
                f"Unexpected or missing files in the staging directory: {sorted(actual ^ written)[:8]}"
            )
        rows = [{"path": str(p), "sha256": digest(args.stage / p)} for p in sorted(written)]
        write(
            args.stage / "publication.json",
            json.dumps({"revision": args.revision, "files": rows}, indent=2) + "\n",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in (
        "validation",
        "routes",
        "catalogs",
        "hr-jobs",
        "cfs-jobs",
        "hr-views",
        "cfs-views",
        "stage",
        "mathjax",
    ):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument(
        "--pages-only",
        action="store_true",
        help="Prepare reports and physical viewers ahead of the native analyst views. Omit for the final manifest.",
    )
    prepare(parser.parse_args())
