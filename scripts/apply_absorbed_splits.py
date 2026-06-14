#!/usr/bin/env python3
"""Apply absorbed-article splits to article_data/.

Stage 3 of the absorbed-article track:
  1. absorbed_detect.py  -> absorbed_candidates.jsonl  (oversized record + expected absorbed heads)
  2. split_workflow.js   -> absorbed_splits.jsonl       (LLM: verbatim start_text per absorbed head)
  3. THIS script         -> splits each absorber body, inserts recovered article records

For each absorber the located start_texts partition its body_text. The first segment
stays with the absorber (its own article); each later segment becomes a NEW record
carrying the recovered headword. New records inherit the absorber's page span and are
flagged detected_by="absorption-split"; the absorber keeps an audit note in provenance.
Run with --dry-run first.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_articles import extract_cross_refs, is_cross_reference  # noqa: E402

WS = re.compile(r"\s+")


def find_offset(body, start_text):
    """Locate start_text in body tolerant of whitespace differences; return char
    offset in the ORIGINAL body or None."""
    if not start_text:
        return None
    off = body.find(start_text)
    if off >= 0:
        return off
    # whitespace-normalised search with an index map back to the original
    norm_chars, idx_map = [], []
    prev_ws = False
    for i, ch in enumerate(body):
        if ch.isspace():
            if prev_ws:
                continue
            norm_chars.append(" ")
            idx_map.append(i)
            prev_ws = True
        else:
            norm_chars.append(ch)
            idx_map.append(i)
            prev_ws = False
    nbody = "".join(norm_chars)
    ntarget = WS.sub(" ", start_text).strip()
    p = nbody.find(ntarget)
    if p < 0 and len(ntarget) > 24:
        p = nbody.find(ntarget[:24])           # fall back to a distinctive prefix
    return idx_map[p] if p >= 0 else None


def seg_html(text):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return "\n".join(f"<p>{p}</p>" for p in paras) or f"<p>{text.strip()}</p>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--candidates", default="absorbed_candidates.jsonl")
    ap.add_argument("--splits", default="absorbed_splits.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    adir = Path(args.article_dir)

    # canonical display name per absorbed norm, per absorber
    cand = {}
    for l in open(args.candidates):
        c = json.loads(l)
        disp = {a["norm"]: a["headword"] for a in c["absorbed"]}
        cand[(c["file"], c["ln"])] = disp

    # split results, keyed by (file, ln)
    splits = {}
    for l in open(args.splits):
        s = json.loads(l)
        splits[(s["file"], s["ln"])] = s["splits"]

    # group target lines per file
    per_file = defaultdict(dict)
    for (fn, ln) in splits:
        per_file[fn][ln] = splits[(fn, ln)]

    n_new = n_absorbers = n_unlocated = 0
    for fn, lnmap in per_file.items():
        path = adir / fn
        recs = [json.loads(l) for l in path.open()]
        out = []
        for i, r in enumerate(recs):
            if i not in lnmap or "absorbed_split" in r.get("provenance", {}):
                out.append(r)                       # not a target, or already split (idempotent)
                continue
            disp = cand.get((fn, i), {})
            body = r["body_text"]
            # locate each found split
            pts = []
            for sp in lnmap[i]:
                if not sp.get("found"):
                    continue
                off = find_offset(body, sp.get("start_text", ""))
                if off is None or off < 10:         # offset 0 = no real boundary
                    n_unlocated += 1
                    continue
                pts.append((off, sp["norm"]))
            if not pts:
                out.append(r)
                continue
            pts.sort()
            dedup = []                              # dedupe near-identical offsets
            for off, nm in pts:
                if dedup and off - dedup[-1][0] < 40:
                    continue
                dedup.append((off, nm))
            pts = dedup
            n_absorbers += 1
            orig_cc, orig_hw = r["char_count"], r["headword"]

            # pieces: the absorber's own article first, then each absorbed article
            pieces = [(0, pts[0][0], orig_hw, r["base_headword"])]
            for j, (off, nm) in enumerate(pts):
                end = pts[j + 1][0] if j + 1 < len(pts) else len(body)
                pieces.append((off, end, disp.get(nm, nm), disp.get(nm, nm)))
            # if the absorber's own segment is negligible (a marginal-note scrap, e.g.
            # PERSEUS = "1 Extent of Persia." before the whole PERSIA article), drop it
            # and let the absorber record BECOME the first recovered article.
            relabel = (pieces[0][1] - pieces[0][0]) < 150
            if relabel:
                pieces = pieces[1:]

            s0, e0, hw0, base0 = pieces[0]
            seg0 = body[s0:e0].strip()
            r["body_text"] = seg0
            r["body_html"] = seg_html(seg0)
            r["char_count"] = len(seg0)
            if relabel:
                r["headword"], r["base_headword"] = hw0, base0
                r["detected_by"] = "absorption-split"
                r["is_cross_reference"] = is_cross_reference(hw0, seg0)
                r["cross_refs"] = extract_cross_refs(seg0)[:50]
            prov = r.setdefault("provenance", {})
            prov["absorbed_split"] = {
                "recovered": [p[2] for p in pieces[1:]], "original_char_count": orig_cc,
                "source": "cross-edition-absorption+llm"}
            if relabel:
                prov["relabeled_from"] = orig_hw
            out.append(r)
            for s, e, hw, base in pieces[1:]:
                seg = body[s:e].strip()
                out.append({
                    "headword": hw, "base_headword": base, "qualifier": None,
                    "type": "article", "detected_by": "absorption-split",
                    "is_cross_reference": is_cross_reference(hw, seg),
                    "volume_num": r["volume_num"], "eb_code": r["eb_code"],
                    "identifier": r["identifier"], "alpha_range": r["alpha_range"],
                    "printed_page_start": r["printed_page_start"], "printed_page_end": r["printed_page_end"],
                    "image_page_start": r["image_page_start"], "image_page_end": r["image_page_end"],
                    "body_text": seg, "body_html": seg_html(seg),
                    "cross_refs": extract_cross_refs(seg)[:50], "char_count": len(seg),
                    "provenance": {"split_from": orig_hw, "source": "cross-edition-absorption+llm"},
                })
                n_new += 1
        if not args.dry_run:
            with path.open("w", encoding="utf-8") as fh:
                for r in out:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"absorbers split: {n_absorbers}   recovered records: {n_new}   "
          f"unlocated start_texts: {n_unlocated}"
          + ("   (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
