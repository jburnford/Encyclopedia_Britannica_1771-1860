#!/usr/bin/env python3
"""Group manifest volumes into chunks for SLURM array tasks.

Each chunk file lists the identifiers one array task will process (in edition
order). Default 3 volumes/chunk (~2,600 pages, ~3-4h at ~15 pages/min).

  python3 make_chunks.py \
      --manifest /project/def-jic823/britannica_chandra2/manifest/volumes.jsonl \
      --chunks-dir /project/def-jic823/britannica_chandra2/chunks \
      --per-chunk 3
"""

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--chunks-dir", required=True, type=Path)
    ap.add_argument("--per-chunk", type=int, default=3)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.manifest, encoding="utf-8")]
    # manifest is already in (eb_code, volume) order
    args.chunks_dir.mkdir(parents=True, exist_ok=True)

    chunks = [rows[i : i + args.per_chunk] for i in range(0, len(rows), args.per_chunk)]
    for i, chunk in enumerate(chunks):
        path = args.chunks_dir / f"chunk_{i}.txt"
        path.write_text("".join(r["identifier"] + "\n" for r in chunk))
        codes = ",".join(sorted({r["eb_code"] or "?" for r in chunk}))
        pages = sum(r["n_images"] for r in chunk)
        print(f"chunk_{i}: {len(chunk)} vols, {pages} pages [{codes}]")

    print(f"\n{len(chunks)} chunks. Submit e.g.:")
    print(f"  sbatch --array=0-{len(chunks) - 1}%4 run_batch.slurm")


if __name__ == "__main__":
    main()
