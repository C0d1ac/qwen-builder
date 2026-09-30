#!/usr/bin/env bash
set -euo pipefail

OWNER="${OWNER:-c0d1ac}"
IMAGE_PREFIX="ghcr.io/${OWNER}/qwen-flash-fp8-chunk"
MODEL_DIR="${MODEL_DIR:-/data/qwen-model}"
MODEL_FILE="${MODEL_DIR}/model-fp8-mtp-ple.safetensors"
CHUNK_DIR="${MODEL_DIR}/.fp8-chunks"

mkdir -p "$CHUNK_DIR" "$MODEL_DIR"

for index in 0 1 2 3 4 5 6; do
    image="${IMAGE_PREFIX}:${index}"
    container="qwen-fp8-${index}"
    chunk="${CHUNK_DIR}/model-fp8-mtp-ple.safetensors.part$(printf '%03d' "$index")"

    docker pull "$image"
    docker create --name "$container" "$image" >/dev/null
    docker cp "$container:/model/chunks/model-fp8-mtp-ple.safetensors.part$(printf '%03d' "$index")" "$chunk"
    docker rm "$container" >/dev/null
    docker rmi "$image" >/dev/null
done

cat "$CHUNK_DIR"/model-fp8-mtp-ple.safetensors.part* > "${MODEL_FILE}.tmp"
mv "${MODEL_FILE}.tmp" "$MODEL_FILE"
rm -rf "$CHUNK_DIR"

echo "Wrote $MODEL_FILE"
stat -c 'Size: %s bytes' "$MODEL_FILE"