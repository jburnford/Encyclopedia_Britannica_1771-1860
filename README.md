# Encyclopaedia Britannica — Chandra 2 OCR pipeline

One clean pipeline: the NLS Foundry *Encyclopaedia Britannica 1768–1860* dataset
(195 volumes, ~155,388 page images, editions 1–8 plus supplements) OCR'd with
[Chandra 2](https://huggingface.co/datalab-to/chandra-ocr-2) on Nibi H100s,
**keeping page headers and footers** (`include_headers_footers=True`).

## Data flow

```
/project/def-jic823/nls-data-encyclopaediaBritannica/   # NLS source (read-only)
    <identifier>/<identifier>-mets.xml                  # page order, rights, dates
    <identifier>/image/*.jpg                            # 600x797 page images
    encyclopaediaBritannica-inventory.csv               # id -> title (edition, volume, EB code)

/project/def-jic823/britannica_chandra2/                # this pipeline's data root
    manifest/volumes.{csv,jsonl}    # master metadata, one row per volume
    chunks/chunk_N.txt              # volume ids per SLURM array task
    output/<EB code>/<identifier>/
        pages.jsonl                 # per-page: image id, markdown, raw, tokens (resumable)
        <identifier>.md             # merged volume markdown with page/image separators
        metadata.json               # manifest record + processing stats + page order
        COMPLETE                    # success flag
    logs/
```

No PDF conversion: page JPEGs are fed straight to the model via Chandra's
Python API, batched 28 at a time against a per-job vLLM server. Page order is
taken from each volume's METS structMap, so every output page maps back to its
NLS image id and ALTO file.

## Run

```bash
# 1. build manifest (login node, seconds)
python3 scripts/build_manifest.py \
    --data-dir /project/def-jic823/nls-data-encyclopaediaBritannica \
    --out-dir  /project/def-jic823/britannica_chandra2/manifest

# 2. chunk into array tasks (3 volumes ≈ 2,600 pages ≈ 3-4 h each)
#    --codes keeps one copy per edition: EB.1 (1771 1st) over EB.3 (1773 reprint);
#    EB.5 over EB.6 (both 1797 3rd); EB.7 (1801) over EB.8 (1803 suppl. to 3rd);
#    EB.12 over EB.13/EB.14 (1824 suppl. to 4th-6th) -> 163 vols, ~127k pages
python3 scripts/make_chunks.py \
    --manifest /project/def-jic823/britannica_chandra2/manifest/volumes.jsonl \
    --chunks-dir /project/def-jic823/britannica_chandra2/chunks \
    --codes EB.1,EB.4,EB.5,EB.7,EB.9,EB.10,EB.11,EB.12,EB.15,EB.16

# 3. pilot: first chunk only (1771 first edition)
cd /project/def-jic823/britannica_chandra2/scripts
sbatch --array=0 run_batch.slurm

# 4. full run, 4 concurrent GPUs
sbatch --array=1-54%4 run_batch.slurm
```

Re-running a chunk is safe: completed volumes are skipped via `COMPLETE`,
partially done volumes resume from `pages.jsonl`.

Throughput basis: chandra2 jobs 15838597 / 15843921 measured ~13–19 pages/min
per H100 → full corpus ≈ 165–200 GPU-hours.

## Rights

NLS: items to 1853 are public domain; 1854–1860 "No Known Copyright". The
per-volume rights statement from METS is carried into each `metadata.json`.
