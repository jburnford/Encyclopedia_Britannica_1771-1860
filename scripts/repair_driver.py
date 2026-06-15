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


def keyof(obj, fields):
    return obj[fields[0]] if len(fields) == 1 else tuple(obj[f] for f in fields)


def batch_indices(path, fields):
    return {keyof(c, fields) for c in json.loads(path.read_text())}


def decided_set(decisions_path, fields):
    if not Path(decisions_path).exists():
        return set()
    out = set()
    for line in open(decisions_path):
        line = line.strip()
        if line:
            out.add(keyof(json.loads(line), fields))
    return out


MODES = {
    # mode -> (key fields, Workflow result key, fields to persist, candidates file)
    # Both passes key on a single global int i (agents mis-copy filename strings between
    # adjacent items, so file/ln are never trusted from the agent). The absorbed merge
    # resolves i -> the authoritative (file, ln) from the candidates and persists those
    # (plus i) so apply_absorbed_splits can still join by (file, ln).
    "headword": (["i"], "decisions", ["i", "decision", "canonical"], None),
    "absorbed": (["i"], "results", ["file", "ln", "i", "splits"],
                 "absorbed_candidates.jsonl"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "next", "merge"])
    ap.add_argument("--mode", choices=list(MODES), default="headword")
    ap.add_argument("--batch-dir", default=None)
    ap.add_argument("--decisions", default=None)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--inbox", default="repair_batches/_inbox.json")
    args = ap.parse_args()

    fields, result_key, persist, cand_default = MODES[args.mode]
    batch_dir = args.batch_dir or f"repair_batches/{args.mode}"
    decisions = args.decisions or (
        "headword_decisions.jsonl" if args.mode == "headword"
        else "absorbed_splits.jsonl")

    batches = sorted(Path(batch_dir).glob("batch_*.json"))
    decided = decided_set(decisions, fields)

    if args.cmd == "merge":
        # absorbed: build i -> (file, ln) from the candidates so the agent's
        # (untrusted) file/ln are replaced by the canonical ones.
        loc = {}
        if args.mode == "absorbed":
            cpath = args.candidates or cand_default
            for ix, line in enumerate(open(cpath)):
                c = json.loads(line)
                loc[ix] = (c["file"], c["ln"])
        raw = json.loads(Path(args.inbox).read_text())
        rows = raw[result_key] if isinstance(raw, dict) else raw
        added = skipped = bad = 0
        with open(decisions, "a") as fh:
            for d in rows:
                k = keyof(d, fields)
                if k in decided:
                    skipped += 1
                    continue
                rec = dict(d)
                if args.mode == "absorbed":
                    if d["i"] not in loc:
                        bad += 1
                        continue
                    rec["file"], rec["ln"] = loc[d["i"]]
                fh.write(json.dumps({f: rec.get(f) for f in persist},
                                    ensure_ascii=False) + "\n")
                decided.add(k)
                added += 1
        msg = f"merged: +{added} new, {skipped} already-present"
        if bad:
            msg += f", {bad} unmappable-i dropped"
        print(msg + f" -> {len(decided)} total decided")
        return

    undone = [b for b in batches if not batch_indices(b, fields) <= decided]
    if args.cmd == "status":
        total_c = sum(len(batch_indices(b, fields)) for b in batches)
        print(f"batches: {len(batches) - len(undone)}/{len(batches)} done | "
              f"candidates decided: {len(decided)}/{total_c} | "
              f"batches remaining: {len(undone)}")
        return

    # next: print the next K undone batch paths
    print(" ".join(str(b) for b in undone[:args.count]))


if __name__ == "__main__":
    main()
