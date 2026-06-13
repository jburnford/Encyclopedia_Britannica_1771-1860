#!/usr/bin/env python3
"""Copy per-volume HTML into a flat html/ dir with descriptive filenames.

Naming scheme:  <eb_code>_<edition>_v<NN>[_<alpha>]_<identifier>.html
  edition  = ed<N>  for numbered editions, "suppl" for supplements
  v<NN>    = zero-padded volume number (v00 for index/title volumes)
  <alpha>  = slugified alpha_range (or volume_label when no range)
  id       = NLS identifier (kept for traceability; guarantees uniqueness)

Examples:
  EB.5_ed3_v01_A-ANG_190273291.html
  EB.9_ed4_v01_Part1_A-Agriculture_191253818.html
  EB.7_suppl_v01_ABE-IMP_191253807.html
  EB.15_ed7_v00_Seventh-edition-General-index_192547789.html

Also writes html/index.csv mapping every filename back to its source.

Usage:
    python3 scripts/flatten_html.py [--output-dir output] [--html-dir html]
"""
import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}


def slug_simple(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", "-", s)              # spaces -> hyphen
    s = re.sub(r"[^A-Za-z0-9._-]", "", s)   # drop other punctuation (commas, etc.)
    return re.sub(r"-{2,}", "-", s).strip("-")


def slug_range(s: str) -> str:
    """Slug an alpha_range, special-casing 'Part N, REST' -> 'PartN_REST'."""
    s = s.strip()
    m = re.match(r"Part\s*([IVXivx]+|\d+)\s*,\s*(.*)", s)
    if m:
        tok = m.group(1)
        num = ROMAN.get(tok.lower(), tok)   # normalise roman 'I' -> 1
        return f"Part{num}_{slug_simple(m.group(2))}"
    return slug_simple(s)


def make_name(meta: dict) -> str:
    eb = meta.get("eb_code") or "EB.?"
    if meta.get("edition_num"):
        ed = f"ed{meta['edition_num']}"
    elif meta.get("is_supplement"):
        ed = "suppl"
    else:
        ed = "edNA"
    vn = meta.get("volume_num")
    vol = f"v{int(vn):02d}" if vn is not None else "v00"

    alpha = meta.get("alpha_range")
    label = meta.get("volume_label")
    if alpha:
        slug = slug_range(alpha)
    elif label:
        slug = slug_simple(label)
    else:
        slug = ""

    ident = meta.get("identifier", "")
    parts = [eb, ed, vol] + ([slug] if slug else []) + [ident]
    return "_".join(parts) + ".html"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="output")
    ap.add_argument("--html-dir", default="html")
    args = ap.parse_args()

    root = Path(args.output_dir)
    metas = sorted(root.glob("*/*/metadata.json"))
    if not metas:
        sys.exit(f"no volumes found under {root}/*/*/metadata.json")

    html_dir = Path(args.html_dir)
    html_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    seen = {}
    n_copied = 0
    for meta_p in metas:
        meta = json.loads(meta_p.read_text())
        ident = meta.get("identifier", meta_p.parent.name)
        src = meta_p.parent / f"{ident}.html"
        if not src.exists():
            print(f"  WARN: missing {src}", file=sys.stderr)
            continue
        name = make_name(meta)
        if name in seen:
            sys.exit(f"FATAL: filename collision {name} ({seen[name]} vs {src})")
        seen[name] = src
        shutil.copy2(src, html_dir / name)
        n_copied += 1
        rows.append({
            "filename": name,
            "eb_code": meta.get("eb_code"),
            "edition_num": meta.get("edition_num"),
            "is_supplement": meta.get("is_supplement"),
            "volume_num": meta.get("volume_num"),
            "alpha_range": meta.get("alpha_range"),
            "volume_label": meta.get("volume_label"),
            "n_pages": meta.get("n_pages"),
            "identifier": ident,
            "title": meta.get("title"),
            "src_path": str(src),
        })

    csv_p = html_dir / "index.csv"
    with csv_p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"Copied {n_copied} files -> {html_dir}/")
    print(f"Wrote {csv_p}")


if __name__ == "__main__":
    main()
