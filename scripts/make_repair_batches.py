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


def compact_absorbed(i, c):
    # absorbed-split items are keyed by (file, ln); the split workflow echoes those
    # back. Carry the full body so the agent can locate each absorbed start_text.
    return {
        "file": c["file"],
        "ln": c["ln"],
        "absorber_headword": c["absorber_headword"],
        "body": c["body"],
        "absorbed": [{"norm": a["norm"], "headword": a["headword"], "ref": a["ref"]}
                     for a in c["absorbed"]],
    }


COMPACT = {"headword": compact_headword, "absorbed": compact_absorbed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["headword", "absorbed"], default="headword")
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--per-batch", type=int, default=0)
    args = ap.parse_args()

    # mode-aware defaults: absorbed items carry big bodies, so far fewer per batch
    cand = args.candidates or (
        "headword_candidates.jsonl" if args.mode == "headword"
        else "absorbed_candidates.jsonl")
    out = Path(args.out_dir or f"repair_batches/{args.mode}")
    per = args.per_batch or (40 if args.mode == "headword" else 8)
    compact = COMPACT[args.mode]

    rows = [json.loads(l) for l in open(cand)]
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("batch_*.json"):       # clear stale batches (no orphans)
        old.unlink()

    n = 0
    for b, start in enumerate(range(0, len(rows), per)):
        chunk = [compact(start + j, rows[start + j])
                 for j in range(min(per, len(rows) - start))]
        (out / f"batch_{b:04d}.json").write_text(
            json.dumps(chunk, ensure_ascii=False, indent=0))
        n += 1
    print(f"{len(rows)} {args.mode} candidates -> {n} batch files of <= {per} in {out}/")


if __name__ == "__main__":
    main()
