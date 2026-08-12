#!/bin/bash
# 全Release(dataset_*.zip)をダウンロードし、学習用ディレクトリに統合する。
set -e

MERGED_DIR="/workspace/merged_dataset"
mkdir -p "${MERGED_DIR}/ops" "${MERGED_DIR}/rendered"

cd /workspace/repo/dataset_gen

TOTAL=0
while IFS= read -r url; do
  echo "downloading: ${url}"
  fname=$(basename "${url}")
  wget -q "${url}" -O "/tmp/${fname}" || { echo "  failed to download ${fname}, skipping"; continue; }

  unzip -oq "/tmp/${fname}" -d "/tmp/extract_${fname%.zip}" || { echo "  failed to unzip ${fname}, skipping"; rm -f "/tmp/${fname}"; continue; }

  # ops, rendered ディレクトリをマージ先にコピー(重複しないようprefixをつける)
  prefix="${fname%.zip}"
  if [ -d "/tmp/extract_${prefix}/ops" ]; then
    for f in /tmp/extract_${prefix}/ops/*; do
      cp "$f" "${MERGED_DIR}/ops/${prefix}_$(basename $f)" 2>/dev/null || true
    done
  fi
  if [ -d "/tmp/extract_${prefix}/rendered" ]; then
    for d in /tmp/extract_${prefix}/rendered/*/; do
      idx=$(basename "$d")
      mkdir -p "${MERGED_DIR}/rendered/${prefix}_${idx}"
      cp -r "$d"/* "${MERGED_DIR}/rendered/${prefix}_${idx}/" 2>/dev/null || true
    done
  fi

  rm -f "/tmp/${fname}"
  rm -rf "/tmp/extract_${prefix}"

  count=$(find "${MERGED_DIR}/rendered" -maxdepth 1 -type d | wc -l)
  echo "  merged so far: ${count} samples"
done < release_urls.txt

FINAL_COUNT=$(find "${MERGED_DIR}/rendered" -name "mesh.glb" | wc -l)
echo "=== MERGE DONE: ${FINAL_COUNT} samples in ${MERGED_DIR} ==="
