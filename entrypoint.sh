#!/usr/bin/env bash
# Reassemble sharded model files from chunks on first start.
# If MODEL_DIR is a mounted volume, the reassembly happens once
# and persists across container restarts.
set -euo pipefail

cd /model

# Helper: reassemble one file from its chunks
assemble() {
  local src="$1"   # e.g. "model-00001-of-00014.safetensors"
  local dst="$2"   # e.g. "/vols/model/model-00001-of-00014.safetensors"
  if [ -f "$dst" ]; then
    echo "[entrypoint] $dst already exists, skipping"
    return 0
  fi
  echo "[entrypoint] assembling $dst from chunks..."
  local safe="${src//\//_}"
  local prefix="/model/chunks/${safe}.part"
  # cat preserves byte order; parts are zero-padded
  cat "${prefix}"* > "$dst.tmp"
  mv "$dst.tmp" "$dst"
  echo "[entrypoint] done: $dst"
}

main() {
  mkdir -p "$MODEL_DIR"
  # Read manifest and reassemble every source file
  python3 - <<'PY'
import json, os, subprocess, sys
m = json.load(open('/model/manifest.json'))
files = sorted({c['source_file'] for c in m['chunks']})
for f in files:
    dst = os.path.join(os.environ['MODEL_DIR'], f)
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    if os.path.exists(dst):
        print(f'skip {dst}', flush=True)
        continue
    safe = f.replace('/', '_')
    parts = sorted(p for p in os.listdir('/model/chunks') if p.startswith(safe + '.part'))
    cmd = ['cat'] + [f'/model/chunks/{p}' for p in parts]
    print(f'assemble {dst} from {len(parts)} parts', flush=True)
    with open(dst + '.tmp', 'wb') as out:
        subprocess.run(cmd, stdout=out, check=True)
    os.rename(dst + '.tmp', dst)
PY
}

# Run reassembly, then hand off to the real command
main
exec "$@"
