FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    wget \
    curl \
    xz-utils \
    libxi6 \
    libxrender1 \
    libxfixes3 \
    libxkbcommon0 \
    libgl1 \
    libsm6 \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Blender公式バイナリを導入(apt版は依存関係が壊れやすいため公式tarballを使用)
RUN wget -q https://download.blender.org/release/Blender4.2/blender-4.2.5-linux-x64.tar.xz -O /tmp/blender.tar.xz \
    && tar xf /tmp/blender.tar.xz -C /opt \
    && rm /tmp/blender.tar.xz
ENV PATH="/opt/blender-4.2.5-linux-x64:${PATH}"
ENV BLENDER_BIN="/opt/blender-4.2.5-linux-x64/blender"

RUN pip3 install --no-cache-dir objaverse trimesh numpy

WORKDIR /workspace
COPY dataset_gen/ /workspace/dataset_gen/
RUN chmod +x /workspace/dataset_gen/entrypoint.sh
RUN mkdir -p /workspace/output

# 使い方(Runpod上):
#   env に RUNPOD_API_KEY(再発行した新しいキー)、NUM_SAMPLES、WORKERS を設定してデプロイ
#   コンテナ起動時に entrypoint.sh が自動実行され、
#   生成完了後にポッド自身がAPI経由でTerminateする
ENTRYPOINT ["/workspace/dataset_gen/entrypoint.sh"]
