#!/usr/bin/env python3
"""Apply adjudicated cross-edition headword corrections to article_data/.

Stage 3 of the OCR headword-repair pipeline:
  1. headword_reconcile.py  -> headword_candidates.jsonl   (detect + suggest)
  2. adjudicate_workflow.js -> headword_decisions.jsonl     (LLM decides per candidate)
  3. THIS script            -> rewrites article_data/*.jsonl

For each candidate the LLM marked "correct", every record in that candidate's
edition whose base_headword matches the garbled variant is rewritten:
  * provenance.raw_headword / raw_base_headword  <- the original OCR strings
  * provenance.headword_correction               <- {from,to,n_editions,edit_distance,source}
  * base_headword / headword                      <- the canonical spelling

The body text is left untouched (it is the faithful OCR); only the headword
fields are normalised so the article can be matched across editions and grounded.
Run with --dry-run first to see the impact without writing.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

EDS = ["EB.1", "EB.4", "EB.5", "EB.9", "EB.10", "EB.11"]


def norm(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--candidates", default="headword_candidates.jsonl")
    ap.add_argument("--decisions", default="headword_decisions.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    adir = Path(args.article_dir)

    cands = {}
    for ln, line in enumerate(open(args.candidates)):
        c = json.loads(line)
        cands[ln] = c                      # index == line number in candidates file

    # decisions reference candidates by their "i" field (== line index)
    fixes = {}                             # (edition, variant_norm) -> (canonical_display, meta)
    n_keep = n_bad = 0
    for line in open(args.decisions):
        d = json.loads(line)
        if d["decision"] != "correct" or not d.get("canonical"):
            n_keep += 1
            continue
        c = cands.get(d["i"])
        if not c:
            n_bad += 1
            continue
        sug = next((s for s in c["suggestions"] if s["norm"] == norm(d["canonical"])), None)
        if not sug:
            n_bad += 1                     # LLM picked a spelling not among suggestions
            continue
        fixes[(c["edition"], c["variant"])] = (sug["canonical"], {
            "from": c["variant"], "to": sug["norm"],
            "n_editions": sug["n_editions"], "edit_distance": sug["edit_distance"],
            "source": "cross-edition+llm"})

    print(f"corrections to apply: {len(fixes)}  (keep: {n_keep}, unusable: {n_bad})")

    # group fixes by edition for a single pass per file
    by_ed = defaultdict(dict)
    for (ed, v), val in fixes.items():
        by_ed[ed][v] = val

    total_recs = 0
    for ed, vmap in by_ed.items():
        for jf in sorted(adir.glob(f"{ed}_*.jsonl")):
            recs = [json.loads(l) for l in jf.open()]
            changed = False
            for r in recs:
                if r["type"] == "treatise":
                    continue
                v = norm(r["base_headword"])
                if v not in vmap:
                    continue
                canon, meta = vmap[v]
                old_base, old_hw = r["base_headword"], r["headword"]
                prov = r.setdefault("provenance", {})
                prov["raw_headword"] = old_hw
                prov["raw_base_headword"] = old_base
                prov["headword_correction"] = meta
                r["base_headword"] = canon
                # Substitute old_base only where it stands as a complete token, so a
                # truncated caps-prefix base (e.g. "SNOW-D" inside "SNOW-Drop") cannot
                # corrupt the surrounding headword into "SNOWDONrop". Fall back to the
                # bare canonical when no whole-token match exists.
                anchored = re.sub(rf"(?<![A-Za-z]){re.escape(old_base)}(?![A-Za-z-])",
                                  canon, old_hw, count=1)
                r["headword"] = anchored if anchored != old_hw else canon
                changed = True
                total_recs += 1
            if changed and not args.dry_run:
                with jf.open("w", encoding="utf-8") as fh:
                    for r in recs:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"records rewritten: {total_recs}" + ("  (dry-run, nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
