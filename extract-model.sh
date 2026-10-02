#!/bin/bash
set -e

OWNER="c0d1ac"
MODEL_DIR="/data/qwen-model"
NUM_PARTS=10
HF_CACHE_REPO="models--unsloth--Qwen3.8-Flash-Next"

mkdir -p "$MODEL_DIR"

echo "Login to GHCR (needs token with read:packages permission)"
echo "Create token at: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens"
read -s -p "Enter GitHub token: " GHCR_TOKEN
echo
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$OWNER" --password-stdin

for i in $(seq 1 $NUM_PARTS); do
    IMAGE="ghcr.io/$OWNER/qwen-nvfp4:part$i"
    CONTAINER="qwen-extract-$i"

    echo "========================================="
    echo "Part $i of $NUM_PARTS"
    echo "========================================="

    echo "Pulling..."
    docker pull "$IMAGE"

    echo "Extracting cached files..."
    docker create --name "$CONTAINER" "$IMAGE"
    CACHE_DIR="$(mktemp -d)"
    docker cp "$CONTAINER:/root/.cache/huggingface/hub/$HF_CACHE_REPO/snapshots/." "$CACHE_DIR/"
    find "$CACHE_DIR" -type f -o -type l | while read -r file; do
        cp -L "$file" "$MODEL_DIR/$(basename "$file")"
    done
    rm -rf "$CACHE_DIR"
    docker rm "$CONTAINER"

    echo "Removing image to free disk..."
    docker rmi "$IMAGE"

    echo "Done. Disk free: $(df -h / | tail -1 | awk '{print $4}')"
    echo
done

echo "========================================="
echo "EXTRACTION COMPLETE"
echo "========================================="
echo "Location: $MODEL_DIR"
echo "Files: $(ls "$MODEL_DIR" | wc -l)"
echo "Size: $(du -sh "$MODEL_DIR" | cut -f1)"