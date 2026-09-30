#!/usr/bin/env python3
"""
download_chunks.py — Download each planned chunk via HTTP Range through a proxy.

Why Range requests?
  HF LFS storage supports Range. Instead of downloading a 50GB shard and then
  splitting it on disk (needs 100GB disk), we stream just the bytes we need
  for each chunk directly from the proxy. One file on disk per chunk.

Resumable:
  If a chunk file already exists with the expected size, it is skipped.
  If it exists with the wrong size, it is truncated and re-downloaded.

ENV:
  HF_TOKEN     — optional bearer token for gated repos
  HF_ENDPOINT  — proxy/mirror base, default https://huggingface.co
  PARALLEL     — number of chunks to download in parallel (default 1)
  MANIFEST     — path to manifest.json (default ./manifest.json)
  OUT_DIR      — where to write chunks (default ./chunks)
"""
import os
import sys
import json
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

HF_TOKEN    = os.environ.get("HF_TOKEN", "")
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
PARALLEL    = int(os.environ.get("PARALLEL", "1"))
MANIFEST    = Path(os.environ.get("MANIFEST", "./manifest.json"))
OUT_DIR     = Path(os.environ.get("OUT_DIR", "./chunks"))

# 8 MiB streaming buffer — large enough to amortize syscalls, small enough
# to not OOM under parallel downloads.
STREAM_BUF = 8 * 1024 * 1024

# Retry config
MAX_RETRIES = 5
TIMEOUT     = (30, 300)  # connect, read


def auth_headers():
    h = {}
    if HF_TOKEN:
        h["Authorization"] = f"Bearer {HF_TOKEN}"
    return h


def human(n):
    if n >= 1e9: return f"{n/1e9:.2f}GB"
    if n >= 1e6: return f"{n/1e6:.2f}MB"
    if n >= 1e3: return f"{n/1e3:.2f}KB"
    return f"{n}B"


def download_one(chunk, repo_id):
    """Download a single chunk using HTTP Range. Returns (chunk_name, status)."""
    url = f"{HF_ENDPOINT}/{repo_id}/resolve/main/{chunk['source_file']}"
    out = OUT_DIR / chunk["chunk_name"]

    # Resume / skip
    if out.exists() and out.stat().st_size == chunk["size"]:
        return (chunk["chunk_name"], f"skip ({human(chunk['size'])})")

    # Resume partial download if size mismatch but smaller than expected
    existing = out.stat().st_size if out.exists() else 0
    if existing and chunk["size"] > 0 and existing < chunk["size"]:
        mode = "ab"
        range_start = existing
    else:
        mode = "wb"
        range_start = 0

    headers = auth_headers()
    if chunk["size"] > 0:
        # Chunked: get bytes [offset + range_start, offset + size - 1]
        start = chunk["offset"] + range_start
        end   = chunk["offset"] + chunk["size"] - 1
        headers["Range"] = f"bytes={start}-{end}"
    elif range_start == 0:
        # Zero-size file (rare). Just create empty file.
        out.write_bytes(b"")
        return (chunk["chunk_name"], "empty (0B)")

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with requests.get(url, headers=headers, stream=True,
                              allow_redirects=True, timeout=TIMEOUT) as r:
                r.raise_for_status()
                with open(out, mode) as f:
                    for buf in r.iter_content(chunk_size=STREAM_BUF):
                        if buf:
                            f.write(buf)
            actual = out.stat().st_size
            expected = chunk["size"] - range_start
            if actual == expected:
                return (chunk["chunk_name"], f"ok ({human(actual)})")
            # Otherwise loop to retry from new partial position
            existing = out.stat().st_size
            mode = "ab"
            range_start = existing
            start = chunk["offset"] + range_start
            end   = chunk["offset"] + chunk["size"] - 1
            headers["Range"] = f"bytes={start}-{end}"
        except Exception as e:
            last_err = e
            mode = "ab"  # try to resume
            existing = out.stat().st_size if out.exists() else 0
            range_start = existing
            if chunk["size"] > 0:
                start = chunk["offset"] + range_start
                end   = chunk["offset"] + chunk["size"] - 1
                headers["Range"] = f"bytes={start}-{end}"
            print(f"  retry {attempt}/{MAX_RETRIES} {chunk['chunk_name']}: {e}",
                  file=sys.stderr)
    return (chunk["chunk_name"], f"FAILED after {MAX_RETRIES}: {last_err}")


def main():
    if not MANIFEST.exists():
        print(f"manifest not found: {MANIFEST}")
        print("run: python3 generate_plan.py")
        sys.exit(1)

    manifest = json.loads(MANIFEST.read_text())
    repo_id = manifest["repo_id"]
    chunks  = manifest["chunks"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {len(chunks)} chunks from {repo_id}")
    print(f"Endpoint: {HF_ENDPOINT}  Parallel: {PARALLEL}")
    print()

    failed = []
    if PARALLEL <= 1:
        for c in chunks:
            name, status = download_one(c, repo_id)
            print(f"  {name:50s} {status}")
            if status.startswith("FAILED"):
                failed.append(name)
    else:
        with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
            futs = {ex.submit(download_one, c, repo_id): c for c in chunks}
            for fut in as_completed(futs):
                name, status = fut.result()
                print(f"  {name:50s} {status}")
                if status.startswith("FAILED"):
                    failed.append(name)

    print()
    if failed:
        print(f"FAILED: {len(failed)} chunks. Re-run to resume.")
        for n in failed:
            print(f"  {n}")
        sys.exit(1)
    print("All chunks downloaded. Next: python3 gen_dockerfile.py")


if __name__ == "__main__":
    main()