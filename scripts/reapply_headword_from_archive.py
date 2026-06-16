#!/usr/bin/env python3
"""Restore headword corrections to freshly re-parsed editions, sourcing the fix
map from the ARCHIVED pre-reparse files' provenance (the decisions/candidates
files are stale and reproduce only 420 of 1368 applied corrections). For each
re-parsed record whose base_headword matches an archived correction's raw base,
re-apply it with the anchored whole-token substitution; the 29 WRONG hyphenated-
compound pairs are skipped.

Usage: reapply_headword_from_archive.py --archive repair_archive/prereparse_b2 \
                                        --only EB.12,EB.15,EB.16 [--dry-run]
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

# same WRONG set as revert_headword_corrections.py
WRONG = {
    ("BARNM", "BARN"), ("BASSV", "BASSO"), ("BERNM", "BERNE"),
    ("CARTHUSIANP", "CARTHUSIAN"), ("CRIMT", "CRIM"), ("DEADLYF", "DEADLY"),
    ("FLOATINGB", "FLOATING"), ("GIANTSC", "GIANTS"), ("GORDIANK", "GORDIAN"),
    ("HEDGESS", "HEDGES"), ("HOLYI", "HOLY"), ("LANTERNF", "LANTERNS"),
    ("NEUTRALS", "NEUTRAL"), ("PARIANM", "PARIAN"), ("SMOKEFAR", "SMOKEF"),
    ("SOURG", "SOUR"), ("SNOWD", "SNOWDON"), ("GALLERYW", "GALLEYW"),
    ("BRAMBLESN", "BRAMBLEN"), ("CARTSB", "CARTEB"), ("CARTZB", "CARTEB"),
    ("COLOGNSE", "COLOGNEE"), ("SERVICAT", "SERVICET"), ("CASALEM", "CASALM"),
    ("BRAGM", "BRAEM"), ("PORPHYRITS", "PORPHYRYS"), ("BARBADORST", "BARBADOEST"),
    ("BRINEP", "BRINEPIT"), ("WATS", "WATERS"),
}


def norm(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def anchored(raw_base, canon, raw_hw):
    out = re.sub(rf"(?<![A-Za-z]){re.escape(raw_base)}(?![A-Za-z-])", canon, raw_hw, count=1)
    return out if out != raw_hw else canon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--archive", default="repair_archive/prereparse_b2")
    ap.add_argument("--only", required=True, help="comma-separated editions")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    eds = [e.strip() for e in args.only.split(",") if e.strip()]

    # Build fix map per edition from archived provenance: variant_norm -> (canon_base, meta)
    fixmap = defaultdict(dict)
    skipped_wrong = 0
    for jf in sorted(Path(args.archive).glob("*.jsonl")):
        ed = jf.name.split("_")[0]
        if ed not in eds:
            continue
        for line in jf.open():
            r = json.loads(line)
            hc = r.get("provenance", {}).get("headword_correction")
            if not hc:
                continue
            pair = (hc.get("from"), hc.get("to"))
            if pair in WRONG:
                skipped_wrong += 1
                continue
            fixmap[ed][hc["from"]] = (r["base_headword"], hc)

    total = applied = 0
    for jf in sorted(Path(args.article_dir).glob("EB.*.jsonl")):
        ed = jf.name.split("_")[0]
        if ed not in eds:
            continue
        recs = [json.loads(l) for l in jf.open()]
        changed = False
        for r in recs:
            if r.get("type") == "treatise":
                continue
            v = norm(r["base_headword"])
            if v not in fixmap[ed]:
                continue
            canon_base, hc = fixmap[ed][v]
            old_base, old_hw = r["base_headword"], r["headword"]
            prov = r.setdefault("provenance", {})
            prov["raw_headword"] = old_hw
            prov["raw_base_headword"] = old_base
            prov["headword_correction"] = hc
            r["base_headword"] = canon_base
            r["headword"] = anchored(old_base, canon_base, old_hw)
            applied += 1
            changed = True
        total += len(recs)
        if changed and not args.dry_run:
            with jf.open("w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"fix map size: {sum(len(m) for m in fixmap.values())} "
          f"({', '.join(f'{e}:{len(fixmap[e])}' for e in eds)}); WRONG skipped: {skipped_wrong}")
    print(f"corrections re-applied: {applied}" + ("  (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
