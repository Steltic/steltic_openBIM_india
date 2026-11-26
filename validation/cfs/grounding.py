"""Read supplied local standard indexes. Licensed hits are private job artifacts."""
import csv
import hashlib
import json
import re
from pathlib import Path


S1 = "IS_875_Part_1_2026"
S2 = "IS_875_Part_2_1987"
S3 = "IS_875_Part_3_2015"
S4 = "IS_875_Part_4_1987"   # manifest's stable stem; read the edition on the PDF itself
S5 = "IS_875_Part_5_1987"
EQ = "IS_1893_Part_1_2016"
CF = "IS_801_1975"
SEC = "IS_811_1987"
HR = "IS_800_2007"
DUCT = "IS_18168_2023"


def terrain_category(building):
    return 3 if building.number == 7 else 2


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def retrieve(corpus, job, building):
    base = Path(corpus) / "documents" / "standards"
    rows = []
    def hit(stem, query, file, quote, page=None, purpose="design loads"):
        cite = f"{stem} {query}" + (f", PDF p. {page}" if page else "")
        record = dict(stem=stem, query=query, found=True, cite=cite, purpose=purpose,
                      file=f"rag/{len(rows):02d}.json", quote=quote.strip()[:240])
        dump(job/record["file"], {"found":True, "stem":stem, "query":query, "cite":cite,
                                  "quote":record["quote"], "source_file":file.relative_to(base).as_posix(),
                                  "source_sha256":hashlib.sha256(file.read_bytes()).hexdigest()})
        rows.append(record)
    def exact(stem, kind, key, purpose="design loads"):
        index = base/stem/"indexes"/(kind+"s.json")
        items = json.loads(index.read_text(encoding="utf-8"))
        item = next((r for r in items if str(r.get(kind+"_id")).strip()==key), None)
        if item:
            page=item.get("pdf_page")
            quote=item.get("title") or item.get("markdown_excerpt") or key
            hit(stem,kind+" "+key,index,quote,page,purpose)
        else:
            # Some headings, including IS 801 cl. 7.3, are absent from the
            # machine section index even though the page image/text has them.
            for folder in ("pages_recovered","pages_search","pages"):
                for f in sorted((base/stem/"markdown"/folder).glob("page_*.md")):
                    s=f.read_text(encoding="utf-8")
                    m=re.search(r"^\s*(?:#{1,5}\s*|[-*]\s*)?(?:SECTION\s+)?"+re.escape(key)+r"\s+(?![\d.])[^\n]{4,145}",s,re.M|re.I)
                    if m:
                        hit(stem,kind+" "+key,f,m[0].strip(),int(f.stem[-3:]),purpose)
                        return
            rows.append(dict(stem=stem,query=kind+" "+key,found=False,cite=f"{stem} {kind} {key}",
                             purpose=purpose,note="Local index and pages have no exact heading match"))
    def table(stem, key):
        return base/stem/"tables"/f"{stem}_Table_{key}_recovered.csv"
    def records(path):
        with path.open(encoding="utf-8-sig",newline="") as f:
            return list(csv.DictReader(f))
    def gap(stem,query,**extra):
        rows.append(dict(stem=stem,query=query,found=False,cite=f"{stem} {query}",**extra))

    for stem,kind,keys,purpose in (
        (CF,"section",["5.2","6.1","6.3","6.4","6.5","6.6","6.7","7.3","7.5","8.1","8.2"],"cold-formed member"),
        (SEC,"table",["3","4"],"cold-formed section properties"),
        (S1,"table",["1"],"dead load"),(S2,"table",["1","2"],"imposed load"),
        (S2,"section",["3.1.2"],"partition allowance"),
        (S3,"table",["2","4","5","6"],"wind"),(S3,"section",["6.3.4","7.2.1","7.3"],"wind"),
        (S5,"section",["8.1"],"working stress combinations"),
        (EQ,"table",["3","7","8","9","10"],"seismic"),(EQ,"section",["6.4.2","7.7.1","7.11.1"],"seismic"),
        (HR,"table",["6"],"serviceability_limits_table6")):
        for key in keys:
            exact(stem,kind,key,purpose)
    if building.number!=3:
        for key in ["4","5"]:
            exact(HR,"table",key,"lateral_frame_is800")
        exact(HR,"section","12","lateral_frame_is800")
        if building.zone!="II":
            exact(DUCT,"section","1.3","lateral_frame_is800")

    speed_file=table(S3,"AnnexA")
    city_key={"Visakhapatnam":"Vishakapatnam","Noida":"Delhi"}.get(building.site,building.site)
    speed_row=next(r for r in records(speed_file) if list(r.values())[0].lower()==city_key.lower())
    speed=float(list(speed_row.values())[1])
    hit(S3,"Annex A "+city_key,speed_file,",".join(speed_row.values()),59)
    zfile=table(EQ,"3")
    z=float(records(zfile)[0][building.zone])
    if building.number==14:
        gap(S3,"Annex A Noida",value=speed,source="Delhi proxy; owner brief",verify=True)
        gap(EQ,"Annex E Noida",value=building.zone,source="Figure 1 site reading supplied by brief",verify=True)
    else:
        ali={"Visakhapatnam":"Vishakhapatnam","Bengaluru":"(?:Bangalore \\(Bengaluru\\))","Mumbai":"(?:Mumbai|Bombay)"}
        m=None
        for p in (38,39):
            f=base/EQ/"markdown"/"pages_recovered"/f"page_{p:03}.md"
            s=f.read_text(encoding="utf-8")
            m=re.search(ali.get(building.site,building.site)+r"\s+(I{2,3}|IV|V)\s+([0-9.]+)",s,re.I)
            if m:
                if m[1]!=building.zone or abs(float(m[2])-z)>1e-8:
                    raise ValueError(f"{building.site}: brief/Annex E disagreement")
                hit(EQ,"Annex E "+building.site,f,m[0],p)
                break
        if not m:
            gap(EQ,"Annex E "+building.site,value=building.zone,source="zone in owner brief",verify=True)
    if building.number==2:
        for k in ("5.2.1","5.2.4","5.2.6"):
            exact(S4,"section",k,"snow")
        gap(S4,"Figure 1 ground snow zone",value=4,source="Zone 4 sensitivity case in brief; confirm site map",verify=True)
    else:
        gap(S4,"site snow applicability",value=0,source="Site is outside the snow region per brief",
            verify=True,note="No snow load applied.")
    if building.number==3:
        p=base/S2/"markdown"/"pages_recovered"/"page_013.md"
        storage=next(line for line in p.read_text(encoding="utf-8").splitlines() if "viii)(a)" in line and "7.5" in line)
        hit(S2,"Table 1 viii(a), general storage",p,storage,13,"storage floor load")
    terrain=terrain_category(building)
    terrain_rows=records(table(S3,"2"))
    k2={r["height_z_m"]:float(r[f"k2_terrain_category_{terrain}"]) for r in terrain_rows if r["height_z_m"].isdigit()}
    return rows,speed,z,k2
