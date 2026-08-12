#!/bin/bash
# 各Releaseをダウンロードし、展開するだけ(cpによる再コピーをしない)。
# これにより、大量ファイルのコピーでポッドがハングする問題を回避する。
set -e

DATASET_ROOT="/workspace/dataset_root"
mkdir -p "${DATASET_ROOT}"

cd /workspace/repo/dataset_gen

count=0
while IFS= read -r url; do
  fname=$(basename "${url}")
  release_id="${fname%.zip}"
  target_dir="${DATASET_ROOT}/${release_id}"

  if [ -d "${target_dir}" ]; then
    echo "already extracted: ${release_id}, skipping"
    continue
  fi

  echo "downloading: ${url}"
  wget -q "${url}" -O "/tmp/${fname}" || { echo "  failed to download ${fname}, skipping"; continue; }

  mkdir -p "${target_dir}"
  unzip -oq "/tmp/${fname}" -d "${target_dir}" || { echo "  failed to unzip ${fname}, skipping"; rm -f "/tmp/${fname}"; continue; }

  rm -f "/tmp/${fname}"
  count=$((count+1))
  echo "  extracted ${release_id} (${count} done)"
done < release_urls.txt

echo "=== PREP DONE: ${count} releases extracted to ${DATASET_ROOT} ==="
