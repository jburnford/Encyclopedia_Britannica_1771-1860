#!/usr/bin/env python3
"""Cross-edition headword OCR-error detector.

The Britannica editions (EB.1/4/5/9/10/11) are largely re-set reprints of one
another, so the *same* article headword recurs across editions. That redundancy
lets us flag OCR-garbled headwords: a spelling that appears in only ONE edition
("CONSTANTINOPE") is suspicious when a near-identical spelling ("CONSTANTINOPLE")
is confirmed in several others at the same alphabetical position.

This script does the deterministic half of the repair pipeline: detect singleton
headwords and, for each, propose canonical corrections with enough context for an
LLM (stage 2) to make the final call. It does NOT edit any records.

Signals used to keep precision high (each prunes a class of false match):
  * alphabetical adjacency  -- a true OCR variant sorts next to its correct form
    (CONSTANTINOPE | CONSTANTINOPLE); ELOPS vs EPOPS are hundreds of words apart.
  * shared prefix           -- reject early-letter coincidences.
  * edit distance <= 2      -- OCR garbles are small.
  * co-occurrence test      -- THE edition signal: if the singleton's own edition
    also contains the candidate spelling, they are distinct real words (an edition
    will not hold both EASTER and a mangled EASTER) -> never propose it.
  * vote count              -- how many editions confirm the candidate (more=safer).

Output: headword_candidates.jsonl, one record per suspicious singleton with the
records carrying it, ranked suggestions, alphabetical neighbours, and a body
snippet. Stage 2 (LLM) reads this and writes headword_decisions.jsonl.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

EDS = ["EB.1", "EB.4", "EB.5", "EB.7", "EB.9", "EB.10", "EB.11", "EB.12", "EB.15", "EB.16"]
WINDOW = 30          # alphabetical neighbourhood half-width for candidate search
MAX_EDIT = 2


def norm(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def lev(a, b, maxd=MAX_EDIT):
    if abs(len(a) - len(b)) > maxd:
        return maxd + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > maxd:
            return maxd + 1
        prev = cur
    return prev[-1]


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def load(article_dir):
    """Return (present, vocab_sorted, records_by_key).
    present[norm] = set(editions); records_by_key[(ed,norm)] = list of record locators."""
    present = defaultdict(set)
    records = defaultdict(list)
    for ed in EDS:
        for jf in sorted(article_dir.glob(f"{ed}_*.jsonl")):
            with jf.open() as fh:
                for ln, line in enumerate(fh):
                    r = json.loads(line)
                    if r["type"] == "treatise":
                        continue
                    k = norm(r["base_headword"])
                    if len(k) < 3:
                        continue
                    present[k].add(ed)
                    records[(ed, k)].append({
                        "file": jf.name, "line": ln,
                        "headword": r["headword"], "base_headword": r["base_headword"],
                        "char_count": r["char_count"],
                        "snippet": (r["body_text"] or "")[:160],
                        "is_xref": r.get("is_cross_reference", False),
                    })
    return present, sorted(present), records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--out", default="headword_candidates.jsonl")
    args = ap.parse_args()
    adir = Path(args.article_dir)

    present, vocab, records = load(adir)
    confirmed = {k for k, e in present.items() if len(e) >= 2}
    pos = {k: i for i, k in enumerate(vocab)}
    singletons = [k for k, e in present.items() if len(e) == 1]

    cands = []
    for s in singletons:
        s_ed = next(iter(present[s]))
        i = pos[s]
        sugg = []
        for c in vocab[max(0, i - WINDOW):i + WINDOW]:
            if c == s or c not in confirmed:
                continue
            if abs(len(c) - len(s)) > MAX_EDIT:
                continue
            d = lev(s, c)
            if d > MAX_EDIT:
                continue
            if common_prefix(s, c) < max(2, (min(len(s), len(c)) + 1) // 2):
                continue
            if s_ed in present[c]:           # co-occurrence -> distinct real words
                continue
            sugg.append({"canonical": records[(min(present[c]), c)][0]["base_headword"],
                         "norm": c, "edit_distance": d,
                         "n_editions": len(present[c]),
                         "editions": sorted(present[c])})
        if not sugg:
            continue
        sugg.sort(key=lambda x: (x["edit_distance"], -x["n_editions"]))
        recs = records[(s_ed, s)]
        # alphabetical neighbours (any spelling) for context
        nb = [vocab[j] for j in range(max(0, i - 2), min(len(vocab), i + 3)) if j != i]
        cands.append({
            "variant": s, "edition": s_ed,
            "n_records": len(recs),
            "records": recs[:5],
            "suggestions": sugg[:4],
            "neighbors": nb,
            "snippet": recs[0]["snippet"],
        })

    # rank: easiest/safest first (single d=1 suggestion confirmed widely)
    def conf(c):
        s = c["suggestions"]
        return (s[0]["edit_distance"], -s[0]["n_editions"], len(s))
    cands.sort(key=conf)

    with Path(args.out).open("w") as fh:
        for c in cands:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_d1 = sum(1 for c in cands if c["suggestions"][0]["edit_distance"] == 1)
    n_unique = sum(1 for c in cands if len(c["suggestions"]) == 1
                   or c["suggestions"][0]["edit_distance"] < c["suggestions"][1]["edit_distance"])
    n_wide = sum(1 for c in cands if c["suggestions"][0]["n_editions"] >= 4)
    print(f"singletons: {len(singletons)}  ->  candidates with suggestion(s): {len(cands)}")
    print(f"  edit_distance 1: {n_d1}   unique-best: {n_unique}   top-suggestion in >=4 eds: {n_wide}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
