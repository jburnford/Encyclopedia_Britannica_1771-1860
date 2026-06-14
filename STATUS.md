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

## Stage 3 — Article parsing (EB.1 + EB.4 + EB.5 + EB.9 + EB.10 + EB.11 complete)

`scripts/parse_articles.py` segments the page-stream into one record per dictionary headword,
with long treatises as single records. Run: `python3 scripts/parse_articles.py --only EB.9 --report`.
Output: `article_data/<eb>_<edition>_v<NN>_<alpha>_<id>.jsonl`.

> **Edition-code ≠ edition-number.** The NLS `eb_code` is a shelfmark, not the edition ordinal:
> EB.1 = 1st (1771), EB.4 = 2nd (1778–83), EB.5 = 3rd (1797), EB.7 = Suppl. to 3rd (1801),
> **EB.9 = 4th (1810)**, EB.10 = 5th, EB.11 = 6th, EB.12 = Suppl. to 4/5/6, EB.15 = 7th, EB.16 = 8th.

**Edition profiles.** The core segmentation is shared across editions; an `EDITION_PROFILES` dict
toggles only the parts that differ (unknown editions fall back to 1st-edition behaviour):

| key | EB.1 | EB.4 | EB.5 | EB.9 | effect |
|-----|------|------|------|------|--------|
| `margin_notes` | off | on | on | on | drop outer-margin side-glosses / footnotes (2nd ed. on) from bodies |
| `multivol` | off | on | on | on | a volume may open mid-treatise (`Astronomy-BZO`, `Hydrostatics-LES`, `Agriculture-AME`); capture it |

(EB.10 5th ed. and EB.11 6th ed. reuse the same `margin_notes` + `multivol` profile; neither is part-split.)

Page-number parsing accepts both `( 5 )` (EB.1) and `[ 101 ]` (EB.4+) — edition-agnostic.
**Headword delimiter:** an all-caps headword is recognised when followed by a comma/period
(`ANATHEMA, in …`) **or a parenthetical etymology/identifier** (`BAROMETER (from Baros …)`,
`POPE (Alexander), …`). The paren form was added after the EB.9↔EB.10 cross-check showed
`BAROMETER` (and ~3,750 biography / ancient-geography / redirect entries across EB.4/5/9/10) being
silently absorbed into the previous article. `is_cross_reference` also strips a leading `(name)` so
`LOYOLA (Ignatius). See IGNATIUS.` is flagged as a redirect.
The `alpha_range` is stripped of EB.9's `"Part N, "` scan-split prefix before it drives body-start
and the lead-treatise opener (else `find_body_start` keys on letter "P" and skips the volume front).
**Treatise-section gate:** bare math labels (`RULE`, `EXAMP.`, `PROB. I`, `COR.`, `QUEST.`) inside
the long math articles are dropped unless aligned with the page running head (trigram LCP ≥ 2), so a
real entry (`CASE`, `RULE OF THREE`, `COR CAROLI`) survives but a treatise-internal label is absorbed
into the running article (124→27 in EB.9; also trimmed EB.1 −9, EB.4 −37, EB.5 −88).

### EB.1 (1771 first edition) — all 3 volumes

| Volume | Range | Records | articles | sub_entries | treatises | errata |
|--------|-------|--------:|---------:|------------:|----------:|-------:|
| 144133901 v1 | A–B | 5,598 | 4,869 | 716 | 12 | 1 |
| 144133902 v2 | C–L | 7,221 | 6,658 | 549 | 14 | 0 |
| 144133903 v3 | M–Z | 6,202 | 5,946 | 239 | 17 | 0 |
| **Total** | A–Z | **19,021** | **17,473** | **1,504** | **43** | **1** |

Detection signals: **bold** at paragraph start 16,146 · **all-caps-plain** 2,549 · **all-caps + lowercase
modifier** (buried sub-entries: `CANINE teeth`, `AGARICO-fungus`) 98 · **inverted compound** (`Sea-GAGE`,
`Block-CARRIAGE`) 23 · **run-on** (stub clusters split) 213 · **treatise** 43. Precision ~100% on
hand-checked random samples; treatise inventory matches the
canonical EB.1 set (ANATOMY 175pp, ASTRONOMY, CHEMISTRY, OPTICS, SURGERY, LAW = "Principles of the Law
of Scotland", …).

### EB.4 (1778–83 second edition) — all 10 volumes

| Volume | Range | Records | articles | sub_entries | treatises |
|--------|-------|--------:|---------:|------------:|----------:|
| 144850370 v1 | A–AST | 3,092 | 2,886 | 199 | 7 |
| 144850373 v2 | Astronomy–BZO | 2,826 | 2,512 | 309 | 5 |
| 144850374 v3 | C | 3,416 | 2,895 | 514 | 7 |
| 144850375 v4 | D–F | 2,665 | 2,374 | 283 | 8 |
| 144850376 v5 | G–J | 2,307 | 2,061 | 238 | 8 |
| 144850377 v6 | K–Medicine | 1,452 | 1,287 | 158 | 7 |
| 144850378 v7 | Medicines–Optics | 1,278 | 1,182 | 86 | 10 |
| 144850379 v8 | Optics–Poetry | 1,118 | 1,032 | 77 | 9 |
| 190273289 v9 | POI–SCU | 1,761 | 1,585 | 175 | 1 |
| 190273290 v10 | SCU–Appendix | 3,151 | 2,810 | 332 | 9 |
| **Total** | A–Z | **23,066** | **20,624** | **2,371** | **71** |

99.3% of records carry a printed page; 3 empty-body. **Inverted compound** sub-entries (qualifier +
all-caps lemma — `Sea-GAGE`, `Royal PREROGATIVE`) add 117 here (140 across both editions, 0 false
positives on full audit). Treatise inventory matches the 2nd edition's
expanded dissertation set (ACOUSTICS, COMPARATIVE ANATOMY, ELECTRICITY, MATERIA MEDICA, METALLURGY,
MINERALOGY, ORNITHOLOGY, PNEUMATICS, …). EB.4 uses **continuous pagination across the whole 10-volume
set** (page numbers run to ~9000), not per-volume — so absolute page thresholds are meaningless.

The current parser **out-of-the-box** segmented EB.4 cleanly; the only real adaptations were the three
profile items above. Verified by sampling; the segmentation precision looks comparable to EB.1.

### EB.5 (1797 third edition) — all 18 volumes

**27,483 records** (25,366 articles · 2,024 sub-entries · 92 treatises · 1 errata), 0.6% missing a
printed page, 0 OCR-repetition duplicates. Reusing the EB.4 profile (`margin_notes` + `multivol`)
worked directly — margin pollution dropped 104 → 31 per volume, and mid-treatise opens
(`Hydrostatics-LES`, `Medals-Midwifery`) capture their continuation. The 3rd edition's treatises are
enormous (vol 11 `MEDICINE` alone is ~1.97M chars; `METAPHYSICS` 875K). Treatise inventory matches the
canonical set (ANATOMY, ASTRONOMY, CHEMISTRY, COMPARATIVE ANATOMY, ELECTRICITY, OPTICS, SURGERY, …).
A handful of treatise *labels* are off — plate sequences picked up a genus running head
(`CAPRA`, `MYRISTICA`), and end-of-volume inserts (`OMISSION`, an `ERRATA`) — but no dictionary
content is lost (surrounding entries verified present); these are cosmetic.

### EB.9 (1810 fourth edition) — all 20 volumes (40 scan-parts)

**29,769 records** (27,250 articles · 2,402 sub-entries · 117 treatises), mean **97.4 %** of images
covered per part (rest is plates / front-matter), 0 OCR-repetition duplicates. EB.9 is the same layout
family as EB.4/EB.5 — the only structural novelty is that each physical volume is scanned as two parts
(`Part 1, AME-ANS` / `Part 2, Agriculture-AME`). Two adaptations were needed beyond reusing the profile:
(1) **strip the `"Part N, "` prefix** from `alpha_range` so body-start/opener key on the real letter —
without this a Part-1 volume keyed on "P", `find_body_start` jumped to a stray `PROBLEM` deep inside,
and the entire front of the volume (e.g. the 800K-char `ANATOMY` dissertation in vol 2) was silently
dropped; (2) the **treatise-section gate** (above), since the 4th edition prints far more worked-math
articles (`ANNUITIES`, `ALGEBRA`, `ARITHMETIC`) whose `RULE`/`EXAMP.`/`PROB.` labels were fragmenting
the articles. The 4th-edition dissertation set is captured in full: `CHEMISTRY` (2.10M chars),
`BOTANY`, `MEDICINE`, `ASTRONOMY`, `ELECTRICITY`, `ANATOMY`, `OPTICS`, `GEOLOGY`, `PHYSIOLOGY`,
`MINERALOGY`, `SURGERY`, `MATERIA MEDICA`, `LAW OF ENGLAND`, … A few small (<4K-char) treatises are
mis-titled where a plate list inherited a running head (`BRIDGE`, `CLOCK`, `TELESCOPE`); no content lost.
The massive `AMERICA` article (~100 pp, filed under "AME") stays one *article* rather than a treatise
because its running head never breaks alphabetical filing — captured whole, the label is cosmetic.

### EB.10 (1815 fifth edition) — all 20 volumes

**30,823 records** (26,980 articles · 3,553 sub-entries · 110 treatises before the paren fix; the fix
lifted it), mean **97.8 %** image coverage, 0 truncation. Same layout family as EB.4/5/9 but **not
part-split** — reused the profile unchanged. Used as a **cross-edition validator** against EB.9 (the
5th ed. is largely a re-set of the 4th): **93 % of base headwords are shared** between EB.9 and EB.10,
and the non-shared 7 % is dominated by OCR spelling variants of the *same* article, not parser
disagreement. Content spot-checks are byte-identical or near (`CALCINATION` 368 ch both, `ABDOMEN`
131 both, `ECLIPSE` 182 both, `GRAVITY` 1581/1604).

The cross-check surfaced the paren-headword bug (above). Every large article that first looked
"missing in EB.9" turned out to be **present but OCR-mangled in the headword**, correctly segmented:
`CONSTANTINOPLE`→`CONSTANTINOPE` (152K ch), `OTAHEITE`→`OTAHITE` (96K), `PERSIA` welded under
`PERSEUS` (142K), `INSTINCT` under `INSTEP` (67K). These are OCR-quality issues (a dropped letter or a
heading the VLM didn't set off), not segmentation errors — flagged as a known limitation, fixable only
by re-OCR or a fuzzy headword-normalisation pass before grounding.

### EB.11 (1823 sixth edition) — all 20 volumes

**30,397 records** (27,393 articles · 2,863 sub-entries · 141 treatises), mean **97.3 %** coverage,
0 truncation. Same family as EB.10; profile reused unchanged.

### OCR headword repair (cross-edition reconciliation)

The six editions are largely re-set reprints, so the same headword recurs across them. That
redundancy is used to detect and correct OCR-garbled headwords. Three-stage pipeline:

1. **`scripts/headword_reconcile.py`** — deterministic detector. A headword spelling in only ONE
   edition ("CONSTANTINOPE") is suspect when a near spelling is confirmed in others at the same
   alphabetical slot. Four precision filters: alphabetical adjacency, shared prefix, edit-distance ≤2,
   and the **co-occurrence test** (if the singleton's own edition also has the candidate spelling they
   are distinct real words — an edition won't hold EASTER and a mangled EASTER). 7,426 singletons →
   **2,961 candidates** with ranked suggestions + body snippet → `headword_candidates.jsonl`.
2. **`scripts/adjudicate_workflow.js`** — LLM fan-out (Workflow): candidates batched, agents return
   structured `correct`/`keep` + canonical. Editions can't decide the final call alone (the corpus is
   full of distinct Latin/genus/place names 1–2 edits apart: CALAMITES≠CALAMINE); the LLM is the
   tie-breaker, with the editions framing each decision. Run on **Sonnet** (Haiku was inconsistent
   batch-to-batch). → `headword_decisions.jsonl` (948 correct, 2,013 keep).
3. **`scripts/apply_headword_fixes.py`** — overwrites `headword`/`base_headword` with the canonical;
   stashes the OCR originals in `provenance.raw_headword`/`raw_base_headword` and records
   `provenance.headword_correction`. Body text is left untouched (faithful OCR).

**Result: 981 records corrected** (e.g. `ALSFIELD→ALSFELD`, `SCHILD→SCHELD`, `AMALFA→AMALFI`,
`VERTUMINUS→VERTUMNUS`). EB.9↔EB.10 base-headword overlap rose 22,524 → 22,768. Record counts
unchanged (headword-only edit). Re-runnable end-to-end as the corpus grows.

Not yet addressed: the "absorbed article" class (PERSIA welded under PERSEUS) — a headword missing
with no singleton variant; needs body-splitting, a separate harder track (~200–400 cases).

### Record schema
### Record schema

`headword, base_headword, qualifier, type` (`article|sub_entry|treatise`), `detected_by`,
`is_cross_reference` (bare "See X" redirect — 2,346 across EB.1; body is only the pointer + an
optional domain tag, so a substantive-article count = non-treatise records with this false ≈ 16,562),
`volume_num, eb_code, identifier, alpha_range, printed_page_start/end` (from the "( N )" running
head), `image_page_start/end` (jsonl index), `body_text, body_html, cross_refs[], char_count,
provenance{image_files, headword_bbox, headword_image}`. Treatises add a nested `outline[]`
(PART/CHAP/SECT). Variants group by `(volume_num, base_headword)`.

### How it works (key decisions)

- **Headwords**: bold at paragraph start (drop-cap initials extended, e.g. `<b>A</b>NATOMY`→ANATOMY);
  all-caps-plain + comma as a recall fallback, matched on the *full* paragraph text so italic-wrapped
  / empty-`p.text` headwords are caught; run-on `<p>`s of stub entries split per line.
- **`base_headword` (grouping/grounding key)**: defaults to the first caps word, but inverted
  headwords (EB files "HIGH ADMIRAL" under ADMIRAL, "MAGNETICAL AMPLITUDE" under AMPLITUDE) are
  re-keyed onto the caps word with the longest common prefix with the page running-head trigram
  (its alphabetical filing position), with the leading words demoted to `qualifier`. Fires only when
  a *later* word strictly beats the first, so genuine first-word entries (ABJURATION OF HERESY,
  trigram ABJ) are untouched. Halved the first-letter ordering anomalies; ~60 records moved
  article→sub_entry.
- **Treatises** = gaps in the page-header trigram sequence (robust to OCR letter-spacing and
  recto/verso "Part II." alternation), with an h2-banner fallback for short running heads (LAW → "L").
- **Reading order** = Chandra's native block order (a `(column,y)` re-sort was found to scramble
  multi-column pages — removed).
- **Cross-references** ("See X") excluded structurally; structural markers ("PLATE IV", "FIG. 3")
  rejected only when followed by a number/roman.

### Review interface

`scripts/build_review_html.py` emits a self-contained HTML viewer per volume under `review_html/`
(data embedded, opens from `file://`; records in page/reading order). Filters by type / detection
signal / cross-ref, free-text search, and a **"problems only"** toggle surfacing heuristic error
candidates (empty body, fragment, page-number anomaly, possible bleed — 43 flagged across EB.1).

### Validation

Audited via a random-sampling loop (50 articles/iteration + a global bleed scan), fixing the parser
and re-parsing until samples came back clean. Four systematic bugs found and fixed: cross-column
bleed (reading order), italic-first/empty-`p.text` headwords, `NON_HEADWORD` over-rejection
(CASE/BOOK/TABLE/FIGURE/INDEX), and plate-caption bleed. Net recovered ~490 records vs. the first
pass and eliminated the large bleed cases.

**Second audit round** (external review, two LLM passes). Fixes applied: (a) `base_headword` re-keyed
for inverted headwords via running-head trigram; (b) `is_cross_reference` flag for bare redirects;
(c) **buried sub-entry recall** — a paragraph opening `CAPS + lowercase/hyphen modifier + comma`
(`ABSINTHIATED medicines`, `AGARICO-fungus`) is now split out, gated by same-first-letter trigram
alignment + function-word/continuation stoplists (98 recovered, 0 prose false-positives on full audit);
(d) trailing printer **catchwords** stripped (`… Hasselquist. ACRI-`, ~30); (e) end-of-volume **errata**
block split out of the entry it bled into (BZO); (f) **empty-body dedup** — a column-bottom headword
stub is dropped when the next record repeats the lemma (57 → 5). Several reported "merges" were
verified *correct* in the data (ACORUM/ACORUS, ACROTERIA/ACRITHYMIA distinct) or hallucinated.

**Third round** (EB.4-driven): **inverted compound** sub-entries — a paragraph opening with a
normal-case qualifier + an ALL-CAPS lemma + comma (`Sea-GAGE,`, `Block-CARRIAGE,`, `Royal PREROGATIVE,`)
— are now split out (the lemma is printed in small caps, so the all-caps detectors missed them). Gated
by trigram alignment of the lemma + a qualifier stoplist (prose / section / person prefixes). 140
recovered across both editions, 0 false-positives on full audit; e.g. `GAGE` now yields `Sliding-GAGE`,
`Sea-GAGE`, `Wind-GAGE` as distinct sub-entries instead of one 11k-char blob.

### Known limitations (OCR-level, acceptable for the pilot)

- 5 records with `body == headword` — standalone `<p><b>X</b></p>` whose definition attached elsewhere.
- Two entries merged when OCR joins them in **one `<p>`** with no separator (e.g. "c. 2.CALLUS",
  `ADENOSE`/`ALVI fluxus`) — not splittable at the paragraph level.
- Buried sub-entries with a **3+ word** Latin modifier before the comma (`ARRESTO facto super bonis`)
  stay merged: the recall rule caps the modifier at 2 words to keep prose precision at 100%.
- Source **OCR transcription** errors are preserved verbatim (`anno 1491` for 1492, `wife`/`wise`,
  doubled words) — these are not parser errors and would need a separate OCR-correction pass.
- Fully letter-spaced *outline* labels can run together ("PARTI.", "OFTHEBONES.").
- **OCR repetition loops**: the Chandra VLM occasionally gets stuck and emits one paragraph many
  times on a page (vol 5 page produced `GAMBOGE` ×72). A postprocess pass collapses consecutive
  identical records (only EB.4 vol 5 was affected — 70 removed). The leftover `GAMBOGE`→`GAME` weld
  is hard-coded apart in `repair_gamboge_game()` (clean `GAMBOGE` + recovered `GAME` article); the
  proper fix is re-OCR of that page, after which the hard-coded patch becomes a no-op.
- **EB.4**: 1 of 71 treatises mis-titled (`OFFLOWERS` — a path-2 banner grabbed a section header
  instead of the dissertation title; content is preserved, only the title is wrong). Cross-volume
  treatises (ASTRONOMY, OPTICS) are captured as one record per volume, not yet stitched into a single
  record across the volume boundary. A few inline `*` footnote markers / OCR-merged margin footnotes
  remain in bodies (same class as the one-`<p>` merges).

---

## Next steps

1. **Continue to the remaining editions** (EB.7 Suppl., EB.11 6th, EB.12 Suppl., EB.15 7th,
   EB.16 8th). EB.1 + EB.4 + EB.5 + EB.9 + EB.10 done; the `EDITION_PROFILES` mechanism is in
   place, so each new edition should need only a profile entry plus spot-checking (layout,
   running-head conventions, treatise sets, and — for part-split scans — the `"Part N, "` prefix).
2. **Ground headwords to Wikidata** (use the WikidataMCP vector search; the `headword-disambig` skill).
3. Optionally: stitch cross-volume treatises into single records; address the OCR-level limitations.

## Repo / git

Tracked: `README.md`, `.gitignore`, `html/` (163 files + `index.csv`), `scripts/` (build_manifest,
make_chunks, run_batch.slurm, chandra_volume, build_html, flatten_html). **Untracked:**
`scripts/parse_articles.py` and this `STATUS.md` (not yet committed). `output/` is gitignored
(large; lives on Nibi, synced via rsync).
