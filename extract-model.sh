#!/bin/bash
set -e

OWNER="c0d1ac"
MODEL_DIR="/data/qwen-model"
NUM_PARTS=7

mkdir -p "$MODEL_DIR"

echo "Login to GHCR (needs token with read:packages permission)"
echo "Create token at: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens"
read -s -p "Enter GitHub token: " GHCR_TOKEN
echo
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$OWNER" --password-stdin

for i in $(seq 1 $NUM_PARTS); do
    IMAGE="ghcr.io/$OWNER/qwen-part$i:latest"
    CONTAINER="qwen-extract-$i"

    echo "========================================="
    echo "Part $i of $NUM_PARTS"
    echo "========================================="

    echo "Pulling..."
    docker pull "$IMAGE"

    echo "Extracting files..."
    docker create --name "$CONTAINER" "$IMAGE"
    docker cp "$CONTAINER:/model/." "$MODEL_DIR/"
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