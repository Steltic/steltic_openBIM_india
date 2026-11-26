"""Bind an unpacked fixed India corpus and licensed PDFs to the validation run.

This report contains filenames, fingerprints, page locators and edition identifiers.
No source page, clause excerpt, or standards table is written to the report.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile

import pymupdf


def hash_file(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("archive","corpus","pdf-dir","output"):
        p.add_argument("--"+name,required=True,type=Path)
    a=p.parse_args()
    manifest=json.loads((a.corpus/"INDIA_MANIFEST.json").read_text(encoding="utf-8"))
    verified=Counter()
    differences=[]
    with zipfile.ZipFile(a.archive) as z:
        for entry in z.infolist():
            name=entry.filename.removeprefix("corpus_fixed/")
            if entry.is_dir() or not (name=="INDIA_MANIFEST.json" or name.startswith(("indexes/","documents/standards/"))):
                continue
            file=a.corpus/name
            if not file.is_file() or hashlib.sha256(z.read(entry)).hexdigest()!=hash_file(file):
                differences.append(name)
            else:
                verified[name.split("/")[0]]+=1
    docs=[]
    for record in manifest["docs"]:
        filename=record["pdf"].split("/")[-1]
        path=a.pdf_dir/filename
        if not path.is_file():
            raise FileNotFoundError(path)
        with pymupdf.open(path) as pdf:
            pages=len(pdf)
        if pages!=record["pages"]:
            differences.append(filename+" page count")
        docs.append(dict(stem=record["stem"],edition=record["edition"],pdf=filename,pages=pages,sha256=hash_file(path)))
    # Independently reopen the primary PDFs at controls used across the cases.
    checks=[
        ("IS_875_Part_4_1987.pdf",1,("2021","Snow"),"Snow load edition on the title page"),
        ("IS_1893_Part_1_2016_Amd2_Reff2021.pdf",28,("7.11.1","0.004"),"Storey drift limit"),
        ("IS_801_1975.pdf",12,("design stress",),"Cold-formed working stress"),
    ]
    located=[]
    for filename,number,terms,meaning in checks:
        with pymupdf.open(a.pdf_dir/filename) as pdf:
            text=" ".join(pdf[number-1].get_text().split()).casefold()
        ok=all(token.casefold() in text for token in terms)
        located.append(dict(pdf=filename,pdf_page=number,control=meaning,located=ok))
        if not ok:
            differences.append(filename+" / "+meaning)
    report=dict(archive_sha256=hash_file(a.archive),matching_archive_entries=dict(verified),
                editions_and_pdf_fingerprints=docs,primary_pdf_spot_checks=located,differences=differences)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(f"{sum(verified.values())} matching corpus files, {len(docs)} primary documents and amendments, {len(differences)} findings")
    if differences:
        print(differences[:10])
    return int(bool(differences))


if __name__=="__main__":
    raise SystemExit(main())
