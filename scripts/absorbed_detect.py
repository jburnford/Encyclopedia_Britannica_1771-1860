#!/usr/bin/env python3
"""Detect "absorbed article" cases for the cross-edition repair pipeline.

Companion to headword_reconcile.py. That script fixes headwords that are present
but MISSPELLED. This one finds headwords that are MISSING entirely from an edition
because the parser never saw a heading (the OCR didn't set it off) and the article
body was welded onto the preceding record — e.g. EB.9's PERSEUS record (141K chars)
actually contains both PERSEUS *and* the whole PERSIA article; PERSIA has no record.

Detection (two signals, both required):
  1. an oversized record  R in edition E: char_count >> median of the same headword
     in the other editions (>3x and +8000 absolute);
  2. one or more headwords that sort right after R in E, are PRESENT in >=3 other
     editions, but are ABSENT in E -> the likely absorbed article(s).

Output: absorbed_candidates.jsonl, one per absorber, with the full body and the
ordered list of expected absorbed headwords (each with a reference snippet from an
edition that has it). Stage 2 (LLM) locates each article's start in the body; stage
3 splits them into their own records.
"""
import argparse
import bisect
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

CORE = ["EB.4", "EB.5", "EB.7", "EB.9", "EB.10", "EB.11", "EB.12", "EB.15", "EB.16"]


def norm(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--out", default="absorbed_candidates.jsonl")
    args = ap.parse_args()
    adir = Path(args.article_dir)

    recs_by_ed = defaultdict(list)
    size_by_word = defaultdict(dict)
    present = defaultdict(set)
    snippet_by_word = {}                 # norm -> a reference body snippet from some edition
    body_index = {}                      # (edition, file, ln) -> not stored; we re-read on demand

    for ed in CORE:
        for jf in sorted(adir.glob(f"{ed}_*.jsonl")):
            for ln, l in enumerate(jf.open()):
                r = json.loads(l)
                if r["type"] == "treatise":
                    continue
                k = norm(r["base_headword"])
                if len(k) < 3:
                    continue
                recs_by_ed[ed].append({"k": k, "hw": r["headword"], "base": r["base_headword"],
                                       "cc": r["char_count"], "file": jf.name, "ln": ln})
                present[k].add(ed)
                size_by_word[k][ed] = max(size_by_word[k].get(ed, 0), r["char_count"])
                if k not in snippet_by_word and r["char_count"] > 40:
                    snippet_by_word[k] = (r["base_headword"], (r["body_text"] or "")[:140])

    vocab_by_ed = {ed: sorted(set(r["k"] for r in recs_by_ed[ed])) for ed in CORE}
    allwords = sorted(present)

    # an absorbed headword W (present in >=3 other editions, absent in E, sorting after
    # the absorber) is collected by EITHER signal:
    #   adjacency  -- W sorts between the absorber and its immediate E-successor (catches
    #                 contiguous runs even when their text appears only as garbled headings);
    #   body match -- W's text appears in the absorber's body (catches welds where a
    #                 present-in-E article sits between them, e.g. PERSEVERANCE between
    #                 PERSEUS and the absorbed PERSIA). Bounded to the same first 2 letters
    #                 to avoid coincidental hits deep inside a very long body.
    def token_in(w, body_upper):
        return re.search(r"\b" + re.escape(w[:max(5, len(w) - 1)]), body_upper) is not None

    # pre-read bodies of all oversized records so the body signal can run
    oversized = []                       # (ed, r, med)
    for ed in CORE:
        others = set(e for e in CORE if e != ed)
        for r in recs_by_ed[ed]:
            elsewhere = [size_by_word[r["k"]][e] for e in others if e in size_by_word[r["k"]]]
            if len(elsewhere) < 3:
                continue
            med = statistics.median(elsewhere)
            if med > 0 and r["cc"] > 3 * med and r["cc"] - med > 8000:
                oversized.append((ed, r, med))

    want = defaultdict(set)
    for ed, r, med in oversized:
        want[r["file"]].add(r["ln"])
    bodies = {}
    for fn, lns in want.items():
        for ln, l in enumerate((adir / fn).open()):
            if ln in lns:
                bodies[(fn, ln)] = json.loads(l)

    cands = []
    for ed, r, med in oversized:
        others = set(e for e in CORE if e != ed)
        vocab = vocab_by_ed[ed]
        body = bodies[(r["file"], r["ln"])]["body_text"]
        bu = body.upper()
        vi = bisect.bisect_right(vocab, r["k"])
        succ = vocab[vi] if vi < len(vocab) else "ZZZZZZZZ"
        lo = bisect.bisect_right(allwords, r["k"])

        def qualifies(w):
            return ed not in present[w] and len(present[w] & others) >= 3

        # adjacency: everything between absorber and its immediate E-successor
        adj = {w for w in allwords[lo:bisect.bisect_left(allwords, succ)] if qualifies(w)}
        # body match: same first 2 letters, text present in the body
        body_hits = {w for w in allwords[lo:bisect.bisect_left(allwords, r["k"][:2] + "ZZZZZZ")]
                     if qualifies(w) and token_in(w, bu)}
        miss = adj | body_hits
        if miss:
            cands.append((ed, r, med, sorted(miss)))

    n = 0
    with Path(args.out).open("w") as fh:
        for ed, r, med, missing in cands:
            rec = bodies[(r["file"], r["ln"])]
            absorbed = [{"headword": snippet_by_word.get(w, (w, ""))[0],
                         "norm": w,
                         "ref": snippet_by_word.get(w, (w, ""))[1],
                         "n_editions": len(present[w])}
                        for w in missing]
            fh.write(json.dumps({
                "edition": ed, "file": r["file"], "ln": r["ln"],
                "absorber_headword": r["hw"], "absorber_base": r["base"],
                "absorber_cc": r["cc"], "median_elsewhere": int(med),
                "absorbed": absorbed,
                "body": rec["body_text"],
            }, ensure_ascii=False) + "\n")
            n += 1
    print(f"absorber candidates: {n}  (total absorbed articles: {sum(len(m) for *_, m in cands)})")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
