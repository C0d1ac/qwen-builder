#!/usr/bin/env python3
"""
generate_splits.py - Creates split Dockerfiles and GitHub Actions workflow
"""

import json
import urllib.request
import sys
import os

MODEL_ID = "Qwen/Qwen3.8-Flash-Next"
MAX_IMAGE_SIZE_GB = 55
MAX_LAYER_SIZE_GB = 8
GHCR_OWNER = "c0d1ac"  # Change this!

# Fetch file list WITH SIZES from tree endpoint
print("Fetching file list with sizes...")
url = f"https://huggingface.co/api/models/{MODEL_ID}/tree/main"

try:
    with urllib.request.urlopen(url) as response:
        tree_data = json.loads(response.read().decode())
except Exception as e:
    print(f"Error fetching tree: {e}")
    sys.exit(1)

# Collect files with sizes
files = []
for f in tree_data:
    if f.get('type') != 'file':
        continue
    name = f['path']
    if '/' in name or name.startswith('.git'):
        continue
    size = f.get('size', 0)
    files.append({'name': name, 'size': size})

files.sort(key=lambda x: x['name'])

# Separate config and safetensors
config_files = [f for f in files if not f['name'].endswith('.safetensors')]
safetensors = [f for f in files if f['name'].endswith('.safetensors')]

total_size = sum(f['size'] for f in files)
safetensors_size = sum(f['size'] for f in safetensors)

print(f"Config files: {len(config_files)}")
print(f"Safetensors: {len(safetensors)}")
print(f"Total size: {total_size / 1024**3:.2f} GB")
print(f"Safetensors size: {safetensors_size / 1024**3:.2f} GB")

# Verify we have sizes
if total_size == 0:
    print("\nERROR: All file sizes are 0. The API might be rate-limited or changed.")
    print("Falling back to equal split by shard count...")
    
    # Fallback: split equally by count, estimate ~1.9GB per shard
    estimated_shard_size = 1.9 * 1024**3  # ~1.9GB
    for f in safetensors:
        f['size'] = estimated_shard_size
    total_size = sum(f['size'] for f in files)
    print(f"Estimated total size: {total_size / 1024**3:.2f} GB")

# Split safetensors into parts
max_part_bytes = MAX_IMAGE_SIZE_GB * 1024**3
parts = []
current_part = []
current_size = 0

for f in safetensors:
    if current_size + f['size'] > max_part_bytes and current_part:
        parts.append(current_part)
        current_part = []
        current_size = 0
    current_part.append(f)
    current_size += f['size']

if current_part:
    parts.append(current_part)

print(f"\nSplit into {len(parts)} parts:")
for i, part in enumerate(parts):
    size_gb = sum(f['size'] for f in part) / 1024**3
    first_shard = part[0]['name']
    last_shard = part[-1]['name']
    print(f"  Part {i+1}: {len(part)} shards, {size_gb:.2f} GB ({first_shard} to {last_shard})")

# Create output directory
os.makedirs("split-dockerfiles", exist_ok=True)

# Generate Dockerfile for each part
for i, part in enumerate(parts):
    part_num = i + 1
    filename = f"split-dockerfiles/Dockerfile.part{part_num}"
    
    with open(filename, 'w') as df:
        df.write(f"# Part {part_num} of {len(parts)}\n")
        df.write(f"# Shards: {part[0]['name']} to {part[-1]['name']}\n")
        df.write(f"# Size: ~{sum(f['size'] for f in part) / 1024**3:.2f} GB\n\n")
        
        df.write("FROM alpine:latest AS downloader\n")
        df.write("RUN apk add --no-cache git git-lfs ca-certificates\n")
        df.write("WORKDIR /downloads\n\n")
        
        # Build the git lfs pull command with includes
        includes = [f['name'] for f in part]
        if part_num == 1:
            includes += [f['name'] for f in config_files]
        
        df.write("RUN git lfs install && \\\n")
        df.write(f"    git clone --depth 1 --filter=blob:none https://huggingface.co/{MODEL_ID} repo && \\\n")
        df.write("    cd repo && \\\n")
        df.write("    git lfs pull \\\n")
        for inc in includes:
            df.write(f'        --include="{inc}" \\\n')
        df.write("    && cd .. && \\\n")
        df.write("    mkdir -p /model && \\\n")
        df.write("    cd repo && \\\n")
        for f in part:
            df.write(f"    cp {f['name']} /model/ && \\\n")
        if part_num == 1:
            for f in config_files:
                df.write(f"    cp {f['name']} /model/ && \\\n")
        df.write("    cd .. && rm -rf repo\n\n")
        
        df.write("FROM alpine:latest\n")
        df.write("WORKDIR /model\n\n")
        
        # Config files in part 1 only
        if part_num == 1:
            for f in config_files:
                df.write(f"COPY --from=downloader /model/{f['name']} /model/{f['name']}\n")
            df.write("\n")
        
        # Safetensors in batches under layer limit
        max_layer_bytes = MAX_LAYER_SIZE_GB * 1024**3
        layer_batch = []
        layer_size = 0
        
        for f in part:
            layer_batch.append(f)
            layer_size += f['size']
            
            if layer_size >= max_layer_bytes:
                batch_gb = layer_size / 1024**3
                df.write(f"# Layer ~{batch_gb:.1f} GB\n")
                for bf in layer_batch:
                    df.write(f"COPY --from=downloader /model/{bf['name']} /model/{bf['name']}\n")
                df.write("\n")
                layer_batch = []
                layer_size = 0
        
        if layer_batch:
            batch_gb = layer_size / 1024**3
            df.write(f"# Layer ~{batch_gb:.1f} GB\n")
            for bf in layer_batch:
                df.write(f"COPY --from=downloader /model/{bf['name']} /model/{bf['name']}\n")
    
    print(f"Created {filename}")

# Generate GitHub Actions workflow
workflow = """name: Build Qwen Model Parts

on:
  workflow_dispatch:
  push:
    paths:
      - 'split-dockerfiles/**'

jobs:
"""

for i in range(len(parts)):
    part_num = i + 1
    workflow += f"""  build-part{part_num}:
    runs-on: ubuntu-latest
    permissions:
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Free disk space
        run: |
          sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc
          sudo apt-get clean
          df -h /

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: """ + "${{ github.actor }}" + """
          password: """ + "${{ secrets.GITHUB_TOKEN }}" + """

      - name: Build part {part_num}
        run: |
          docker build -f split-dockerfiles/Dockerfile.part{part_num} \\
            -t ghcr.io/{GHCR_OWNER}/qwen-part{part_num}:latest .

      - name: Push part {part_num}
        run: docker push ghcr.io/{GHCR_OWNER}/qwen-part{part_num}:latest

"""

os.makedirs(".github/workflows", exist_ok=True)
with open(".github/workflows/build-qwen.yml", 'w') as f:
    f.write(workflow)

print("\nCreated .github/workflows/build-qwen.yml")
print("\n=== Done! ===")