#!/bin/bash
# ROM 本体を (デバッグログ無しで) クリーンビルドし、生成ツールが使う汎用 ELF を prebuilt/ に置く。
# 前提: scripts/build-ffmpeg.sh 実行済み。
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/build-rom.sh clean >/dev/null
scripts/build-rom.sh
mkdir -p prebuilt
# デバッグ情報は prebuilt には不要 (リポジトリに置くので小さくする)
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/project -w /project \
    devkitpro/devkitarm:latest /opt/devkitpro/devkitARM/bin/arm-none-eabi-strip \
    --strip-debug -o prebuilt/mediaplayer.elf rom/mediaplayer.elf
ls -la prebuilt/mediaplayer.elf
