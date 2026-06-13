#!/usr/bin/env python3
"""Segment Encyclopaedia Britannica volumes into article/treatise records.

Reads each volume's pages.jsonl (Chandra OCR structured-layout HTML in the
`raw` field) and metadata.json, then emits articles.jsonl: one record per
dictionary headword, with long treatises (ANATOMY, ASTRONOMY, ...) captured as
single records with a section outline.

Headword signals (EB.1 pilot — see the project plan):
  * PRIMARY  - bold at paragraph start: <p><b>ABACUS</b>, ...  (~99.5% precise)
               incl. drop-cap initials: <p><b>A</b>NATOMY ...  -> "ANATOMY"
  * SECONDARY- all-caps-plain at paragraph start + comma:
               <p>ANATHEMA, in heathen antiquity ...           (recall fallback)
  Cross-references ("... See ANATOMY.") are rejected by the paragraph-start rule.

Treatises are detected as gaps in the page-header trigram sequence whose
dominant running head is a word (the OCR letter-spacing of the title, e.g.
"A N A T O M Y." / "ANATOM Y.", is normalised away for matching).

Usage:
    python3 scripts/parse_articles.py [--output-dir output] [--only EB.1] [--report]
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import html as LH
from lxml import etree

COL_SPLIT = 500          # bbox x1 < 500 => left column, else right column
MIN_TREATISE_PAGES = 2   # a trigram-gap run this long with a word running head
NONWORD_HEAD = ("PLATE", "FIG", "PART", "CHAP", "SECT")   # not treatise titles

# ----------------------------------------------------------------------------
# edition profiles — the few things that differ between editions. The core
# segmentation (headwords, treatise gaps, sub-entries, cross-refs, postprocess)
# is shared; a profile only toggles edition-specific handling. Unknown editions
# fall back to DEFAULT_PROFILE (1st-edition behaviour).
# ----------------------------------------------------------------------------
DEFAULT_PROFILE = {
    "margin_notes": False,   # drop outer-margin side-glosses / footnotes from bodies
    "multivol": False,       # treatises may span volume boundaries (start mid-treatise)
}
EDITION_PROFILES = {
    "EB.1": {"margin_notes": False, "multivol": False},   # 1771, 3 vols, A-B/C-L/M-Z
    "EB.4": {"margin_notes": True,  "multivol": True},     # 1778-83, 10 vols, marginal glosses
}


def profile_for(meta):
    return EDITION_PROFILES.get(meta.get("eb_code"), DEFAULT_PROFILE)


def drop_margin_notes(blocks):
    """Remove the 2nd-edition marginal side-glosses and margin footnotes
    ("Abaci, various.", "* See Adansonia.") that would otherwise leak into the
    body. They are narrow Text blocks pinned to a page's OUTER margin; body
    columns are ~400px wide, so a <110px block at the far left/right is a note.
    Mid-column narrow blocks (drop-cap initials) are deliberately kept."""
    if not blocks:
        return blocks
    page_x2 = max((b.bbox[2] for b in blocks if b.bbox), default=0)
    out = []
    for b in blocks:
        if (b.label == "Text" and b.bbox and (b.bbox[2] - b.bbox[0]) < 110
                and (b.bbox[0] < 100 or b.bbox[2] > page_x2 - 60)):
            continue
        out.append(b)
    return out

# uppercase class includes Latin-1 caps + ligatures (ÆDES, ÆGIS, ŒCONOMY, ÇA ...)
_UC = "A-ZÀ-ÖØ-ÞŒ"
CAPS_WORD = re.compile(rf"[{_UC}][{_UC}&]+(?:-[{_UC}]+)*")   # all-caps run, >=2 letters
LEADING_CAPS = re.compile(rf"^[{_UC}]+")
DROPCAP = re.compile(rf"^[{_UC}]$")
ALLCAPS_HEAD = re.compile(
    rf"^\s*([{_UC}][{_UC}&]{{2,}}(?:[ -][{_UC}][A-Za-zÀ-ÿ&]*)*)\s*[,.]\s+\S")
# structural markers (PLATE IV, FIG. 3, CHAP. II, PART I, CASE 1, PROP. V) — only
# a marker when FOLLOWED BY a number/roman. Bare "CASE, among grammarians" or
# "BOOK, in commerce" etc. are real dictionary headwords and must NOT be rejected.
STRUCTURAL = re.compile(
    r"^(?:PLATE|CHAP|CHAPTER|SECT|SECTION|PART|FIG|FIGURE|TAB|TABLE|VOL|BOOK|"
    r"PROP|PROBLEM|THEOREM|LEMMA|COROLL|SCHOL|CASE|EXAMPLE|DEF|AXIOM|NUMB|No)"
    r"\.?\s*(?:[IVXLC]+\b|\d)", re.I)
ROMAN = re.compile(r"^[IVXLCDM]+\.?$")
CROSSREF = re.compile(r"\bSee\s+([A-Z][A-Z&-]{1,}(?:\s+[A-Z][A-Z&-]+)*)")

# printer's catchword: a trailing ALL-CAPS hyphen fragment ("… Hasselquist. ACRI-")
# repeating the first syllable of the next page — OCR keeps it; strip from body tails.
CATCHWORD = re.compile(rf"\s+[{_UC}][{_UC}&]+[­-]\s*$")
# end-of-volume errata block ("Page 127. column 2. … read Plate XI. …") that bled into
# the last dictionary entry; a dense run of these markers flags it for splitting out.
ERRATA_HIT = re.compile(r"Page\s+\d+\.\s*(?:column|col\.?|line)", re.I)
SIG_TAIL = re.compile(r"\s+\d?\s*[A-Z]\s*$")   # printer signature ("8 O") before errata

# Buried sub-entry recall: a paragraph opening with an all-caps lemma + 1-2 LOWERCASE
# modifier words + comma — "ABSINTHIATED medicines, ...", "ACCENSI ferenses, ...",
# "CANINE teeth, ...". The plain ALLCAPS_HEAD misses these (it needs the comma right
# after the caps run). Gated downstream by trigram alignment + the stoplists below to
# reject prose that merely starts with a caps word ("THIS fever,", "HOFFMAN says,").
# separator before the modifier is a space OR a hyphen, to also catch the Latin
# binomial sub-entries "AGARICO-fungus, …", "AJURU-catinga, …", "ARRIERE-ban, …".
ALLCAPS_MOD = re.compile(
    rf"^\s*([{_UC}][{_UC}&]{{2,}})((?:[\s-]+[a-zà-ÿ][A-Za-zÀ-ÿ&-]*){{1,2}})\s*,\s+\S")
# caps words that are function words / pronouns, never dictionary lemmas
FUNC_CAPS = {"THIS", "THAT", "THESE", "THOSE", "THE", "THEY", "THEIR", "THERE",
             "THEN", "THUS", "THAN", "WHEN", "WHICH", "WHERE", "WHILE", "WHO",
             "WHOM", "WHOSE", "WHAT", "BUT", "AND", "FOR", "NOR", "YET", "ALL",
             "SUCH", "SOME", "ITS", "HIS", "HER", "OUR", "YOUR", "NOT",
             "NO", "AS", "IF", "SO", "BY", "ON", "AT", "TO", "OF", "IN", "OR"}
# first lowercase modifier words that signal a sense-continuation, not a new lemma
CONT_WORDS = {"is", "are", "was", "were", "be", "been", "being", "has", "had",
              "have", "will", "would", "may", "might", "must", "can", "could",
              "shall", "should", "does", "did", "also", "likewise", "denotes",
              "signifies", "means", "says", "said", "properly", "sometimes",
              "therefore", "however", "thus", "then", "moreover"}

# inverted compound sub-entry: a normal-case qualifier + an ALL-CAPS lemma (printed
# in small caps) + comma — "Sea-GAGE,", "Block-CARRIAGE,", "Royal PREROGATIVE,".
# The lemma is the filing word (aligns with the page trigram); the qualifier leads.
# Distinct from ALLCAPS_HEAD (lemma first) and ALLCAPS_MOD (lemma + lowercase tail).
INVERTED_COMPOUND = re.compile(
    rf"^\s*([A-Z][a-zà-ÿ]+[ -]([{_UC}][{_UC}&]{{2,}}))\s*,\s+\S")
# leading qualifier words that signal prose / a treatise section header / a person
# reference rather than a real compound headword ("Of RUPTURES,", "Dr HALES,")
INV_STOP_QUAL = {"Of", "On", "See", "The", "For", "After", "Before", "When",
                 "While", "Whence", "If", "As", "Thus", "Hence", "In", "To", "By",
                 "With", "From", "This", "That", "These", "Those", "But", "And",
                 "Mr", "Mrs", "Dr", "Sir", "Mons", "Signor", "Saint"}


# ----------------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------------
def text_of(el) -> str:
    return "".join(el.itertext())


def outer_html(el) -> str:
    return etree.tostring(el, encoding="unicode", method="html").strip()


def norm_caps(s: str) -> str:
    """Aggressive match key: keep letters only, uppercase. 'ANATOM Y.' -> 'ANATOMY'."""
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def trigram_lcp(word: str, tg_upper: str) -> int:
    """Length of the common prefix between a word's letters and a page trigram."""
    if not tg_upper:
        return 0
    w, n = norm_caps(word), 0
    while n < len(tg_upper) and n < len(w) and w[n] == tg_upper[n]:
        n += 1
    return n


# Fully letter-spaced multi-word treatise titles lose their word boundaries in
# OCR ("C O N I C S E C T I O N S."); EB.1 has a small fixed set, so map them.
TREATISE_DISPLAY = {
    "CONICSECTIONS": "CONIC SECTIONS",
    "MORALPHILOSOPHY": "MORAL PHILOSOPHY",
    "NATURALHISTORY": "NATURAL HISTORY",
    "RELIGIONORTHEOLOGY": "RELIGION, OR THEOLOGY",
    "WATCHANDCLOCKWORK": "WATCH and CLOCK-WORK",
    "SHORTHANDWRITING": "SHORT-HAND WRITING",
    # EB.4 (2nd ed.) multi-word dissertation titles
    "COMPARATIVEANATOMY": "COMPARATIVE ANATOMY",
    "EXPERIMENTALPHILOSOPHY": "EXPERIMENTAL PHILOSOPHY",
    "MATERIAMEDICA": "MATERIA MEDICA",
    "LAWOFSCOTLAND": "LAW OF SCOTLAND",
    "PETITEGUERRE": "PETITE GUERRE",
    "LISTOFAUTHORS": "LIST OF AUTHORS",
    "CRAYONPAINTING": "CRAYON-PAINTING",
    "SHIPBUILDING": "SHIP-BUILDING",
}


def clean_title(text: str) -> str:
    """Recover a display title from OCR letter-spaced caps, keeping hyphens.
    'BOOK - KEEPIN G.' -> 'BOOK-KEEPING'; 'AGRICULTUR E.' -> 'AGRICULTURE'."""
    return re.sub(r"\s+", "", text or "").strip(" .,;:").strip()


def unspace_caps(s: str) -> str:
    """Collapse single-letter spaced runs into words for display/outline.
    'A N A T O M Y.' -> 'ANATOMY.'; 'SECT. I. Of the BONES.' unchanged-ish."""
    s = (s or "").strip()
    if not s:
        return s
    out, buf = [], []
    for tok in s.split(" "):
        if tok == "":
            continue
        m = re.fullmatch(r"([A-Za-z])([.,;:]?)", tok)   # single letter, maybe trailing punct
        if m:
            buf.append(m.group(1))
            if m.group(2):                              # punctuation closes the spaced run
                out.append("".join(buf) + m.group(2)); buf = []
        else:
            if buf:
                out.append("".join(buf)); buf = []
            out.append(tok)
    if buf:
        out.append("".join(buf))
    return " ".join(out)


def clean_text(chunks) -> str:
    if isinstance(chunks, str):
        chunks = [chunks]
    parts = []
    for c in chunks:
        c = re.sub(r"\s+", " ", (c or "")).strip()
        if c:
            parts.append(c)
    text = " ".join(parts)
    text = re.sub(r"(\w)[­-]\s+([a-z])", r"\1\2", text)   # de-hyphenate line breaks
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    return text.strip()


def extract_cross_refs(text: str):
    refs = []
    for m in CROSSREF.finditer(text):
        ref = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        if ref and ref not in refs:
            refs.append(ref)
    return refs


_SEE = re.compile(r"\bSee\b")
_DOMAIN = re.compile(
    r"^(?:a\s+(?:term|word|name)\s+(?:used\s+)?(?:in|of|among|amongst)"
    r"|in|among|amongst|of|used\s+(?:in|among|amongst))\s+[^,.]+", re.I)


def is_cross_reference(headword: str, body_text: str) -> bool:
    """True for a bare redirect ('HARE, in zoology. See LEPUS.') whose only content
    is the See-pointer plus an optional domain tag. Entries with a real definition
    before the pointer ('ABDOMEN, the lower belly. See ANATOMY.') are NOT redirects:
    after dropping the headword and one leading domain clause, the residual must be
    empty for the entry to count as a cross-reference."""
    b = (body_text or "").strip()
    m = _SEE.search(b)
    if not m:
        return False
    pre = b[:m.start()]
    hw = (headword or "").strip()
    if hw and pre[:len(hw)].upper() == hw.upper():     # strip the leading headword
        pre = pre[len(hw):]
    pre = pre.strip(" ,.;:")
    pre = _DOMAIN.sub("", pre, count=1).strip(" ,.;:")  # strip one domain clause
    return pre == ""


# ----------------------------------------------------------------------------
# block parsing
# ----------------------------------------------------------------------------
class Block:
    __slots__ = ("label", "bbox", "el", "column")

    def __init__(self, label, bbox, el):
        self.label = label
        self.bbox = bbox
        self.el = el
        self.column = 0 if (bbox and bbox[0] < COL_SPLIT) else 1


def parse_bbox(s):
    try:
        x1, y1, x2, y2 = (int(v) for v in s.split())
        return (x1, y1, x2, y2)
    except Exception:
        return None


def parse_blocks(raw: str):
    if not raw:
        return []
    frag = LH.fragment_fromstring(raw, create_parent="div")
    blocks = []
    for d in frag.iter("div"):
        lbl = d.get("data-label")
        if not lbl:
            continue
        blocks.append(Block(lbl, parse_bbox(d.get("data-bbox", "")), d))
    return blocks


def order_blocks(blocks):
    # Chandra emits blocks in true reading order (it correctly threads an article's
    # continuation across columns, even on irregular layouts). A naive (column, y)
    # re-sort BREAKS that on multi-column pages — e.g. it appended a TABERNACLE
    # continuation onto SYZYGY. So keep the model's native order.
    return blocks


class PageHead:
    __slots__ = ("page_no", "mode", "running", "trigram")

    def __init__(self, page_no, mode, running, trigram):
        self.page_no = page_no
        self.mode = mode            # dict | treatise | plate | unknown
        self.running = running      # alphabetic running-head token (raw, un-normalised)
        self.trigram = trigram      # 3-letter trigram when mode == dict


def parse_page_header(blocks):
    page_no, alphas = None, []
    n_text = sum(1 for b in blocks if b.label == "Text")
    n_img = sum(1 for b in blocks if b.label in ("Image", "Figure", "Diagram"))
    for b in blocks:
        if b.label != "Page-Header":
            continue
        t = text_of(b.el).strip()
        if not t:
            continue
        if re.fullmatch(r"[\[(]?\s*\d{1,4}\s*[\])]?\.?", t):   # ( 5 ) EB.1 · [ 101 ] EB.4
            page_no = int(re.search(r"\d+", t).group())
        elif re.search(r"[A-Za-z]", t):
            alphas.append(unspace_caps(t))
    trigram = next((a for a in alphas if re.fullmatch(r"[A-Z]{3}", a)), None)
    plate_like = any(re.match(r"PLATE", a, re.I) for a in alphas)
    word = next((a for a in alphas if len(norm_caps(a)) >= 4), None)
    if trigram:
        mode = "dict"
    elif plate_like or (n_img and n_text <= 1):
        mode = "plate"
    elif word:
        mode = "treatise"
    else:
        mode = "unknown"
    running = trigram or word or (alphas[0] if alphas else "")
    return PageHead(page_no, mode, running, trigram)


# ----------------------------------------------------------------------------
# headword detection
# ----------------------------------------------------------------------------
class Headword:
    __slots__ = ("full", "base", "qualifier", "type", "detected_by")

    def __init__(self, full, base, qualifier, type_, detected_by):
        self.full, self.base, self.qualifier = full, base, qualifier
        self.type, self.detected_by = type_, detected_by


def _classify(full: str, detected_by: str, trigram=None):
    full = re.sub(r"\s+", " ", full).strip()
    display = full.rstrip(" .,:")
    if display.endswith("-") or display.endswith("­"):   # word-break fragment (TI-, SUBMIS-)
        return None
    m = CAPS_WORD.search(display)
    if m:                                                  # normal: >=2-letter caps base
        base = m.group(0)
        qualifier = display[:m.start()].strip(" ,.")
        tail = display[m.end():]
        # Inverted headwords: EB alphabetises "HIGH ADMIRAL" under ADMIRAL and
        # "MAGNETICAL AMPLITUDE" under AMPLITUDE, so the base (the grouping /
        # grounding key) is the caps word the entry is filed under, not necessarily
        # the first. The page running-head trigram is alphabetically aligned with
        # that filing word, so pick the caps word with the longest common prefix
        # with the trigram — but re-key onto a *later* word only when it strictly
        # beats the first word's match (>=2 chars). This leaves genuine first-word
        # entries (ABJURATION OF HERESY, trigram ABJ) untouched, while catching
        # near-miss running heads (ROYAL AID under AID even when the head reads AIN).
        if trigram and len(trigram) == 3:
            tg = trigram.upper()
            best, choice = trigram_lcp(base, tg), None
            for mm in CAPS_WORD.finditer(display):
                if mm.start() == m.start():
                    continue
                s = trigram_lcp(mm.group(0), tg)
                if s >= 2 and s > best:
                    best, choice = s, mm
            if choice is not None:
                base = choice.group(0)
                qualifier = display[:choice.start()].strip(" ,.")
                tail = display[choice.end():]
    elif re.fullmatch(rf"[{_UC}]", display):               # single-letter entry ("A")
        base, qualifier, tail = display, "", ""
    else:
        return None
    while True:                                            # absorb multi-lemma run
        mt = re.match(rf"^(?:\s*,\s*|\s+OR\s+|\s+or\s+|\s+and\s+|\s*&\s*)([{_UC}][{_UC}&-]+)\b", tail)
        if not mt:
            break
        tail = tail[mt.end():]
    modifier = tail.strip(" ,.")
    has_qualifier = bool(qualifier)
    has_modifier = bool(modifier) and not modifier.isupper()
    type_ = "sub_entry" if (has_qualifier or has_modifier) else "article"
    return Headword(display, base, qualifier or None, type_, detected_by)


def detect_headword(p, trigram=None):
    kids = list(p)
    lead = (p.text or "")
    if kids and kids[0].tag == "b" and not lead.strip():
        b = kids[0]
        bold = text_of(b).strip()
        btail = b.tail or ""
        if DROPCAP.match(bold) and btail[:1].isalpha() and btail[:1].isupper():
            ext = LEADING_CAPS.match(btail).group(0)
            full = bold + ext
            rest = btail[len(ext):]
            mlow = re.match(r"[a-z]+", rest)
            if mlow:
                full += mlow.group(0)
        else:
            full = bold
        ctx = full + (b.tail or "")
        if re.match(r"^\d", full) or STRUCTURAL.match(ctx) or ROMAN.match(full):
            return None
        return _classify(full, "bold", trigram)
    # all-caps-plain headword. Match the FULL paragraph text (not just p.text):
    # some entries wrap the first word in <i> or have empty p.text, e.g.
    # '<i>COIX</i>, or JOB'S TEARS, ...' or 'COITION. See GENERATION.' — these
    # would be missed (and absorbed into the previous article) if we only looked
    # at p.text. The bold branch above already handled the bold case.
    ptext = text_of(p)
    m = ALLCAPS_HEAD.match(ptext)
    if m:
        cand = m.group(1).strip()
        if STRUCTURAL.match(ptext) or ROMAN.match(cand) or len(cand) < 3:
            return None
        return _classify(cand, "allcaps", trigram)
    # buried sub-entry: caps lemma + lowercase modifier(s) + comma ("CANINE teeth, ...").
    # Only accept when the lemma is alphabetically aligned with the page (trigram LCP
    # >= 2) and is not a function word / sense-continuation — otherwise it is prose.
    m = ALLCAPS_MOD.match(ptext)
    if m and trigram:
        lemma, mods = m.group(1), m.group(2)
        first_mod = mods.lstrip(" -").split()[0].lower()
        # gate: same first letter as the page running head (a page spans a letter's
        # range, so the head's 2nd/3rd letter need not match the lemma), and not a
        # function word / sense-continuation (those, not the trigram, reject prose).
        if (len(lemma) >= 3 and lemma not in FUNC_CAPS and first_mod not in CONT_WORDS
                and not STRUCTURAL.match(ptext) and trigram_lcp(lemma, trigram.upper()) >= 1):
            return _classify(lemma + mods, "allcaps_mod", trigram)
    # inverted compound: "Sea-GAGE, ...", "Royal PREROGATIVE, ..." — qualifier then
    # the ALL-CAPS lemma. Gate on the lemma aligning with the page trigram (>=2) and
    # a qualifier that isn't a prose / section / person prefix.
    m = INVERTED_COMPOUND.match(ptext)
    if m and trigram:
        full, lemma = m.group(1), m.group(2)
        qual = re.split(r"[ -]", full, 1)[0]
        if (qual not in INV_STOP_QUAL and not STRUCTURAL.match(ptext)
                and trigram_lcp(lemma, trigram.upper()) >= 2):
            return _classify(full, "inverted", trigram)
    return None


_LINE_CAPS = re.compile(rf"^\s*[{_UC}][{_UC}&]+\b")


def split_runon(p):
    """If a <p> packs several entries on separate lines (each starting with an
    ALL-CAPS headword, e.g. a column of 'X. See Y.' cross-ref stubs), return the
    list of lines; else None. Avoids over-splitting normal wrapped prose."""
    lines = [l.strip() for l in text_of(p).split("\n") if l.strip()]
    if len(lines) < 2:
        return None
    matched = [l for l in lines if _LINE_CAPS.match(l)]
    if len(matched) >= 2 and len(matched) / len(lines) >= 0.6:
        return lines
    return None


def runon_headword(line, trigram=None):
    """Headword for a run-on line: the text before the first comma/period."""
    if not _LINE_CAPS.match(line):
        return None
    head = re.split(r"[,.]", line, 1)[0].strip()
    if STRUCTURAL.match(line) or ROMAN.match(head):
        return None
    return _classify(head, "runon", trigram)


# ----------------------------------------------------------------------------
# treatise detection (trigram-gap runs)
# ----------------------------------------------------------------------------
def h2_title_matching(blocks, title_norm):
    for b in blocks:
        if b.label != "Section-Header":
            continue
        for h in b.el.iter("h1", "h2", "h3"):
            if norm_caps(text_of(h)) == title_norm:
                return clean_title(text_of(h))
    return None


def is_title_block(b, title_norm):
    if b.label != "Section-Header":
        return False
    return any(norm_caps(text_of(h)) == title_norm for h in b.el.iter("h1", "h2", "h3"))


def allcaps_h2_title(blocks):
    """First h1/h2 that is a predominantly-uppercase title (e.g. the LAW treatise
    banner 'PRINCIPLES OF THE LAW OF SCOTLAND.'), for treatises whose running head
    is too short to be a word (LAW -> running head 'L')."""
    for b in blocks:
        if b.label != "Section-Header":
            continue
        for h in b.el.iter("h1", "h2"):
            t = unspace_caps(re.sub(r"\s+", " ", text_of(h)).strip(" .,;:"))
            letters = [c for c in t if c.isalpha()]
            if len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) >= 0.8:
                return t
    return None


def detect_treatise_spans(pages, body_start):
    """Return {start_idx: {"title","title_norm","end_idx"}}.

    A treatise = a maximal run of pages with no dictionary trigram whose dominant
    running head is a real word (>=5 letters, not PLATE/FIG/PART/CHAP). The title
    page is the <h2> matching that word, on the page before the run or its first
    page; the body runs to the page before the trigram sequence resumes.
    """
    spans, n, i = {}, len(pages), body_start
    while i < n:
        if pages[i]["head"].trigram:
            i += 1
            continue
        lo = i
        while i < n and not pages[i]["head"].trigram:
            i += 1
        hi = i - 1
        if hi - lo + 1 < MIN_TREATISE_PAGES:
            continue
        cnt = Counter()
        for p in pages[lo:hi + 1]:
            r = norm_caps(p["head"].running)
            if len(r) >= 5 and not r.startswith(NONWORD_HEAD):
                cnt[r] += 1
        start, display, title_norm = lo, None, None
        if cnt and cnt.most_common(1)[0][1] >= 2:
            # path 1: dominant >=5-letter word running head (ANATOMY, ALGEBRA, ...)
            title_norm = cnt.most_common(1)[0][0]
            for cand in (lo - 1, lo):
                if cand < 0:
                    continue
                d = h2_title_matching(pages[cand]["blocks"], title_norm)
                if d:
                    start, display = cand, d
                    break
            display = display or title_norm
        elif hi - lo + 1 >= 4:
            # path 2: running head too short to be a word (LAW -> 'L'); use the
            # all-caps banner h2 on the run's first page as the title.
            for cand in (lo, lo - 1):
                if cand < 0:
                    continue
                t = allcaps_h2_title(pages[cand]["blocks"])
                if t:
                    start, display, title_norm = cand, t, norm_caps(t)
                    break
        if title_norm is None:
            continue
        display = TREATISE_DISPLAY.get(title_norm, display)
        spans[start] = {"title": display, "title_norm": title_norm,
                        "end_idx": hi, "from_h2": True}

    # merge adjacent runs of the same treatise split by a stray plate/OCR page
    merged, prev = {}, None
    for start in sorted(spans):
        info = spans[start]
        if prev is not None:
            p = merged[prev]
            if info["title_norm"] == p["title_norm"] and start - p["end_idx"] <= 3:
                p["end_idx"] = info["end_idx"]
                if info["from_h2"] and not p["from_h2"]:
                    p["title"], p["from_h2"] = info["title"], True
                continue
        merged[start] = dict(info)
        prev = start
    return merged


def build_outline(span_pages):
    outline = []
    for pg in span_pages:
        for b in order_blocks(pg["blocks"]):
            if b.label != "Section-Header":
                continue
            for h in b.el.iter("h3", "h4", "h5", "h6"):
                label = unspace_caps(text_of(h)).strip()
                if not label:
                    continue
                outline.append({
                    "level": int(h.tag[1]),
                    "label": label,
                    "printed_page": pg["head"].page_no,
                    "image_page": pg["idx"],
                })
    return outline


# ----------------------------------------------------------------------------
# record accumulators
# ----------------------------------------------------------------------------
# blocks scanned for headwords (dictionary entries may be packed into List-Group
# / Complex-Block divs, not just Text); other body labels only append to the
# currently-open article.
HEADWORD_BLOCK_LABELS = {"Text", "List-Group", "Complex-Block"}
BODY_BLOCK_LABELS = {"Text", "Table", "Equation-Block", "List-Group",
                     "Caption", "Footnote", "Complex-Block"}


class Record:
    def __init__(self, hw, pg, block):
        self.hw = hw
        self.html_parts, self.text_parts = [], []
        self.page_start = self.page_end = pg["head"].page_no
        self.idx_start = self.idx_end = pg["idx"]
        self.images = [pg["image"]]
        self.headword_bbox = block.bbox if block else None
        self.headword_image = pg["image"]

    def add(self, html, text, pg):
        if html:
            self.html_parts.append(html)
        if text:
            self.text_parts.append(text)
        if pg["head"].page_no is not None:
            self.page_end = pg["head"].page_no
        self.idx_end = pg["idx"]
        if pg["image"] not in self.images:
            self.images.append(pg["image"])


class TreatiseAcc:
    def __init__(self, span, start_pg, end_idx):
        self.title = span["title"]
        self.html_parts, self.text_parts = [], []
        self.page_start = self.page_end = None
        self.idx_start, self.idx_end = start_pg["idx"], end_idx
        self.images, self.headword_bbox = [], None
        self.headword_image = start_pg["image"]

    def add_block(self, b, pg):
        if self.headword_bbox is None and b.label == "Section-Header":
            self.headword_bbox = b.bbox
        self.html_parts.append(outer_html(b.el))
        self.text_parts.append(text_of(b.el))
        if pg["head"].page_no is not None:
            if self.page_start is None:
                self.page_start = pg["head"].page_no
            self.page_end = pg["head"].page_no
        if pg["image"] not in self.images:
            self.images.append(pg["image"])


def finalize_record(cur: Record, meta):
    body_text = clean_text(cur.text_parts)
    return {
        "headword": cur.hw.full, "base_headword": cur.hw.base,
        "qualifier": cur.hw.qualifier, "type": cur.hw.type,
        "detected_by": cur.hw.detected_by,
        "is_cross_reference": is_cross_reference(cur.hw.full, body_text),
        "volume_num": meta.get("volume_num"), "eb_code": meta.get("eb_code"),
        "identifier": meta.get("identifier"), "alpha_range": meta.get("alpha_range"),
        "printed_page_start": cur.page_start, "printed_page_end": cur.page_end,
        "image_page_start": cur.idx_start, "image_page_end": cur.idx_end,
        "body_text": body_text, "body_html": "\n".join(cur.html_parts),
        "cross_refs": extract_cross_refs(body_text)[:50], "char_count": len(body_text),
        "provenance": {"image_files": cur.images,
                       "headword_bbox": list(cur.headword_bbox) if cur.headword_bbox else None,
                       "headword_image": cur.headword_image},
    }


def finalize_treatise(tre: TreatiseAcc, outline, meta):
    body_text = clean_text(tre.text_parts)
    return {
        "headword": tre.title, "base_headword": tre.title, "qualifier": None,
        "type": "treatise", "detected_by": "treatise", "is_cross_reference": False,
        "volume_num": meta.get("volume_num"), "eb_code": meta.get("eb_code"),
        "identifier": meta.get("identifier"), "alpha_range": meta.get("alpha_range"),
        "printed_page_start": tre.page_start, "printed_page_end": tre.page_end,
        "image_page_start": tre.idx_start, "image_page_end": tre.idx_end,
        "body_text": body_text, "body_html": "\n".join(tre.html_parts),
        "cross_refs": extract_cross_refs(body_text)[:50], "char_count": len(body_text),
        "outline": outline,
        "provenance": {"image_files": tre.images,
                       "headword_bbox": list(tre.headword_bbox) if tre.headword_bbox else None,
                       "headword_image": tre.headword_image},
    }


# ----------------------------------------------------------------------------
# volume processing
# ----------------------------------------------------------------------------
def find_body_start(pages, alpha0):
    for pg in pages:
        for b in order_blocks(pg["blocks"]):
            if b.label != "Text":
                continue
            for p in b.el.iter("p"):
                hw = detect_headword(p, pg["head"].trigram)
                if hw and hw.base[:1] == alpha0:
                    return pg["idx"]
    return pages[0]["idx"] if pages else 0


def process_volume(vol_dir: Path):
    meta = json.loads((vol_dir / "metadata.json").read_text())
    prof = profile_for(meta)
    pages = []
    with (vol_dir / "pages.jsonl").open() as fh:
        for idx, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            blocks = parse_blocks(rec.get("raw", "") or "")
            head = parse_page_header(blocks)            # header parsed before filtering
            if prof["margin_notes"]:
                blocks = drop_margin_notes(blocks)
            pages.append({"idx": idx, "image": rec.get("image", ""),
                          "blocks": blocks, "head": head})

    alpha0 = (meta.get("alpha_range") or "A")[0].upper()
    body_start = find_body_start(pages, alpha0)
    if prof["multivol"]:
        # multi-volume editions split treatises across volume boundaries: a volume
        # can OPEN in the middle of one (vol 2 = "Astronomy-BZO" starts mid-ASTRONOMY).
        # The alpha_range opener tells us: a treatise NAME ("Astronomy", "Medicines",
        # "Optics") means the volume opens mid-treatise; a letter range ("A-AST", "C")
        # means a normal dictionary start. Only then do we scan/process from page 0,
        # capturing the continuation — otherwise front matter (PREFACE) would be
        # mis-captured and find_body_start lands on a stray headword inside it.
        spans = detect_treatise_spans(pages, 0)
        opener = norm_caps((meta.get("alpha_range") or "").split("-")[0])
        lead = None
        if len(opener) >= 4:                       # a treatise title, not "A"/"AST"
            lead = next((s for s in sorted(spans)
                         if s < body_start and spans[s]["title_norm"][:5] == opener[:5]), None)
        loop_start = lead if lead is not None else body_start
    else:
        spans = detect_treatise_spans(pages, body_start)
        loop_start = body_start

    records, cur = [], None
    stats = {"articles": 0, "sub_entries": 0, "treatises": 0, "bold": 0, "allcaps": 0,
             "allcaps_mod": 0, "inverted": 0, "runon": 0, "pages_body": 0, "pages_plate": 0}

    def flush():
        nonlocal cur
        if cur is not None:
            records.append(finalize_record(cur, meta))
            cur = None

    def open_record(hw, pg, b, html, text):
        nonlocal cur
        flush()
        cur = Record(hw, pg, b)
        stats[hw.detected_by] += 1
        stats["articles" if hw.type == "article" else "sub_entries"] += 1
        cur.add(html, text, pg)

    def consume_text_block(b, pg):
        nonlocal cur
        for p in b.el.iter("p"):
            lines = split_runon(p)
            if lines:                                    # column of packed stub entries
                for line in lines:
                    hw = runon_headword(line, pg["head"].trigram)
                    if hw:
                        open_record(hw, pg, b, f"<p>{line}</p>", line)
                    elif cur is not None:
                        cur.add("", line, pg)
                continue
            hw = detect_headword(p, pg["head"].trigram)
            if hw:
                open_record(hw, pg, b, outer_html(p), text_of(p))
            elif cur is not None:
                cur.add(outer_html(p), text_of(p), pg)

    i, n = loop_start, len(pages)
    while i < n:
        pg = pages[i]
        head = pg["head"]

        if i in spans:                                   # treatise span begins here
            span = spans[i]
            end = span["end_idx"]
            tre = TreatiseAcc(span, pg, end)
            start_is_dict = head.trigram is not None
            reached = False
            for b in order_blocks(pg["blocks"]):
                if b.label in ("Page-Header", "Page-Footer"):
                    continue
                if not reached and is_title_block(b, span["title_norm"]):
                    flush()                              # close last dict article
                    reached = True
                    tre.add_block(b, pg)
                elif not reached and start_is_dict:
                    if b.label in HEADWORD_BLOCK_LABELS:
                        consume_text_block(b, pg)
                    elif cur is not None and b.label in BODY_BLOCK_LABELS:
                        cur.add(outer_html(b.el), text_of(b.el), pg)
                elif not reached and not start_is_dict:
                    # first run page, title not yet hit: hold until title or absorb all
                    tre.add_block(b, pg)
                else:
                    tre.add_block(b, pg)
            flush()
            for j in range(i + 1, end + 1):              # rest of span = treatise body
                for b in order_blocks(pages[j]["blocks"]):
                    if b.label in ("Page-Header", "Page-Footer"):
                        continue
                    tre.add_block(b, pages[j])
            outline = build_outline(pages[i:end + 1])
            records.append(finalize_treatise(tre, outline, meta))
            stats["treatises"] += 1
            i = end + 1
            continue

        if head.mode == "plate":
            # Full-page engraving: its Captions/labels are figure descriptions
            # ("LITHIDIA, Fig. 1. ... MANIS or Scaly Lizard A. Bell. Sc."), NOT
            # article content — skip them. cur stays open, so an article that
            # genuinely continues past the plate resumes on the next text page.
            stats["pages_plate"] += 1
            i += 1
            continue

        stats["pages_body"] += 1
        for b in order_blocks(pg["blocks"]):
            if b.label in HEADWORD_BLOCK_LABELS:
                consume_text_block(b, pg)
            elif cur is not None and b.label in BODY_BLOCK_LABELS:
                cur.add(outer_html(b.el), text_of(b.el), pg)
        i += 1
    flush()
    records = postprocess(records)
    stats["articles"] = sum(1 for r in records if r["type"] == "article")
    stats["sub_entries"] = sum(1 for r in records if r["type"] == "sub_entry")
    stats["treatises"] = sum(1 for r in records if r["type"] == "treatise")
    return records, stats, meta


def postprocess(records):
    """OCR-level cleanups applied after segmentation:
      0. collapse runs of consecutive identical records (OCR repetition loops);
      1. strip trailing printer catchwords ("… Hasselquist. ACRI-");
      2. split an end-of-volume errata block out of the entry it bled into (BZO);
      3. drop an empty-body headword stub when the next record repeats the lemma
         (a headword printed at a column bottom, its text continuing overleaf).
    """
    # (0) repetition-loop dedup: the Chandra VLM occasionally gets stuck and emits the
    # same paragraph many times on one page (vol 5 produced GAMBOGE x72). Identical
    # consecutive (headword, body) records are never legitimate dictionary entries.
    deduped = []
    for r in records:
        if (deduped and r["headword"] == deduped[-1]["headword"]
                and r["body_text"] == deduped[-1]["body_text"]):
            continue
        deduped.append(r)
    records = deduped

    stage = []
    for r in records:
        bt = CATCHWORD.sub("", r["body_text"]).rstrip()        # (1) catchword
        if bt != r["body_text"]:
            r["body_text"], r["char_count"] = bt, len(bt)
        hits = list(ERRATA_HIT.finditer(r["body_text"]))       # (2) errata split
        if len(hits) >= 3 and hits[0].start() > 30:
            cut = hits[0].start()
            head = SIG_TAIL.sub("", r["body_text"][:cut]).rstrip()
            err = r["body_text"][cut:].strip()
            r["body_text"], r["char_count"] = head, len(head)
            stage.append(r)
            erec = dict(r)
            erec.update(headword="ERRATA", base_headword="ERRATA", qualifier=None,
                        type="errata", detected_by="errata", is_cross_reference=False,
                        body_text=err, body_html="<p>" + err + "</p>",
                        cross_refs=extract_cross_refs(err)[:50], char_count=len(err))
            erec.pop("outline", None)
            stage.append(erec)
        else:
            stage.append(r)

    out = []                                                   # (3) empty-body dedup
    for i, r in enumerate(stage):
        body = r["body_text"].strip().rstrip(".,")
        head = r["headword"].strip().rstrip(".,")
        nxt = stage[i + 1] if i + 1 < len(stage) else None
        if (body == head and nxt is not None and nxt["type"] not in ("treatise", "errata")
                and nxt.get("base_headword") == r.get("base_headword")):
            continue                                           # stub; content is in nxt
        out.append(r)
    return out


def write_jsonl(records, out_path: Path):
    with out_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from flatten_html import make_name        # reuse the HTML filename convention

    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="output")
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--only", default="EB.1")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    root = Path(args.output_dir)
    metas = sorted(root.glob(f"{args.only}/*/metadata.json"))
    if not metas:
        sys.exit(f"no volumes under {root}/{args.only}/*/metadata.json")

    art_dir = Path(args.article_dir)
    art_dir.mkdir(parents=True, exist_ok=True)

    grand = {}
    for meta_p in metas:
        records, stats, meta = process_volume(meta_p.parent)
        # same name as the volume's HTML, with a .jsonl extension
        out_p = art_dir / (make_name(meta)[:-len(".html")] + ".jsonl")
        write_jsonl(records, out_p)
        print(f"{meta.get('eb_code')} v{meta.get('volume_num')} "
              f"({meta.get('alpha_range')}): {len(records)} records -> {out_p}")
        if args.report:
            print(f"    articles={stats['articles']} sub_entries={stats['sub_entries']} "
                  f"treatises={stats['treatises']} | bold={stats['bold']} "
                  f"allcaps={stats['allcaps']} allcaps_mod={stats['allcaps_mod']} "
                  f"inverted={stats['inverted']} runon={stats['runon']} | "
                  f"body_pages={stats['pages_body']} plate_pages={stats['pages_plate']}")
        for k, v in stats.items():
            grand[k] = grand.get(k, 0) + v
    if args.report:
        print(f"\nTOTAL: {grand}")


if __name__ == "__main__":
    main()
