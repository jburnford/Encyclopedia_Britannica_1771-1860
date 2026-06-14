#!/usr/bin/env python3
"""Resumable driver for the adjudication / absorbed-split Workflows.

Keeps the LLM fan-out crash- and usage-limit-safe by tracking progress in an
on-disk decisions accumulator keyed by the candidate's global index `i`:

  status  -- how many batches / candidates are decided
  next    -- print the next K batch files that still have undecided candidates
             (paste into the Workflow `files` arg)
  merge   -- fold a Workflow's returned decisions (a JSON file: either
             {"decisions":[...]} or a bare [...]) into the decisions JSONL,
             skipping any `i` already present. Safe to re-run a batch: only new
             `i`s are appended.

A batch is "done" when every candidate `i` in it appears in the decisions file,
so an interrupted run simply re-lists its unfinished batches next time.
"""
import argparse
import json
from pathlib import Path


def batch_indices(path):
    return {c["i"] for c in json.loads(path.read_text())}


def decided_set(decisions_path):
    if not Path(decisions_path).exists():
        return set()
    out = set()
    for line in open(decisions_path):
        line = line.strip()
        if line:
            out.add(json.loads(line)["i"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "next", "merge"])
    ap.add_argument("--batch-dir", default="repair_batches/headword")
    ap.add_argument("--decisions", default="headword_decisions.jsonl")
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--inbox", default="repair_batches/_inbox.json")
    args = ap.parse_args()

    batches = sorted(Path(args.batch_dir).glob("batch_*.json"))
    decided = decided_set(args.decisions)

    if args.cmd == "merge":
        raw = json.loads(Path(args.inbox).read_text())
        rows = raw["decisions"] if isinstance(raw, dict) else raw
        added = skipped = 0
        with open(args.decisions, "a") as fh:
            for d in rows:
                if d["i"] in decided:
                    skipped += 1
                    continue
                fh.write(json.dumps({"i": d["i"], "decision": d["decision"],
                                     "canonical": d.get("canonical")},
                                    ensure_ascii=False) + "\n")
                decided.add(d["i"])
                added += 1
        print(f"merged: +{added} new, {skipped} already-present "
              f"-> {len(decided)} total decided")
        return

    undone = [b for b in batches if not batch_indices(b) <= decided]
    if args.cmd == "status":
        total_c = sum(len(batch_indices(b)) for b in batches)
        print(f"batches: {len(batches) - len(undone)}/{len(batches)} done | "
              f"candidates decided: {len(decided)}/{total_c} | "
              f"batches remaining: {len(undone)}")
        return

    # next: print the next K undone batch paths
    print(" ".join(str(b) for b in undone[:args.count]))


if __name__ == "__main__":
    main()
