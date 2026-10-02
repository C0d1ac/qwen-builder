#!/usr/bin/env python3
"""Generate per-part Dockerfiles using the Hugging Face CLI."""

import json
import urllib.request
import os

MODEL_ID = "unsloth/Qwen3.8-Flash-Next"
NUM_PARTS = 10
MAX_LAYER_BYTES = 9 * 1024**3

print("Fetching file list...")
url = f"https://huggingface.co/api/models/{MODEL_ID}/tree/main"
with urllib.request.urlopen(url) as r:
    files = [f for f in json.loads(r.read()) 
             if f.get('type') == 'file' and '/' not in f.get('path', '') and not f['path'].startswith('.')]

files.sort(key=lambda x: x['path'])
config_files = [f for f in files if not f['path'].endswith('.safetensors')]
safetensors = [f for f in files if f['path'].endswith('.safetensors')]

# Estimate sizes if missing
for f in safetensors:
    if not f.get('size'):
        f['size'] = 1.9 * 1024**3

total = sum(f['size'] for f in safetensors)
per_part = total // NUM_PARTS + (1 if total % NUM_PARTS else 0)
print(f"Total: {total/1024**3:.1f}GB, Target per part: {per_part/1024**3:.1f}GB")

# Split into ten target parts, omitting empty parts if the repository has fewer files.
parts = [[] for _ in range(NUM_PARTS)]
part_idx = 0
part_size = 0
for f in safetensors:
    if part_size + f['size'] > per_part and part_idx < NUM_PARTS - 1:
        part_idx += 1
        part_size = 0
    parts[part_idx].append(f)
    part_size += f['size']

parts = [part for part in parts if part]

os.makedirs("split-dockerfiles", exist_ok=True)

for i, part in enumerate(parts):
    part_num = i + 1
    size_gb = sum(f['size'] for f in part) / 1024**3
    print(f"Part {part_num}: {len(part)} shards, {size_gb:.1f}GB")
    
    with open(f"split-dockerfiles/Dockerfile.part{part_num}", 'w') as df:
        df.write("FROM python:3.12-slim\n")
        df.write("ARG HF_TOKEN\n")
        df.write("ENV HF_TOKEN=$HF_TOKEN\n")
        df.write("RUN pip install --no-cache-dir huggingface_hub\n")
        df.write("RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*\n")
        df.write("WORKDIR /root/.cache/huggingface\n\n")
        
        # Config files only in part 1
        if part_num == 1:
            df.write("# Config & tokenizer\n")
            download_files = config_files + part
        else:
            download_files = part
        regular_files = [f for f in download_files if f["size"] <= MAX_LAYER_BYTES]
        large_files = [f for f in download_files if f["size"] > MAX_LAYER_BYTES]
        if regular_files:
            df.write("RUN hf download \\\n")
            df.write(f"    {MODEL_ID} \\\n")
            for index, f in enumerate(regular_files):
                suffix = " \\\n" if index < len(regular_files) - 1 else "\n"
                df.write(f'    "{f["path"]}"{suffix}')
            df.write("\n")
        for f in large_files:
            chunk_count = (f["size"] + MAX_LAYER_BYTES - 1) // MAX_LAYER_BYTES
            safe_name = f["path"].replace("/", "_")
            url = f"https://huggingface.co/{MODEL_ID}/resolve/main/{f['path']}"
            for index in range(chunk_count):
                start = index * MAX_LAYER_BYTES
                end = min(f["size"], start + MAX_LAYER_BYTES) - 1
                chunk_name = f"{safe_name}.part{index:03d}"
                df.write(
                    f"RUN mkdir -p /root/.cache/huggingface/chunks && "
                    f"curl --fail --location --retry 5 --retry-all-errors "
                        f"-H \"Authorization: Bearer $HF_TOKEN\" "
                        f"-H \"Range: bytes={start}-{end}\" "
                        f"\"{url}\" -o "
                    f"/root/.cache/huggingface/chunks/{chunk_name}\n"
                )

print("\nDone! Files in split-dockerfiles/")