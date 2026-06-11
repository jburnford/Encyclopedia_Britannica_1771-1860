#!/usr/bin/env python3
"""Build the master manifest for the NLS Encyclopaedia Britannica dataset.

Parses the NLS inventory CSV plus each volume's METS file and emits:
  manifest/volumes.csv    - one row per volume, clean metadata
  manifest/volumes.jsonl  - same data, one JSON object per line

Run on Nibi:
  python3 build_manifest.py \
      --data-dir /project/def-jic823/nls-data-encyclopaediaBritannica \
      --out-dir  /project/def-jic823/britannica_chandra2/manifest
"""

import argparse
import csv
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

EDITION_RE = re.compile(
    r"\b(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth)\s+edition(?:,\s*(\d{4}))?",
    re.I,
)
VOLUME_RE = re.compile(r"\bVolume\s+(\d+)\b", re.I)

EDITION_ORDINAL = {
    "first": 1, "second": 2, "third": 3, "fourth": 4,
    "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
}


def parse_title(title: str) -> dict:
    """Parse an NLS inventory title into structured fields.

    Example titles:
      "Encyclopaedia Britannica; or, A dictionary ... - First edition, 1771, Volume 1, A-B - EB.1"
      "Encyclopaedia Britannica - Second edition, Volume 1, A-AST - EB.4"
      "Supplement to the third edition of the Encyclopaedia Britannica ... - Volume 1, ABE-IMP - EB.7"
      "Encyclopaedia Britannica - Seventh edition, General index - EB.15"
    """
    out = {
        "title": title,
        "eb_code": None,
        "edition_label": None,
        "edition_num": None,
        "edition_year": None,
        "is_supplement": False,
        "supplement_to": None,
        "volume_num": None,
        "volume_label": None,
        "alpha_range": None,
    }

    parts = [p.strip() for p in title.split(" - ")]
    if parts and re.fullmatch(r"EB\.\d+", parts[-1]):
        out["eb_code"] = parts.pop()

    if title.lower().startswith("supplement"):
        out["is_supplement"] = True
        m = re.search(r"supplement to the (.+?) of the encyclopaedia", title, re.I)
        if m:
            out["supplement_to"] = m.group(1).strip()
        out["edition_label"] = "Supplement (" + (out["supplement_to"] or "?") + ")"
    else:
        m = EDITION_RE.search(title)
        if m:
            out["edition_label"] = m.group(1).capitalize() + " edition"
            out["edition_num"] = EDITION_ORDINAL[m.group(1).lower()]
            if m.group(2):
                out["edition_year"] = int(m.group(2))

    m = VOLUME_RE.search(title)
    if m:
        out["volume_num"] = int(m.group(1))
        # alpha range / descriptor follows "Volume N, "
        tail = title[m.end():].lstrip(", ").strip()
        # strip trailing " - EB.x" if split missed it
        tail = re.sub(r"\s*-\s*EB\.\d+$", "", tail).strip()
        if tail:
            out["alpha_range"] = tail
    else:
        # No volume number: index, dissertations, etc. Use last descriptive part.
        for p in reversed(parts):
            if "encyclopaedia" not in p.lower() and "supplement" not in p.lower():
                out["volume_label"] = p
                break

    return out


def parse_mets(mets_path: Path) -> dict:
    """Extract page order, date issued, and rights from a METS file."""
    out = {"date_issued": None, "rights": None, "n_pages_mets": None, "pages": []}
    try:
        tree = ET.parse(mets_path)
    except ET.ParseError as e:
        out["mets_error"] = str(e)
        return out
    root = tree.getroot()

    def local(tag):
        return tag.rsplit("}", 1)[-1]

    # fileSec: FILEID -> image filename (only file://./image/ entries)
    fileid_to_img = {}
    for f in root.iter():
        if local(f.tag) != "file":
            continue
        fid = f.get("ID")
        for loc in f:
            if local(loc.tag) == "FLocat":
                href = loc.get("{http://www.w3.org/1999/xlink}href", "")
                if "image/" in href and href.startswith("file://"):
                    fileid_to_img[fid] = href.rsplit("/", 1)[-1]

    # structMap: ordered pages -> fptr FILEID
    pages = []
    for div in root.iter():
        if local(div.tag) != "div":
            continue
        order = div.get("ORDER")
        if order is None:
            continue
        for fptr in div:
            if local(fptr.tag) == "fptr":
                fid = fptr.get("FILEID")
                if fid in fileid_to_img:
                    pages.append((int(order), fileid_to_img[fid]))
    pages.sort()
    out["pages"] = [img for _, img in pages]
    out["n_pages_mets"] = len(pages)

    for el in root.iter():
        tag = local(el.tag)
        if tag == "dateIssued" and out["date_issued"] is None and el.text:
            out["date_issued"] = el.text.strip()
        elif tag == "accessCondition" and out["rights"] is None:
            txt = " ".join(el.itertext()).strip()
            if txt:
                out["rights"] = txt
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    inv = args.data_dir / "encyclopaediaBritannica-inventory.csv"
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    with open(inv, encoding="utf-8-sig") as f:
        for ident, title in csv.reader(f):
            ident = ident.strip()
            rec = {"identifier": ident}
            rec.update(parse_title(title.strip()))

            vol_dir = args.data_dir / ident
            img_dir = vol_dir / "image"
            rec["volume_dir"] = str(vol_dir)
            rec["n_images"] = (
                len(list(img_dir.glob("*.jpg"))) if img_dir.is_dir() else 0
            )

            mets = vol_dir / f"{ident}-mets.xml"
            if mets.exists():
                m = parse_mets(mets)
                rec["date_issued"] = m["date_issued"]
                rec["rights"] = m["rights"]
                rec["n_pages_mets"] = m["n_pages_mets"]
                rec["pages_match"] = m["n_pages_mets"] == rec["n_images"]
            else:
                rec["date_issued"] = rec["rights"] = rec["n_pages_mets"] = None
                rec["pages_match"] = False
            rows.append(rec)

    def sort_key(r):
        code = int(r["eb_code"].split(".")[1]) if r["eb_code"] else 999
        return (code, r["volume_num"] or 0)

    rows.sort(key=sort_key)

    cols = [
        "identifier", "eb_code", "edition_label", "edition_num", "edition_year",
        "is_supplement", "supplement_to", "volume_num", "volume_label",
        "alpha_range", "date_issued", "n_images", "n_pages_mets", "pages_match",
        "rights", "title", "volume_dir",
    ]
    with open(args.out_dir / "volumes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({c: r.get(c) for c in cols} for r in rows)

    with open(args.out_dir / "volumes.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary
    by_code = {}
    for r in rows:
        k = (r["eb_code"], r["edition_label"])
        by_code.setdefault(k, []).append(r)
    print(f"{'EB code':8} {'edition':34} {'vols':>4} {'pages':>7}  mismatches")
    total = 0
    for (code, label), vs in sorted(
        by_code.items(), key=lambda kv: int(kv[0][0].split(".")[1]) if kv[0][0] else 999
    ):
        pages = sum(v["n_images"] for v in vs)
        total += pages
        bad = [v["identifier"] for v in vs if not v["pages_match"]]
        print(f"{code or '?':8} {label or '?':34} {len(vs):>4} {pages:>7}  {bad if bad else ''}")
    print(f"{'TOTAL':8} {'':34} {len(rows):>4} {total:>7}")


if __name__ == "__main__":
    main()
