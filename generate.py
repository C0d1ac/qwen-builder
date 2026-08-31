#!/usr/bin/env python3
"""Just generates 7 Dockerfiles using wget"""

import json
import urllib.request
import os

MODEL_ID = "Qwen/Qwen3.8-Flash-Next"
BASE_URL = f"https://huggingface.co/{MODEL_ID}/resolve/main"
NUM_PARTS = 7

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

# Split into 7 parts
parts = [[] for _ in range(NUM_PARTS)]
part_idx = 0
part_size = 0
for f in safetensors:
    if part_size + f['size'] > per_part and part_idx < NUM_PARTS - 1:
        part_idx += 1
        part_size = 0
    parts[part_idx].append(f)
    part_size += f['size']

os.makedirs("split-dockerfiles", exist_ok=True)

for i, part in enumerate(parts):
    part_num = i + 1
    size_gb = sum(f['size'] for f in part) / 1024**3
    print(f"Part {part_num}: {len(part)} shards, {size_gb:.1f}GB")
    
    with open(f"split-dockerfiles/Dockerfile.part{part_num}", 'w') as df:
        df.write("FROM alpine:latest\n")
        df.write("RUN apk add --no-cache wget ca-certificates\n")
        df.write("WORKDIR /model\n\n")
        
        # Config files only in part 1
        if part_num == 1:
            df.write("# Config & tokenizer\n")
            for f in config_files:
                df.write(f'RUN wget -q "{BASE_URL}/{f["path"]}" -O "/model/{f["path"]}"\n')
            df.write("\n")
        
        # Group shards into layers (~8GB each)
        layer = []
        layer_size = 0
        max_layer = 8 * 1024**3
        
        for f in part:
            layer.append(f)
            layer_size += f['size']
            
            if layer_size >= max_layer:
                df.write(f"# ~{layer_size/1024**3:.1f}GB layer\n")
                df.write("RUN \\\n")
                for j, sf in enumerate(layer):
                    end = " && \\\n" if j < len(layer) - 1 else "\n"
                    df.write(f'    wget -q "{BASE_URL}/{sf["path"]}" -O "/model/{sf["path"]}"{end}')
                df.write("\n")
                layer = []
                layer_size = 0
        
        if layer:
            df.write(f"# ~{layer_size/1024**3:.1f}GB layer\n")
            df.write("RUN \\\n")
            for j, sf in enumerate(layer):
                end = " && \\\n" if j < len(layer) - 1 else "\n"
                df.write(f'    wget -q "{BASE_URL}/{sf["path"]}" -O "/model/{sf["path"]}"{end}')

print("\nDone! Files in split-dockerfiles/")