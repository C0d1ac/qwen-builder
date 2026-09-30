#!/usr/bin/env python3
"""
generate_plan.py — Build a download/layer plan for a HuggingFace model
that respects the GHCR 10GB-per-layer limit.

WHAT'S DIFFERENT FROM THE OLD SCRIPT:
  * Old script grouped *whole shard files* into parts. If one shard was 50GB,
    that part ended up 50GB → impossible to push as a Docker layer.
  * This script binary-splits EVERY file at a fixed byte boundary (default 9 GB).
    A 50GB shard becomes 6 chunks of ~8.3GB each. Every chunk → one Docker layer.
  * The chunk list is written to manifest.json. The Dockerfile generator and the
    runtime reassembler both consume this manifest.

ENV:
  HF_REPO          — repo id, e.g. nvidia/Qwen3.8-Flash-Next-NVFP4
  HF_TOKEN         — optional, for gated/private repos
  CHUNK_BYTES      — chunk size in bytes (default 9 * 1024**3 = 9663676416)
  HF_ENDPOINT      — mirror/proxy base, default https://huggingface.co
  OUT_DIR          — where to write manifest + chunks (default ./chunks)
"""
import os
import sys
import json
import math
import requests
from pathlib import Path

REPO_ID      = os.environ.get("HF_REPO", "nvidia/Qwen3.8-Flash-Next-NVFP4")
HF_TOKEN     = os.environ.get("HF_TOKEN", "")
HF_ENDPOINT  = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
CHUNK_BYTES  = int(os.environ.get("CHUNK_BYTES", 9 * 1024 * 1024 * 1024))  # 9 GiB
OUT_DIR      = Path(os.environ.get("OUT_DIR", "./chunks"))
MANIFEST     = OUT_DIR.parent / "manifest.json"

API_URL   = f"{HF_ENDPOINT}/api/models/{REPO_ID}"
RESOLVE   = f"{HF_ENDPOINT}/{REPO_ID}/resolve/main"


def auth_headers():
    h = {}
    if HF_TOKEN:
        h["Authorization"] = f"Bearer {HF_TOKEN}"
    return h


def list_repo_files():
    """Return list of {path, size} for every file in the repo."""
    r = requests.get(API_URL, headers=auth_headers(), timeout=60)
    r.raise_for_status()
    siblings = r.json().get("siblings", [])
    files = []
    for s in siblings:
        path = s["rfilename"]
        # HEAD request follows redirects to LFS storage and gives real size
        url = f"{RESOLVE}/{path}"
        h = requests.head(url, headers=auth_headers(), allow_redirects=True, timeout=60)
        size = int(h.headers.get("Content-Length", "0") or "0")
        files.append({"path": path, "size": size})
    return files


def plan_chunks(files):
    """Split every file into chunks of <= CHUNK_BYTES. Return list of chunk dicts."""
    chunks = []
    for f in files:
        size = f["size"]
        safe = f["path"].replace("/", "_").replace("\\", "_")

        # Empty / tiny files (config.json, tokenizer.json, .gitattributes, etc.)
        # Don't split — keep as a single chunk for convenience.
        if size == 0 or size <= CHUNK_BYTES:
            chunks.append({
                "source_file":  f["path"],
                "chunk_index":  0,
                "total_chunks": 1,
                "offset":       0,
                "size":         size,
                "chunk_name":   f"{safe}.part000",
            })
            continue

        n = math.ceil(size / CHUNK_BYTES)
        # Recompute per-chunk size so all chunks of THIS file are equal-sized
        # except possibly the last one. Keeps every chunk strictly < CHUNK_BYTES.
        per = math.ceil(size / n)
        for i in range(n):
            off  = i * per
            sz   = min(per, size - off)
            chunks.append({
                "source_file":  f["path"],
                "chunk_index":  i,
                "total_chunks": n,
                "offset":       off,
                "size":         sz,
                "chunk_name":   f"{safe}.part{i:03d}",
            })
    return chunks


def human(n):
    if n >= 1e9: return f"{n/1e9:.2f}GB"
    if n >= 1e6: return f"{n/1e6:.2f}MB"
    if n >= 1e3: return f"{n/1e3:.2f}KB"
    return f"{n}B"


def main():
    print("Fetching file list from", API_URL)
    files = list_repo_files()
    chunks = plan_chunks(files)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "repo_id":     REPO_ID,
        "endpoint":    HF_ENDPOINT,
        "chunk_bytes": CHUNK_BYTES,
        "files":       files,
        "chunks":      chunks,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))

    total = sum(f["size"] for f in files)
    print(f"\nRepo: {REPO_ID}")
    print(f"Files: {len(files)}")
    print(f"Total size: {human(total)}")
    print(f"Chunk size cap: {human(CHUNK_BYTES)} (GHCR limit: 10GB/layer)")
    print(f"Total chunks: {len(chunks)}")
    print(f"Largest chunk: {human(max(c['size'] for c in chunks))}")

    # Per-file breakdown
    by_file = {}
    for c in chunks:
        by_file.setdefault(c["source_file"], []).append(c)

    print("\nPer-file breakdown:")
    for fname in sorted(by_file.keys()):
        cs = by_file[fname]
        tot = sum(c["size"] for c in cs)
        print(f"  {fname:50s} {len(cs):3d} chunks  {human(tot):>10s}")

    # Sanity check — must be empty
    bad = [c for c in chunks if c["size"] > CHUNK_BYTES]
    if bad:
        print(f"\n!! {len(bad)} chunks still exceed CHUNK_BYTES — bug in planner")
        sys.exit(1)
    print(f"\nAll chunks ≤ {human(CHUNK_BYTES)} ✓")
    print(f"Manifest written to {MANIFEST}")
    print(f"Next: HF_TOKEN=... python3 download_chunks.py")


if __name__ == "__main__":
    main()