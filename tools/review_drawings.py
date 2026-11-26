"""Render the issued plan, elevation and connection-detail samples with Poppler."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from shutil import which
import subprocess
import sys

from package_examples import file_sha, record


def select_sheets(register):
    sheets = register["sheets"]
    plans = [sheet for sheet in sheets if sheet["kind"] == "plan"]
    elevations = [sheet for sheet in sheets if sheet["kind"] == "elevation"]
    frame_lines = [sheet for sheet in elevations if "off-grid" not in sheet["title"].lower()]
    details = [sheet for sheet in sheets if sheet["kind"] == "details"]
    members = {view["sheet"]: len(view["member_ids"]) for view in register["views"]}
    parts = {detail["sheet"]: len(detail["part_ids"]) for detail in register["connection_details"]}
    if not plans or not elevations or not details:
        raise ValueError("A plan, elevation and connection detail are required for the visual review")
    return [max(plans, key=lambda sheet: members.get(sheet["number"], 0)),
            max(frame_lines or elevations, key=lambda sheet: members.get(sheet["number"], 0)),
            max(details, key=lambda sheet: parts.get(sheet["number"], 0))]


def render(case, build, destination, poppler):
    directory = build / case["delivery"]
    pdf = directory / "drawings.pdf"
    fingerprint = file_sha(pdf)
    register = record(directory / "drawing_register.json")
    if fingerprint != register["drawings_pdf_sha256"]:
        raise ValueError(f"{case['id']}: drawing register refers to a different PDF")
    samples = []
    messages = set()
    for sheet in select_sheets(register):
        prefix = destination / f"{case['id']}-{fingerprint[:10]}-{sheet['number']}"
        page = str(sheet["page"])
        completed = subprocess.run([poppler, "-f", page, "-l", page, "-singlefile", "-scale-to", "1150",
                                    "-png", str(pdf), str(prefix)], capture_output=True, text=True, errors="replace")
        if completed.returncode:
            raise RuntimeError(f"{case['id']} / {sheet['number']}: {completed.stderr.strip()}")
        messages.update(line for line in completed.stderr.splitlines() if line.strip())
        samples.append({"sheet": sheet["number"], "page": sheet["page"], "kind": sheet["kind"],
                        "png_sha256": file_sha(prefix.with_suffix(".png"))})
    return {"id": case["id"], "pdf_sha256": fingerprint, "poppler_samples": samples}, messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path, help="Directory with the completed validation.json")
    parser.add_argument("--output", required=True, type=Path, help="Directory for sample PNGs and visual-review.json")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    poppler = which("pdftoppm")
    if not poppler:
        parser.error("Install Poppler and add pdftoppm to PATH")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    cases = record(args.build / "validation.json")["cases"]
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(render, row, args.build, args.output, poppler) for row in cases]
        results = [future.result() for future in futures]
    reviews = [review for review, _ in results]
    for message in sorted({line for _, messages in results for line in messages}):
        print(message, file=sys.stderr)
    target = args.output / "visual-review.json"
    target.write_text(json.dumps(reviews, indent=2) + "\n", encoding="utf-8")
    print(f"Rendered {sum(len(row['poppler_samples']) for row in reviews)} drawing samples in {args.output}")


if __name__ == "__main__":
    main()
