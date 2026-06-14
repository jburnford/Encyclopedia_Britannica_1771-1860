#!/usr/bin/env python3
"""Split a repair-candidate JSONL into small, resumable batch files for the
adjudication / absorbed-split Workflows.

Each batch file is a JSON array of compact candidate objects carrying a GLOBAL
index `i` (== line number in the source candidates file), so decisions can be
accumulated into a single decisions JSONL and applied regardless of how the work
was chunked across sessions. Small batches + an external decisions accumulator
make the pipeline crash/usage-limit safe: a finished batch's decisions are
written to disk by the driver and never recomputed.

Headword candidates -> compact {i, v, ed, sug:[{n,d,ne}], snip}
  (matches the field names adjudicate_workflow.js's prompt expects)

Usage:
  python3 scripts/make_repair_batches.py \
      --candidates headword_candidates.jsonl \
      --out-dir repair_batches/headword --per-batch 40
"""
import argparse
import json
from pathlib import Path


def compact_headword(i, c):
    return {
        "i": i,
        "v": c["variant"],
        "ed": c["edition"],
        "sug": [{"n": s["norm"], "d": s["edit_distance"], "ne": s["n_editions"]}
                for s in c["suggestions"]],
        "snip": c.get("snippet", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="headword_candidates.jsonl")
    ap.add_argument("--out-dir", default="repair_batches/headword")
    ap.add_argument("--per-batch", type=int, default=40)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.candidates)]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # clear any stale batch files so a re-split can't leave orphans
    for old in out.glob("batch_*.json"):
        old.unlink()

    n = 0
    for b, start in enumerate(range(0, len(rows), args.per_batch)):
        chunk = [compact_headword(start + j, rows[start + j])
                 for j in range(min(args.per_batch, len(rows) - start))]
        (out / f"batch_{b:04d}.json").write_text(
            json.dumps(chunk, ensure_ascii=False, indent=0))
        n += 1
    print(f"{len(rows)} candidates -> {n} batch files of <= {args.per_batch} "
          f"in {out}/")


if __name__ == "__main__":
    main()
