#!/usr/bin/env python3
"""Post-hoc field-level cleanups applied directly to article_data (no re-parse):

  qualifier  -- populate the empty `qualifier` field for parenthetical headwords
                ("NOTARY (NOTARIUS)" -> base NOTARY, qualifier "NOTARIUS"). Only
                fills when qualifier is currently null and the headword is
                BASE (...)  — prefix qualifiers ("Grecian ABACUS") are already
                set at parse time and are left alone.
  page-clamp -- repair OCR-misread printed_page_end outliers (e.g. "1883") using
                the reliable image-page span: expected_end = printed_page_start +
                (image_page_end - image_page_start). When the stored end deviates
                from that by more than a tolerance it is replaced and the raw
                value stashed in provenance.raw_printed_page_end.

`type` normalization is intentionally NOT done here — it needs the section-header
criteria handled by the Stage B treatise re-typing pass.

Use --only to scope to specific editions (default: all). Run --dry-run first.
"""
import argparse
import json
import re
from pathlib import Path

PAREN = re.compile(r"^\s*(.+?)\s*\(([^)]+)\)\s*$")
PAGE_TOL = 50


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--only", default="", help="comma-separated editions, e.g. EB.1,EB.4")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    eds = [e.strip() for e in args.only.split(",") if e.strip()]

    files = []
    for jf in sorted(Path(args.article_dir).glob("EB.*.jsonl")):
        ed = jf.name.split("_")[0]
        if not eds or ed in eds:
            files.append(jf)

    n_qual = n_page = 0
    for jf in files:
        recs = [json.loads(l) for l in jf.open()]
        changed = False
        for r in recs:
            # qualifier
            if not r.get("qualifier"):
                m = PAREN.match(r.get("headword", ""))
                if m and re.fullmatch(r"[A-Z][A-Z'\-. ]+", (r.get("base_headword") or "")) \
                        and m.group(1).strip().upper().startswith((r.get("base_headword") or "ZzZ")[:3]):
                    r["qualifier"] = m.group(2).strip()
                    n_qual += 1
                    changed = True
            # page clamp (need both printed + image spans)
            ps, pe = r.get("printed_page_start"), r.get("printed_page_end")
            is_, ie = r.get("image_page_start"), r.get("image_page_end")
            if None not in (ps, pe, is_, ie):
                expected = ps + (ie - is_)
                if pe < ps or abs(pe - expected) > PAGE_TOL:
                    r.setdefault("provenance", {})["raw_printed_page_end"] = pe
                    r["printed_page_end"] = expected
                    n_page += 1
                    changed = True
        if changed and not args.dry_run:
            with jf.open("w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    scope = ",".join(eds) if eds else "ALL"
    print(f"[{scope}] qualifier populated: {n_qual}   printed_page_end clamped: {n_page}"
          + ("   (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
