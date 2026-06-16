#!/usr/bin/env python3
"""Repair the applied cross-edition headword corrections IN PLACE, working only
from each record's provenance (the decisions/candidates files are stale: they
reproduce only 420 of the 1368 applied corrections, the rest coming from an
earlier pipeline run whose candidate file is gone, so a revert+reapply would
destroy ~948 good corrections).

For every record carrying provenance.headword_correction {from, to}:
  * WRONG target (hyphenated-compound base mis-matched: dropped second word or
    garbled/cross-concept merge) -> fully revert to raw, drop the correction.
  * otherwise (a good correction) -> recompute the display headword with the
    anchored whole-token substitution, fixing the string-corruption bug
    (e.g. "SNOWDONrop" -> "SNOWDON", "HEAD-WAYay" -> "HEADWAY"). The correction
    itself is kept; provenance.raw_* is preserved for reversibility.

Idempotent and reversible. Run with --dry-run first.
"""
import argparse
import json
import re
from pathlib import Path

# (variant_norm, canonical_norm) judged WRONG and reverted to raw:
# 16 "dropped second word" + 12 garbled/cross-concept compound merges + WATS.
WRONG = {
    ("BARNM", "BARN"), ("BASSV", "BASSO"), ("BERNM", "BERNE"),
    ("CARTHUSIANP", "CARTHUSIAN"), ("CRIMT", "CRIM"), ("DEADLYF", "DEADLY"),
    ("FLOATINGB", "FLOATING"), ("GIANTSC", "GIANTS"), ("GORDIANK", "GORDIAN"),
    ("HEDGESS", "HEDGES"), ("HOLYI", "HOLY"), ("LANTERNF", "LANTERNS"),
    ("NEUTRALS", "NEUTRAL"), ("PARIANM", "PARIAN"), ("SMOKEFAR", "SMOKEF"),
    ("SOURG", "SOUR"),
    ("SNOWD", "SNOWDON"), ("GALLERYW", "GALLEYW"), ("BRAMBLESN", "BRAMBLEN"),
    ("CARTSB", "CARTEB"), ("CARTZB", "CARTEB"), ("COLOGNSE", "COLOGNEE"),
    ("SERVICAT", "SERVICET"), ("CASALEM", "CASALM"), ("BRAGM", "BRAEM"),
    ("PORPHYRITS", "PORPHYRYS"), ("BARBADORST", "BARBADOEST"),
    ("BRINEP", "BRINEPIT"),
    ("WATS", "WATERS"),
}


def anchored_headword(raw_base, canon, raw_hw):
    """Reproduce apply_headword_fixes' fixed rendering: substitute raw_base ->
    canon only as a whole token, else fall back to the bare canonical."""
    out = re.sub(rf"(?<![A-Za-z]){re.escape(raw_base)}(?![A-Za-z-])",
                 canon, raw_hw, count=1)
    return out if out != raw_hw else canon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    reverted = repaired = ok = 0
    rev_ex, rep_ex = [], []
    for jf in sorted(Path(args.article_dir).glob("EB.*.jsonl")):
        recs = [json.loads(l) for l in jf.open()]
        changed = False
        for r in recs:
            prov = r.get("provenance", {})
            hc = prov.get("headword_correction")
            if not hc:
                continue
            raw_hw = prov.get("raw_headword", r["headword"])
            raw_base = prov.get("raw_base_headword", r["base_headword"])
            pair = (hc.get("from"), hc.get("to"))
            if pair in WRONG:
                r["headword"], r["base_headword"] = raw_hw, raw_base
                prov.pop("headword_correction", None)
                prov.pop("raw_headword", None)
                prov.pop("raw_base_headword", None)
                reverted += 1
                changed = True
                if len(rev_ex) < 6:
                    rev_ex.append(f"{r['headword']!r} (was {pair[0]}->{pair[1]})")
            else:
                want = anchored_headword(raw_base, r["base_headword"], raw_hw)
                if r["headword"] != want:
                    if len(rep_ex) < 6:
                        rep_ex.append(f"{r['headword']!r} -> {want!r}")
                    r["headword"] = want
                    repaired += 1
                    changed = True
                else:
                    ok += 1
        if changed and not args.dry_run:
            with jf.open("w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"wrong-target reverted to raw: {reverted}")
    print(f"string-corruption repaired:   {repaired}")
    print(f"good corrections untouched:    {ok}")
    print("\nrevert examples:", rev_ex)
    print("repair examples:", rep_ex)


if __name__ == "__main__":
    main()
