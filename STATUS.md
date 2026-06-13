# Project status

_Snapshot: 2026-06-13._ Encyclopaedia Britannica (NLS Foundry *1768–1860* dataset) →
OCR → HTML → structured article records, toward a knowledge graph.

Three stages. OCR and HTML are **complete for all 163 selected volumes**; article
parsing is **complete and validated for the 1771 first edition (EB.1)** as a pilot.

---

## Stage 1 — OCR (complete)

Chandra 2 on Nibi H100s, headers/footers kept. See `README.md` for the pipeline.

- **163 / 163 volumes** OCR'd (one copy per edition: EB.1, 4, 5, 7, 9, 10, 11, 12, 15, 16).
- **126,966 pages**, 0 OCR errors. Verified against the source manifest: 0 page-count mismatches.
- Output on Nibi at `/project/def-jic823/britannica_chandra2/output/` and synced locally to
  `output/<EB>/<id>/` (`pages.jsonl`, `<id>.md`, `metadata.json`, `COMPLETE`). `output/` is gitignored.

## Stage 2 — HTML (complete)

- `scripts/build_html.py` — one self-contained, styled HTML per volume from each `pages.jsonl`
  (`raw` layout field), `data-label`-aware; src-less `<img>` alt text rendered as placeholders.
- `scripts/flatten_html.py` — copies into `html/` with descriptive names
  (`<eb>_<edition>_v<NN>_<alpha>_<id>.html`) + `html/index.csv` mapping back to source.
- **163 HTML files** committed and pushed to GitHub
  (`github.com/jburnford/Encyclopedia_Britannica_1771-1860`, public).

## Stage 3 — Article parsing (EB.1 pilot complete)

`scripts/parse_articles.py` segments the page-stream into one record per dictionary headword,
with long treatises as single records. Run: `python3 scripts/parse_articles.py --only EB.1 --report`.
Output: `output/EB.1/<id>/articles.jsonl`.

### EB.1 (1771 first edition) — all 3 volumes

| Volume | Range | Records | articles | sub_entries | treatises |
|--------|-------|--------:|---------:|------------:|----------:|
| 144133901 v1 | A–B | 5,545 | 4,905 | 628 | 12 |
| 144133902 v2 | C–L | 7,201 | 6,698 | 489 | 14 |
| 144133903 v3 | M–Z | 6,205 | 5,983 | 205 | 17 |
| **Total** | A–Z | **18,951** | **17,586** | **1,322** | **43** |

Detection signals: **bold** at paragraph start 16,146 · **all-caps-plain** 2,549 · **run-on**
(stub clusters split) 213 · **treatise** 43. Precision ~100% on hand-checked random samples;
treatise inventory matches the canonical EB.1 set (ANATOMY 175pp, ASTRONOMY, CHEMISTRY, OPTICS,
SURGERY, LAW = "Principles of the Law of Scotland", …).

### Record schema

`headword, base_headword, qualifier, type` (`article|sub_entry|treatise`), `detected_by`,
`volume_num, eb_code, identifier, alpha_range, printed_page_start/end` (from the "( N )" running
head), `image_page_start/end` (jsonl index), `body_text, body_html, cross_refs[], char_count,
provenance{image_files, headword_bbox, headword_image}`. Treatises add a nested `outline[]`
(PART/CHAP/SECT). Variants group by `(volume_num, base_headword)`.

### How it works (key decisions)

- **Headwords**: bold at paragraph start (drop-cap initials extended, e.g. `<b>A</b>NATOMY`→ANATOMY);
  all-caps-plain + comma as a recall fallback, matched on the *full* paragraph text so italic-wrapped
  / empty-`p.text` headwords are caught; run-on `<p>`s of stub entries split per line.
- **Treatises** = gaps in the page-header trigram sequence (robust to OCR letter-spacing and
  recto/verso "Part II." alternation), with an h2-banner fallback for short running heads (LAW → "L").
- **Reading order** = Chandra's native block order (a `(column,y)` re-sort was found to scramble
  multi-column pages — removed).
- **Cross-references** ("See X") excluded structurally; structural markers ("PLATE IV", "FIG. 3")
  rejected only when followed by a number/roman.

### Validation

Audited via a random-sampling loop (50 articles/iteration + a global bleed scan), fixing the parser
and re-parsing until samples came back clean. Four systematic bugs found and fixed: cross-column
bleed (reading order), italic-first/empty-`p.text` headwords, `NON_HEADWORD` over-rejection
(CASE/BOOK/TABLE/FIGURE/INDEX), and plate-caption bleed. Net recovered ~490 records vs. the first
pass and eliminated the large bleed cases.

### Known limitations (OCR-level, acceptable for the pilot)

- ~57 records with `body == headword` — standalone `<p><b>X</b></p>` whose definition attached elsewhere.
- Occasional two entries merged when OCR joins them in one `<p>` with no separator (e.g. "c. 2.CALLUS").
- ~3 dict pages dropped where an article starts at the *bottom* of a treatise's last page
  (treatise ends are mid-page; only starts are split).
- Fully letter-spaced *outline* labels can run together ("PARTI.", "OFTHEBONES.").

---

## Next steps

1. **Generalize the parser beyond EB.1** to the other editions (EB.4 2nd … EB.16 8th, ~160 vols).
   Edition-specific tuning likely needed (layout, running-head conventions, treatise sets).
2. **Ground headwords to Wikidata** (use the WikidataMCP vector search; the `headword-disambig` skill).
3. Optionally address the OCR-level limitations above if downstream use requires it.

## Repo / git

Tracked: `README.md`, `.gitignore`, `html/` (163 files + `index.csv`), `scripts/` (build_manifest,
make_chunks, run_batch.slurm, chandra_volume, build_html, flatten_html). **Untracked:**
`scripts/parse_articles.py` and this `STATUS.md` (not yet committed). `output/` is gitignored
(large; lives on Nibi, synced via rsync).
