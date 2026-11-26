"""Compare frozen independent India jobs with the owner's published design reports.

This is a post-design operation. The upstream design runners never import it.
Supply the two official solutions_india/*/index.json files and their report
trees; no downloaded report or licensed calculation excerpt is republished.
"""
import argparse
import gzip
import hashlib
from html import unescape
import json
from pathlib import Path
import re


ROOT=Path(__file__).resolve().parents[1]


def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def digest(p):
    hashed=hashlib.sha256()
    opener=gzip.open if p.suffix==".gz" else open
    with opener(p,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            hashed.update(block)
    return hashed.hexdigest()


def cells(markup):
    return [" ".join(unescape(re.sub(r"<[^>]*>"," ",t)).split()) for t in re.findall(r"<t[dh](?:\s[^>]*)?>(.*?)</t[dh]>",markup,re.I|re.S)]


def printed_strength(path):
    markup=path.read_text(encoding="utf-8-sig")
    for tr in re.findall(r"<tr(?:\s[^>]*)?>(.*?)</tr>",markup,re.I|re.S):
        row=cells(tr)
        if len(row)>=4 and row[0].casefold().startswith(("strength, members","strength, cold-formed members")) and re.fullmatch(r"\d+\.?\d*",row[1]):
            member=row[4].split(": ",1)[0] if "cold-formed" in row[0].casefold() and len(row)>4 else row[3]
            return {"dc":float(row[1]),"member":member}
    return None


def reference(row,report):
    strength=(row.get("headline") or {}).get("strength") or {}
    data={"native_status":row["status"].lower(),"strength_dc":strength.get("dc"),"governing_member":strength.get("member")}
    printed=printed_strength(report)
    if printed:
        data.update(strength_dc=printed["dc"],governing_member=printed["member"])
    if data["strength_dc"] is None:
        match=re.search(r"worst strength ratio\s+([.\d]+)\s*[—–-]\s*([^;(·]+)",row.get("meta",""),re.I)
        if match:
            data.update(strength_dc=float(match[1]),governing_member=match[2].strip())
    kg=re.search(r"(\d+(?:\.\d+)?)\s*kg/m²",row.get("meta",""))
    if kg:
        data["takeoff_kg_m2"]=float(kg[1])
    frame=(row.get("frame_headline") or {}).get("strength") or {}
    if frame.get("dc") is not None:
        data["hr_frame_strength_dc"]=frame["dc"]
    return data


def fresh_from_job(path,family):
    name="calc_package.json" if family=="hr" else "calc_package_cfs.json"
    pkg=read(path/"design"/name)
    st=pkg.get("design_status",{})
    headline=read(path/"design/headline.json") if (path/"design/headline.json").is_file() else pkg.get("headline",{})
    strength=headline.get("strength") or {}
    summary={"native_status":st.get("status"),"strength_dc":strength.get("dc"),"governing_member":strength.get("member"),
             "check":strength.get("check"),"combination":strength.get("combination"),"clause":strength.get("clause"),
             "reason_count":st.get("n_reasons",len(st.get("reasons",[])))}
    authority=path/("STATUS.engine.md" if family=="hr" else "STATUS.md")
    text=authority.read_text(encoding="utf-8-sig")
    status=re.search(r"^# .*?design status:\s*([a-z]+)",text,re.I|re.M)
    reasons=re.search(r"Open reasons \((\d+)",text)
    if not status:
        raise ValueError(f"{path.name}: cannot read the native issued status")
    summary.update(calculation_status=summary["native_status"],native_status=status[1].lower(),
                   authority_file=authority.name,authority_sha256=digest(authority))
    if reasons:
        summary["reason_count"]=int(reasons[1])
    takeoff=path/"design/takeoff.json"
    if takeoff.is_file():
        record=read(takeoff)
        summary.update(takeoff_kg_m2=record.get("kg_per_m2"),takeoff_basis=record.get("basis"))
    frame=(headline.get("frame") or {}).get("strength") or {}
    if frame.get("dc") is not None:
        summary["hr_frame_strength_dc"]=frame["dc"]
    summary["calc_sha256"]=digest(path/"design"/name)
    summary["report_sha256"]=digest(path/"report.html") if (path/"report.html").exists() else None
    shown=printed_strength(path/"report.html") if summary["report_sha256"] else None
    summary["printed_strength"]=shown
    summary["report_matches_native_headline"]=(abs(shown["dc"]-strength["dc"])<=.00056 and
        shown["member"]==strength["member"]) if shown and strength.get("dc") is not None else None
    open_part=text.split("Open reasons",1)[-1].split("\n\n",1)[0]
    reasons=[s[2:] for s in open_part.splitlines() if s.startswith("- ")] or st.get("reasons",[])
    summary["open_reasons_sample"]=[str(r) for r in reasons[:4]] if summary["reason_count"] else []
    return summary


def compare(args):
    rows=[]
    unit_names={11:["Office","Workshop"],12:["Classroom","Link","Gym"],19:["Flange","Stem"]}
    for family,source_dir in (("hr",args.hr_jobs),("cfs",args.cfs_jobs)):
        index=read(args.indexes/f"published-{family}.json")["examples"]
        for n in range(1,22 if family=="hr" else 16):
            ident=f"IN_{'CFS_' if family=='cfs' else ''}Ex{n}"
            case=ROOT/"validation"/family/ident
            handoff=next((p for p in (case/"handoff.json.gz",case/"handoff.json") if p.is_file()),None)
            if not handoff:
                raise ValueError(f"{ident}: freeze a design handoff before comparing")
            sha=digest(handoff)
            native_dir=source_dir/ident
            if digest(native_dir/"design/openbim_handoff.json")!=sha:
                raise ValueError(f"{ident}: private job differs from frozen public handoff")
            opener=gzip.open if handoff.suffix==".gz" else open
            with opener(handoff,"rt",encoding="utf-8-sig") as stream:
                bindings=json.load(stream)["source_evidence"]["files"]
            for file,expected in bindings.items():
                if digest(native_dir/file)!=expected:
                    raise ValueError(f"{ident}: saved native revision changed at {file}")
            reports=[r for r in index if r["id"].startswith(ident+"_")]
            units=unit_names.get(n,["Main"]) if family=="hr" else ["Main"]
            if len(reports)!=len(units):
                raise ValueError(f"{ident}: original unit/report inventory mismatch")
            for unit in units:
                if len(units)==1:
                    ref=reports[0]
                else:
                    matches=([r for r in reports if "/" not in r["id"]] if unit==units[0] else
                             [r for r in reports if unit.casefold() in re.split(r"[/_\s-]",r["report"].casefold())])
                    if len(matches)!=1:
                        raise ValueError(f"{ident}: cannot identify the published {unit} report")
                    ref=matches[0]
                ref_path=args.reports/family/ref["report"]
                new_path=native_dir if len(units)==1 else native_dir/"units"/unit
                published=reference(ref,ref_path)
                fresh=fresh_from_job(new_path,family)
                rows.append(dict(id=ident,module=family.upper(),number=n,unit=unit,handoff_sha256=sha,
                                 report_url=f"https://stelticai.com/solutions_india/{family}/"+ref["report"],
                                 reference_report_sha256=digest(ref_path),published=published,fresh=fresh))
    return rows


def fmt(value):
    return "—" if value is None else f"{value:.3f}" if isinstance(value,float) else str(value)


def report(rows):
    lines=["# Worked-example revision checklist","",
           "The fresh calculations were frozen before comparison with the example library. Each row compares the governing member strength check in the two revisions. Different members can govern. Read the member, load combination and scope before acting on a ratio difference. The comparison JSON retains the report and calculation fingerprints.","",
           "| Building and unit | Published status / member D/C | Fresh status / member D/C | Governing member, published → fresh |",
           "| --- | --- | --- | --- |"]
    for r in rows:
        a,b=r["published"],r["fresh"]
        label=r["id"]+((" / "+r["unit"]) if r["unit"]!="Main" else "")
        lines.append(f"| [{label}]({r['report_url']}) | {a['native_status']} / {fmt(a['strength_dc'])} | "
                     f"{b['native_status']} / {fmt(b['strength_dc'])} | {a['governing_member'] or '—'} → {b['governing_member'] or '—'} |")
    lines+=["","The [hot-rolled engineering review](hr/engineering-review.md) and [cold-formed engineering review](cfs/engineering-review.md) identify brief, load and detail differences that can explain these comparisons.","","## Items to reconcile",""]
    for r in rows:
        a,b=r["published"],r["fresh"]
        name=r["id"]+(" / "+r["unit"] if r["unit"]!="Main" else "")
        if any(a.get(k)!=b.get(k) for k in ("native_status","strength_dc","governing_member","takeoff_kg_m2","hr_frame_strength_dc")):
            msg=f"- [ ] **{name}.** "
            if b["strength_dc"] is not None and a["strength_dc"] is not None:
                msg+=f"Compare the selected sections, restraints and load envelopes for {a['governing_member']} and {b['governing_member']}. The fresh governing case is {b.get('combination') or 'in the calculation package'}."
            else:
                msg+="Review the native report for the governing member before assigning a common D/C."
            if a.get("takeoff_kg_m2") is not None and b.get("takeoff_kg_m2") is not None:
                msg+=f" Reconcile take-off scope at {a['takeoff_kg_m2']:.1f} and {b['takeoff_kg_m2']:.1f} kg/m² respectively."
            if a.get("hr_frame_strength_dc") is not None and b.get("hr_frame_strength_dc") is not None:
                msg+=f" Compare the HR lateral-frame D/C separately ({a['hr_frame_strength_dc']:.3f} and {b['hr_frame_strength_dc']:.3f})."
            if a["native_status"]!=b["native_status"]:
                msg+=f" Check the published {a['native_status']} decision against the fresh {b['native_status']} decision and its {b['reason_count']} native reason(s)."
            lines.append(msg)
    return "\n".join(lines)+"\n"


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ("indexes","reports","hr-jobs","cfs-jobs","output"):
        parser.add_argument("--"+flag,type=Path,required=True)
    a=parser.parse_args()
    data=compare(a)
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/"comparison.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (a.output/"revision-checklist.md").write_text(report(data),encoding="utf-8")
    print(f"Compared {len(data)} individual published HR/CFS unit reports")
