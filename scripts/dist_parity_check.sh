#!/usr/bin/env bash
set -euo pipefail

# Parity check script to sha256sum all generated dist outputs:
# frontend/www/js/dist, frontend/www/css/dist, and frontend/www/media/dist
# including *.deps.json manifest files.

TARGET_DIR="${1:-frontend/www}"
OUT_FILE="${2:-dist_checksums.sha256}"

if command -v sha256sum >/dev/null 2>&1; then
  HASH_CMD="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  HASH_CMD="shasum -a 256"
else
  echo "Error: neither sha256sum nor shasum is available" >&2
  exit 1
fi

DIRS=()
for d in "${TARGET_DIR}/js/dist" "${TARGET_DIR}/css/dist" "${TARGET_DIR}/media/dist"; do
  if [ -d "$d" ]; then
    DIRS+=("$d")
  fi
done

if [ ${#DIRS[@]} -eq 0 ]; then
  echo "Error: No dist directories found under ${TARGET_DIR}" >&2
  exit 1
fi

echo "Computing SHA-256 for all dist outputs in ${TARGET_DIR}..."
find "${DIRS[@]}" -type f | LC_ALL=C sort | xargs "$HASH_CMD" > "$OUT_FILE"

TOTAL_COUNT=$(wc -l < "$OUT_FILE" | tr -d ' ')
echo "Generated $OUT_FILE with $TOTAL_COUNT hashed files."
