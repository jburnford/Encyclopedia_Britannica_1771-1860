#!/usr/bin/env python3
"""Build a self-contained HTML review interface for the parsed article records.

Emits one page per volume under review_html/ (data embedded as JSON, so it opens
straight from file:// with no server) plus an index.html. Records are shown in
page / reading order (the order parse_articles.py emits them). Designed for
eyeballing segmentation errors: filters by type / detection signal / cross-ref,
free-text search, and a "problems only" toggle that surfaces likely-bad records
(empty body, fragment, page-number anomalies, possible bleed).

Usage:
    python3 scripts/build_review_html.py [--article-dir article_data] [--out review_html]
"""
import argparse
import json
import re
from pathlib import Path

# Articles/sub-entries are embedded in full (so they can be proof-read end to end);
# only treatises are clipped — a 974K-char ANATOMY would bloat the page, and the
# treatise `outline` is the right tool for navigating those anyway.
TREATISE_CLIP = 12000


def wc(t):
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9]+", t or ""))


def problems(r):
    """Heuristic error flags, computed at build time so the viewer can filter."""
    flags = []
    body = (r.get("body_text") or "").strip()
    hw = (r.get("headword") or "").strip()
    if body.rstrip(".,") == hw.rstrip(".,"):
        flags.append("empty-body")
    elif wc(body) <= 4 and not r.get("is_cross_reference") and r.get("type") != "treatise":
        flags.append("fragment")
    ps, pe = r.get("printed_page_start"), r.get("printed_page_end")
    # relative checks only — editions differ in pagination (EB.1 resets per volume,
    # EB.4 runs continuously to ~9000), so an absolute page ceiling is meaningless.
    if ps and pe and pe < ps:
        flags.append("page-end<start")
    if ps and pe and r.get("type") != "treatise" and pe - ps > 30:
        flags.append("page-span-large")   # a non-treatise spanning >30pp is suspicious
    if r.get("type") != "treatise" and r.get("char_count", 0) > 25000:
        flags.append("long-maybe-bleed")
    return flags


def trim(r):
    body = r.get("body_text") or ""
    clip = TREATISE_CLIP if r.get("type") == "treatise" else None
    clipped = clip is not None and len(body) > clip
    if clipped:
        body = body[:clip] + f" …[treatise body truncated in viewer — full {r.get('char_count')} chars in JSONL]"
    return {
        "headword": r.get("headword"),
        "base": r.get("base_headword"),
        "qualifier": r.get("qualifier"),
        "type": r.get("type"),
        "by": r.get("detected_by"),
        "xref": bool(r.get("is_cross_reference")),
        "ps": r.get("printed_page_start"),
        "pe": r.get("printed_page_end"),
        "is": r.get("image_page_start"),
        "ie": r.get("image_page_end"),
        "cc": r.get("char_count"),
        "refs": r.get("cross_refs") or [],
        "outline": len(r.get("outline") or []),
        "img": (r.get("provenance") or {}).get("headword_image"),
        "body": body,
        "flags": problems(r),
    }


PAGE_TMPL = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EB review — __TITLE__</title>
<style>
  :root { --bg:#faf8f4; --card:#fff; --ink:#222; --mut:#777; --line:#e3ddd2;
          --accent:#7a4a1e; --warn:#b00020; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 -apple-system,Segoe UI,Roboto,Georgia,serif;
         background:var(--bg); color:var(--ink); }
  header { position:sticky; top:0; z-index:5; background:var(--card);
           border-bottom:1px solid var(--line); padding:10px 16px;
           box-shadow:0 1px 4px rgba(0,0,0,.05); }
  h1 { font-size:17px; margin:0 0 6px; }
  h1 a { color:var(--mut); text-decoration:none; font-weight:normal; font-size:13px; }
  .controls { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; font-size:13px; }
  .controls input[type=text] { padding:5px 8px; border:1px solid var(--line);
           border-radius:6px; min-width:220px; font-size:13px; }
  .controls label { display:inline-flex; gap:4px; align-items:center; cursor:pointer; }
  .stat { color:var(--mut); }
  main { max-width:980px; margin:0 auto; padding:14px 16px 60px; }
  .rec { background:var(--card); border:1px solid var(--line); border-radius:8px;
         padding:10px 14px; margin:8px 0; }
  .rec.flagged { border-left:4px solid var(--warn); }
  .hw { font-weight:700; font-size:16px; }
  .meta { color:var(--mut); font-size:12px; margin:2px 0 6px; display:flex;
          flex-wrap:wrap; gap:4px 10px; align-items:center; }
  .chip { font-size:11px; padding:1px 7px; border-radius:10px; background:#efe9df;
          color:#5a4a33; white-space:nowrap; }
  .chip.t-treatise { background:#dfeaf5; color:#1d4e79; }
  .chip.t-sub_entry { background:#f3e6f0; color:#7a2e6e; }
  .chip.xref { background:#fff3cd; color:#7a5b00; }
  .chip.flag { background:#fde2e4; color:var(--warn); }
  .body { white-space:pre-wrap; }
  .refs { font-size:12px; color:var(--accent); margin-top:5px; }
  .pager { text-align:center; margin:16px 0; font-size:13px; }
  .pager button { padding:5px 12px; margin:0 4px; border:1px solid var(--line);
           background:var(--card); border-radius:6px; cursor:pointer; }
  mark { background:#fff07a; }
</style></head><body>
<header>
  <h1>Encyclopaedia Britannica — article review &nbsp; <a href="index.html">◂ all volumes</a></h1>
  <div class="controls">
    <input id="q" type="text" placeholder="search headword or body…" autocomplete="off">
    <label><input type="checkbox" class="ty" value="article" checked> article</label>
    <label><input type="checkbox" class="ty" value="sub_entry" checked> sub_entry</label>
    <label><input type="checkbox" class="ty" value="treatise" checked> treatise</label>
    <label><input type="checkbox" id="xref" checked> show cross-refs</label>
    <label><input type="checkbox" id="prob"> problems only</label>
    <span class="stat" id="stat"></span>
  </div>
</header>
<main><div id="list"></div><div class="pager" id="pager"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const RECS = JSON.parse(document.getElementById('data').textContent);
const PER = 100;
let page = 0, view = RECS;
const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function hl(s, q) {
  s = esc(s);
  if (!q) return s;
  try { return s.replace(new RegExp('('+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'),'<mark>$1</mark>'); }
  catch(e) { return s; }
}
function render() {
  const q = $('#q').value.trim();
  const tys = [...document.querySelectorAll('.ty:checked')].map(c=>c.value);
  const showX = $('#xref').checked, probOnly = $('#prob').checked;
  const ql = q.toLowerCase();
  view = RECS.filter(r => {
    if (!tys.includes(r.type)) return false;
    if (!showX && r.xref) return false;
    if (probOnly && (!r.flags || !r.flags.length)) return false;
    if (ql && !(r.headword||'').toLowerCase().includes(ql)
           && !(r.body||'').toLowerCase().includes(ql)) return false;
    return true;
  });
  const pages = Math.ceil(view.length/PER) || 1;
  if (page >= pages) page = 0;
  const slice = view.slice(page*PER, page*PER+PER);
  $('#list').innerHTML = slice.map((r) => {
    const rank = view.indexOf(r) + 1;
    const chips = ['<span class="chip t-'+r.type+'">'+r.type+'</span>',
      '<span class="chip">'+r.by+'</span>'];
    if (r.xref) chips.push('<span class="chip xref">cross-ref</span>');
    (r.flags||[]).forEach(f => chips.push('<span class="chip flag">'+f+'</span>'));
    const pp = (r.ps!=null||r.pe!=null) ? 'pp '+(r.ps??'?')+'–'+(r.pe??'?') : 'pp —';
    const refs = r.refs.length ? '<div class="refs">→ '+r.refs.map(esc).join(' · ')+'</div>' : '';
    const ol = r.type==='treatise' ? ' · outline:'+r.outline : '';
    const qual = r.qualifier ? '<span class="chip" style="background:#eee">qual: '+esc(r.qualifier)+'</span>' : '';
    const img = r.img ? '<span style="color:#aaa">'+esc(r.img)+'</span>' : '';
    return '<div class="rec '+((r.flags&&r.flags.length)?'flagged':'')+'">'+
      '<div class="hw">#'+rank+' &nbsp;'+hl(r.headword, q)+'</div>'+
      '<div class="meta">'+
        '<span class="chip" style="background:#e7efe7;color:#2a5">base: '+esc(r.base||'')+'</span>'+
        qual + chips.join('') +
        '<span>'+pp+' · img '+r.is+'–'+r.ie+' · '+r.cc+' chars'+ol+'</span>'+ img +
      '</div>'+
      '<div class="body">'+hl(r.body, q)+'</div>'+refs+
    '</div>';
  }).join('') || '<p style="color:#999">no records match.</p>';
  $('#stat').textContent = view.length+' / '+RECS.length+' records · page '+(page+1)+'/'+pages;
  $('#pager').innerHTML =
    '<button onclick="go(-1)" '+(page<=0?'disabled':'')+'>◂ prev</button>'+
    '<button onclick="go(1)" '+(page>=pages-1?'disabled':'')+'>next ▸</button>';
  window.scrollTo(0,0);
}
function go(d) { page += d; render(); }
document.querySelectorAll('input').forEach(el =>
  el.addEventListener('input', () => { page=0; render(); }));
render();
</script>
</body></html>
"""

INDEX_TMPL = """<!doctype html><html><head><meta charset="utf-8">
<title>EB article review</title>
<style>body{font:15px/1.5 -apple-system,Segoe UI,Roboto,serif;max-width:760px;
margin:40px auto;padding:0 20px;color:#222}h1{font-size:20px}
table{border-collapse:collapse;width:100%;margin-top:16px}
th,td{text-align:left;padding:7px 12px;border-bottom:1px solid #e3ddd2}
td:not(:first-child),th:not(:first-child){text-align:right}
a{color:#7a4a1e}</style></head><body>
<h1>Encyclopaedia Britannica — parsed article review</h1>
<p>__TOTAL__ records across __NVOL__ volumes, in page order. Click a volume to inspect.</p>
<table><tr><th>Volume</th><th>Records</th><th>Cross-refs</th><th>Flagged</th></tr>
__ROWS__</table>
<p style="color:#777;font-size:13px">Flagged = heuristic problem candidates (empty body,
fragment, page-number anomaly, possible bleed). Use the "problems only" toggle in each volume.</p>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article-dir", default="article_data")
    ap.add_argument("--out", default="review_html")
    args = ap.parse_args()
    art = Path(args.article_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    index_rows = []
    for jp in sorted(art.glob("*.jsonl")):
        recs = [json.loads(l) for l in jp.open() if l.strip()]
        trimmed = [trim(r) for r in recs]
        nflag = sum(1 for t in trimmed if t["flags"])
        nxref = sum(1 for t in trimmed if t["xref"])
        title = jp.stem
        html = (PAGE_TMPL
                .replace("__TITLE__", title)
                .replace("__DATA__", json.dumps(trimmed, ensure_ascii=False)))
        page_name = jp.stem + ".html"
        (out / page_name).write_text(html, encoding="utf-8")
        index_rows.append((title, page_name, len(recs), nxref, nflag))
        print(f"{title}: {len(recs)} records ({nxref} cross-refs, {nflag} flagged) -> {out/page_name}")

    rows = "\n".join(
        f'<tr><td><a href="{p}">{t}</a></td><td>{n:,}</td>'
        f'<td>{x:,}</td><td>{f:,}</td></tr>'
        for (t, p, n, x, f) in index_rows)
    total = sum(r[2] for r in index_rows)
    (out / "index.html").write_text(
        INDEX_TMPL.replace("__TOTAL__", f"{total:,}")
                  .replace("__NVOL__", str(len(index_rows)))
                  .replace("__ROWS__", rows), encoding="utf-8")
    print(f"\nindex -> {out/'index.html'}  ({total:,} records)")


if __name__ == "__main__":
    main()
