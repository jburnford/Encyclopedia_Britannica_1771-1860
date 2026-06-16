#!/usr/bin/env python3
"""Surgical fixes to the absorbed-article pass (Stage A of the cleanup):

  WIND      -- the main WIND treatise is still welded inside the WINCKLEMAN
               record (EB.5 v18); split it out as its own article.
  SUPERIOR  -- the relabel step discarded SUPERIOR's own 67-char article when it
               renamed the absorber to SUPERSTITION (EB.10 v20); re-insert it,
               recovered from the pre-split commit dc1c8fe.
  BOLEYN    -- the split cut the BOLEYN article mid-word ("...Eng-|land;"),
               losing its "BOLEYN, queen of England" opening (EB.5 v03); restore
               the full text from the pre-split BOLETUS absorber at dc1c8fe.
  VOL junk  -- delete the 4 blank-flyleaf "VOL<roman>" treatise records in EB.16
               whose body is the Chandra "This image shows a blank…" alt-text.
               (VOLXIV/XIX/XX hold real content and are fixed by the Stage B
               re-parse, so they are left alone here.)

Run with --dry-run first. Reversible from git.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_absorbed_splits import seg_html, is_cross_reference, extract_cross_refs

PRESPLIT = "dc1c8fe"


def git_records(commit, path):
    out = subprocess.run(["git", "show", f"{commit}:{path}"],
                         capture_output=True, text=True, check=True).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def load(path):
    return [json.loads(l) for l in Path(path).open()]


def save(path, recs, dry):
    if dry:
        return
    with Path(path).open("w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def new_article(template, headword, body, source):
    """Clone metadata from `template`, install a recovered article body."""
    body = body.strip()
    r = {k: template[k] for k in (
        "type", "volume_num", "eb_code", "identifier", "alpha_range",
        "printed_page_start", "printed_page_end", "image_page_start",
        "image_page_end") if k in template}
    r.update({
        "headword": headword, "base_headword": headword, "qualifier": None,
        "type": "article", "detected_by": "absorption-split",
        "is_cross_reference": is_cross_reference(headword, body),
        "body_text": body, "body_html": seg_html(body),
        "cross_refs": extract_cross_refs(body)[:50], "char_count": len(body),
        "provenance": {"recovered_by": "revert_bad_repairs", "source": source},
    })
    return r


def fix_wind(adir, dry):
    p = f"{adir}/EB.5_ed3_v18_STR-ZYM_191253817.jsonl"
    recs = load(p)
    out = []
    done = False
    for r in recs:
        out.append(r)
        if r["base_headword"] == "WINCKLEMAN" and not done:
            b = r["body_text"]
            off = b.find("WIND is a sensible agitation")
            if off < 10:
                print("  WIND: marker not found, skipped")
                continue
            wind_body = b[off:].strip()
            r["body_text"] = b[:off].strip()
            r["body_html"] = seg_html(r["body_text"])
            r["char_count"] = len(r["body_text"])
            r.setdefault("provenance", {})["absorbed_split_fix"] = "split out WIND treatise"
            wind = new_article(r, "WIND", wind_body, "absorbed-fix:WINCKLEMAN")
            out.append(wind)
            done = True
            print(f"  WIND: split out {len(wind_body)} chars; WINCKLEMAN now {r['char_count']}")
    save(p, out, dry)


def fix_superior(adir, dry):
    p = f"{adir}/EB.10_ed5_v20_SUI-ZYM_191678899.jsonl"
    pre = git_records(PRESPLIT, f"article_data/EB.10_ed5_v20_SUI-ZYM_191678899.jsonl")
    pre_sup = next(r for r in pre if r["base_headword"] == "SUPERIOR")
    recs = load(p)
    out = []
    for r in recs:
        if r["base_headword"] == "SUPERSTITION" and r.get("provenance", {}).get("relabeled_from") == "SUPERIOR":
            cut = len(pre_sup["body_text"]) - len(r["body_text"])
            sup_body = pre_sup["body_text"][:cut].strip()
            if not sup_body.upper().startswith("SUPERIOR"):
                print(f"  SUPERIOR: unexpected boundary ({sup_body[:30]!r}), skipped")
                out.append(r)
                continue
            sup = new_article(r, "SUPERIOR", sup_body, "absorbed-fix:relabel-recover")
            out.append(sup)
            r.get("provenance", {}).pop("relabeled_from", None)
            out.append(r)
            print(f"  SUPERIOR: re-inserted {len(sup_body)}-char article: {sup_body!r}")
        else:
            out.append(r)
    save(p, out, dry)


def fix_boleyn(adir, dry):
    p = f"{adir}/EB.5_ed3_v03_BAR-BZO_149977873.jsonl"
    pre = git_records(PRESPLIT, f"article_data/EB.5_ed3_v03_BAR-BZO_149977873.jsonl")
    pre_bol = next(r for r in pre if r["base_headword"] == "BOLETUS")
    recs = load(p)
    cur_bol = next(r for r in recs if r["base_headword"] == "BOLETUS")
    boleyn_body = pre_bol["body_text"][len(cur_bol["body_text"]):].strip()
    for r in recs:
        if r["base_headword"] == "BOLEYN":
            old = r["char_count"]
            r["body_text"] = boleyn_body
            r["body_html"] = seg_html(boleyn_body)
            r["char_count"] = len(boleyn_body)
            r["cross_refs"] = extract_cross_refs(boleyn_body)[:50]
            r.setdefault("provenance", {})["absorbed_split_fix"] = "restored opening from dc1c8fe"
            print(f"  BOLEYN: body {old} -> {r['char_count']} chars; now starts {boleyn_body[:40]!r}")
    save(p, recs, dry)


def fix_vol(adir, dry):
    n = 0
    for jf in sorted(Path(adir).glob("EB.16_*.jsonl")):
        recs = load(jf)
        keep = []
        for r in recs:
            blank = r["body_text"].lstrip()[:30].lower().startswith("this image shows a blank")
            if (r.get("type") == "treatise" and re.fullmatch(r"VOL[IVXLC]+", r["base_headword"] or "")
                    and blank):
                n += 1
                print(f"  VOL: delete {r['base_headword']!r} ({jf.name})")
                continue
            keep.append(r)
        if len(keep) != len(recs):
            save(jf, keep, dry)
    print(f"  VOL: {n} blank-flyleaf records deleted")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print("WIND:");      fix_wind(args.article_dir, args.dry_run)
    print("SUPERIOR:");  fix_superior(args.article_dir, args.dry_run)
    # BOLEYN is NOT fixed here: the "BOLEYN, queen of England" opening was already
    # absent at the pre-split commit (dc1c8fe) — an OCR column-break loss, not an
    # absorbed-split bug — so the current body is faithful to the parsed source.
    print("BOLEYN: skipped (pre-existing OCR loss, not a split bug)")
    print("VOL junk:");  fix_vol(args.article_dir, args.dry_run)
    if args.dry_run:
        print("\n(dry-run, nothing written)")


if __name__ == "__main__":
    main()
