#!/bin/bash
# 生成ツールが使う外部ツール (bannertool / 3dstool) をソースからビルドして tools/bin/ に置く。
# makerom と ffmpeg/ffprobe は別途 PATH 上に必要 (makerom: https://github.com/3DSGuy/Project_CTR)。
# 依存: git, make, cmake, g++, libssl-dev
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=tools/src; BIN=tools/bin
mkdir -p "$SRC" "$BIN"

if [ ! -x "$BIN/bannertool" ]; then
    [ -d "$SRC/bannertool" ] || git clone -q --depth 1 https://github.com/Epicpkmn11/bannertool.git "$SRC/bannertool"
    # submodule (buildtools) の URL が git:// で、環境によってはタイムアウトするので https に読み替える
    git -C "$SRC/bannertool" -c url."https://github.com/".insteadOf=git://github.com/ \
        submodule update --init --recursive --depth 1
    make -C "$SRC/bannertool" -j"$(nproc)"
    cp "$SRC/bannertool/output/linux-x86_64/bannertool" "$BIN/"
fi

if [ ! -x "$BIN/3dstool" ]; then
    [ -d "$SRC/3dstool" ] || git clone -q --depth 1 https://github.com/dnasdw/3dstool.git "$SRC/3dstool"
    mkdir -p "$SRC/3dstool-build"
    (cd "$SRC/3dstool-build" && cmake ../3dstool -DCMAKE_BUILD_TYPE=Release >/dev/null && make -j"$(nproc)")
    cp "$SRC/3dstool/bin/Release/3dstool" "$BIN/"
fi
ls -la "$BIN"
