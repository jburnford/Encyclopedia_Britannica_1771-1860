#!/usr/bin/env python3
"""OCR one NLS volume (a directory of page JPEGs) with Chandra 2 via vLLM.

Feeds page images directly to the model (no PDF conversion). Page order comes
from the volume's METS structMap; falls back to numeric filename sort. Output
is per-page (pages.jsonl, resumable) plus one merged markdown per volume with
page/image-id separators, and a metadata.json carrying the manifest record.

Requires VLLM_API_BASE to point at a running vLLM server (set by the SLURM
wrapper). Run inside the chandra2 venv.

  python3 chandra_volume.py \
      --identifier 144133901 \
      --manifest /project/def-jic823/britannica_chandra2/manifest/volumes.jsonl \
      --out-root /project/def-jic823/britannica_chandra2/output
"""

import argparse
import json
import sys
import time
from pathlib import Path

from chandra.input import load_image
from chandra.model import InferenceManager
from chandra.model.schema import BatchInputItem

from build_manifest import parse_mets  # same scripts dir

CHANDRA_SETTINGS = {
    "model": "datalab-to/chandra-ocr-2",
    "prompt_type": "ocr_layout",
    "include_headers_footers": True,
    "include_images": False,
}


def page_order(volume_dir: Path, identifier: str) -> list:
    mets = volume_dir / f"{identifier}-mets.xml"
    if mets.exists():
        pages = parse_mets(mets)["pages"]
        if pages:
            return pages
    # fallback: numeric sort on leading image id ("188386434.3.jpg" -> 188386434)
    imgs = [p.name for p in (volume_dir / "image").glob("*.jpg")]
    return sorted(imgs, key=lambda n: int(n.split(".")[0]))


def load_done(pages_jsonl: Path) -> dict:
    done = {}
    if pages_jsonl.exists():
        with open(pages_jsonl, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not rec.get("error"):
                    done[rec["image"]] = rec
    return done


def ocr_pages(model, volume_dir, images, batch_size, out_f):
    """OCR the given image filenames; append results to out_f. Returns #errors."""
    errors = 0
    for start in range(0, len(images), batch_size):
        chunk = images[start : start + batch_size]
        batch, loaded = [], []
        for name in chunk:
            try:
                img = load_image(str(volume_dir / "image" / name))
                batch.append(BatchInputItem(image=img, prompt_type="ocr_layout"))
                loaded.append(name)
            except Exception as e:
                print(f"  [load-error] {name}: {e}", flush=True)
                out_f.write(json.dumps({"image": name, "error": True,
                                        "error_kind": "load", "msg": str(e)}) + "\n")
                errors += 1
        if not batch:
            continue
        t0 = time.time()
        results = model.generate(
            batch,
            include_headers_footers=CHANDRA_SETTINGS["include_headers_footers"],
            include_images=CHANDRA_SETTINGS["include_images"],
        )
        dt = time.time() - t0
        for name, res in zip(loaded, results):
            rec = {
                "image": name,
                "markdown": res.markdown,
                "raw": res.raw,
                "token_count": res.token_count,
                "error": bool(res.error),
            }
            if res.error:
                errors += 1
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_f.flush()
        print(f"  pages {start + 1}-{start + len(chunk)} of {len(images)}: "
              f"{dt:.0f}s ({len(batch) / dt:.2f} p/s)", flush=True)
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--identifier", required=True)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--batch-size", type=int, default=28)
    args = ap.parse_args()

    meta = None
    with open(args.manifest, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["identifier"] == args.identifier:
                meta = rec
                break
    if meta is None:
        sys.exit(f"identifier {args.identifier} not in manifest")

    volume_dir = Path(meta["volume_dir"])
    out_dir = args.out_root / (meta["eb_code"] or "unknown") / args.identifier
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_jsonl = out_dir / "pages.jsonl"
    complete_flag = out_dir / "COMPLETE"

    if complete_flag.exists():
        print(f"[{args.identifier}] already complete, skipping")
        return

    images = page_order(volume_dir, args.identifier)
    done = load_done(pages_jsonl)
    todo = [n for n in images if n not in done]
    print(f"[{args.identifier}] {meta['title']}")
    print(f"[{args.identifier}] {len(images)} pages, {len(done)} done, {len(todo)} to OCR")

    model = InferenceManager(method="vllm")

    t0 = time.time()
    with open(pages_jsonl, "a", encoding="utf-8") as out_f:
        errors = ocr_pages(model, volume_dir, todo, args.batch_size, out_f)
        if errors:
            # one retry pass over failed pages
            done = load_done(pages_jsonl)
            retry = [n for n in images if n not in done]
            print(f"[{args.identifier}] retrying {len(retry)} failed pages", flush=True)
            errors = ocr_pages(model, volume_dir, retry, args.batch_size, out_f)

    # Assemble merged volume markdown in METS page order
    done = load_done(pages_jsonl)
    missing = [n for n in images if n not in done]
    parts = []
    for i, name in enumerate(images, 1):
        parts.append(f"<!-- page {i} | image {name} -->\n\n")
        if name in done:
            parts.append(done[name]["markdown"].strip() + "\n\n")
        else:
            parts.append("[OCR FAILED]\n\n")
    md_path = out_dir / f"{args.identifier}.md"
    md_path.write_text("".join(parts), encoding="utf-8")

    metadata = {
        **{k: v for k, v in meta.items()},
        "chandra": CHANDRA_SETTINGS,
        "n_pages": len(images),
        "n_ocr_ok": len(done),
        "failed_pages": missing,
        "total_tokens": sum(r["token_count"] for r in done.values()),
        "elapsed_s": round(time.time() - t0, 1),
        "page_image_order": images,
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if missing:
        print(f"[{args.identifier}] DONE WITH ERRORS: {len(missing)} pages failed")
        sys.exit(1)
    complete_flag.touch()
    print(f"[{args.identifier}] COMPLETE: {len(images)} pages, "
          f"{metadata['total_tokens']} tokens, {metadata['elapsed_s']}s")


if __name__ == "__main__":
    main()
