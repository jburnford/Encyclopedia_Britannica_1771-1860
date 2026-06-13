#!/usr/bin/env python3
"""Build one self-contained HTML file per volume from Chandra 2 pages.jsonl.

Reads each volume's pages.jsonl (the `raw` field — Chandra's structured layout
HTML with data-label / data-bbox attributes) and metadata.json, then writes
<identifier>.html alongside them. Pages are emitted in jsonl order (== METS
page order). Images were not exported (include_images=False), so <img> tags
carry alt text but no src; we render that alt text as a visible placeholder
instead of a broken-image icon. Everything else (Text, Section-Header, Table,
Equation-Block MathML, etc.) is kept verbatim.

Usage:
    python3 scripts/build_html.py [--output-dir output] [--only EB.1]
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

IMG_RE = re.compile(r'<img\b[^>]*?\balt="(.*?)"[^>]*?/?>', re.S)
SRCLESS_IMG_RE = re.compile(r'<img\b(?![^>]*\bsrc=)[^>]*?/?>', re.S)

CSS = """\
:root { --ink:#1a1a1a; --dim:#777; --rule:#ddd; --accent:#7a5c2e; }
* { box-sizing: border-box; }
body {
  font-family: Georgia, 'Times New Roman', serif;
  color: var(--ink); line-height: 1.55;
  max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 6rem;
  background: #fafaf8;
}
header.vol-meta { border-bottom: 2px solid var(--accent); margin-bottom: 2rem; }
header.vol-meta h1 { font-size: 1.4rem; line-height: 1.3; margin: 0 0 .75rem; }
header.vol-meta dl {
  display: grid; grid-template-columns: max-content 1fr; gap: .15rem .75rem;
  font-size: .8rem; color: var(--dim); margin: 0 0 1rem;
}
header.vol-meta dt { font-weight: bold; }
header.vol-meta dd { margin: 0; }
section.page { border-top: 1px solid var(--rule); padding-top: 1.25rem; margin-top: 1.5rem; }
.page-num {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: .7rem; color: var(--dim); margin-bottom: .6rem; letter-spacing: .02em;
}
p { margin: .55rem 0; }
/* layout labels */
[data-label="Page-Header"], [data-label="Page-Footer"] {
  font-size: .78rem; color: var(--dim); font-style: italic;
}
[data-label="Section-Header"] { font-weight: bold; font-size: 1.1rem; margin: 1.4rem 0 .4rem; }
[data-label="Section-Header"] p { margin: 0; }
[data-label="Caption"] { font-style: italic; font-size: .85rem; color: #555; text-align: center; }
[data-label="Footnote"] { font-size: .8rem; color: #444; }
[data-label="Equation-Block"] { text-align: center; margin: .8rem 0; overflow-x: auto; }
[data-label="List-Group"] ul, [data-label="List-Group"] ol { margin: .4rem 0; }
table { border-collapse: collapse; margin: .6rem 0; font-size: .9rem; }
td, th { border: 1px solid var(--rule); padding: .2rem .5rem; text-align: left; }
.img-desc {
  display: block; border: 1px dashed #bbb; background: #f1efe9;
  color: #555; font-size: .82rem; font-style: italic;
  padding: .5rem .7rem; margin: .6rem 0; border-radius: 3px;
}
.img-desc::before { content: "\\1F5BC  image: "; font-style: normal; }
[data-label="Blank-Page"] { color: var(--dim); font-size: .78rem; font-style: italic; }
[data-label="Blank-Page"]:empty::after { content: "[blank page]"; }
"""


def render_imgs(raw: str) -> str:
    """Turn src-less <img alt="..."> into a visible description span."""
    def repl(m):
        return f'<span class="img-desc">{m.group(1).strip()}</span>'
    raw = IMG_RE.sub(repl, raw)
    # any remaining src-less img (no alt) -> generic placeholder
    raw = SRCLESS_IMG_RE.sub('<span class="img-desc">(unlabelled image)</span>', raw)
    return raw


def meta_dl(meta: dict) -> str:
    rows = [
        ("Edition", f'{meta.get("edition_label","?")} ({meta.get("edition_year","?")})'),
        ("Volume", meta.get("volume_num")),
        ("Alpha range", meta.get("alpha_range")),
        ("EB code", meta.get("eb_code")),
        ("Identifier", meta.get("identifier")),
        ("Pages", meta.get("n_pages")),
    ]
    cells = "".join(
        f"<dt>{html.escape(str(k))}</dt><dd>{html.escape(str(v))}</dd>"
        for k, v in rows if v not in (None, "")
    )
    return f"<dl>{cells}</dl>"


def build_volume(vol_dir: Path) -> Path | None:
    meta_p = vol_dir / "metadata.json"
    pages_p = vol_dir / "pages.jsonl"
    if not (meta_p.exists() and pages_p.exists()):
        return None
    meta = json.loads(meta_p.read_text())
    ident = meta.get("identifier", vol_dir.name)
    title = html.escape(meta.get("title", ident))

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        f"<style>\n{CSS}</style>",
        "</head>",
        "<body>",
        '<header class="vol-meta">',
        f"<h1>{title}</h1>",
        meta_dl(meta),
        "</header>",
        "<main>",
    ]

    n = 0
    with pages_p.open() as fh:
        for i, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            n += 1
            img = html.escape(str(rec.get("image", "")))
            body = render_imgs(rec.get("raw", "") or "")
            parts.append(
                f'<section class="page" id="p{i}" data-image="{img}">'
                f'<div class="page-num">page {i} &middot; {img}</div>'
                f"{body}</section>"
            )

    parts += ["</main>", "</body>", "</html>", ""]
    out_p = vol_dir / f"{ident}.html"
    out_p.write_text("\n".join(parts), encoding="utf-8")
    return out_p, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="output", help="root of output/<EB>/<id>/ tree")
    ap.add_argument("--only", default=None, help="limit to one edition dir, e.g. EB.1")
    args = ap.parse_args()

    root = Path(args.output_dir)
    if not root.is_dir():
        sys.exit(f"output dir not found: {root}")

    glob_pat = f"{args.only}/*/metadata.json" if args.only else "*/*/metadata.json"
    metas = sorted(root.glob(glob_pat))
    if not metas:
        sys.exit(f"no volumes found under {root}/{glob_pat}")

    total_vols = total_pages = 0
    for meta_p in metas:
        res = build_volume(meta_p.parent)
        if res:
            out_p, n = res
            total_vols += 1
            total_pages += n
            print(f"  {out_p.relative_to(root)}  ({n} pages)")
    print(f"\nDone: {total_vols} volumes, {total_pages} pages -> HTML")


if __name__ == "__main__":
    main()
