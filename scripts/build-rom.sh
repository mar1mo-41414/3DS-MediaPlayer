#!/bin/bash
# ROM 本体 (rom/) を devkitARM コンテナでビルドする。要: scripts/build-ffmpeg.sh 実行済み。
set -euo pipefail
cd "$(dirname "$0")/.."
exec docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/project -w /project/rom \
    devkitpro/devkitarm:latest make "$@"
