#!/bin/bash
# 生成ツールが使う外部ツール (bannertool / 3dstool / makerom) をソースからビルドして tools/bin/ に置く。
# ソースは動作確認した版 (コミット/タグ) に固定してある。ffmpeg / ffprobe (libx264 付き) は別途 PATH 上に必要。
# 依存: git, make, cmake, g++ (または clang), libssl-dev
# makerom は PATH 上や tools/bin/ に既にあればビルドしない。
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=tools/src; BIN=tools/bin
mkdir -p "$SRC" "$BIN"

# 動作確認した版
BANNERTOOL_REF=51dac927a4c43de769900d91fd3cb6142295263f   # Epicpkmn11/bannertool
TOOL3DS_REF=3771ae967d64092370b646db86aa626401c279e8      # dnasdw/3dstool
MAKEROM_REF=makerom-v0.19.0                               # 3DSGuy/Project_CTR

# URL の指定した版 (コミット or タグ) だけを浅く取得して dir に展開する
fetch_at() {
    local url=$1 dir=$2 ref=$3
    [ -d "$dir/.git" ] || { rm -rf "$dir"; git init -q "$dir"; git -C "$dir" remote add origin "$url"; }
    git -C "$dir" fetch -q --depth 1 origin "$ref"
    git -C "$dir" -c advice.detachedHead=false checkout -q FETCH_HEAD
}

if [ ! -x "$BIN/bannertool" ]; then
    fetch_at https://github.com/Epicpkmn11/bannertool.git "$SRC/bannertool" "$BANNERTOOL_REF"
    # submodule (buildtools) の URL が git:// で、環境によってはタイムアウトするので https に読み替える
    git -C "$SRC/bannertool" -c url."https://github.com/".insteadOf=git://github.com/ \
        submodule update --init --recursive --depth 1
    # 既定の make は配布用の zip まで作ろうとして、zip が無い環境で失敗する。必要なのはバイナリだけ
    make -C "$SRC/bannertool" -j"$(nproc)" output/linux-x86_64/bannertool
    cp "$SRC/bannertool/output/linux-x86_64/bannertool" "$BIN/"
fi

if [ ! -x "$BIN/3dstool" ]; then
    fetch_at https://github.com/dnasdw/3dstool.git "$SRC/3dstool" "$TOOL3DS_REF"
    mkdir -p "$SRC/3dstool-build"
    (cd "$SRC/3dstool-build" && cmake ../3dstool -DCMAKE_BUILD_TYPE=Release >/dev/null && make -j"$(nproc)")
    cp "$SRC/3dstool/bin/Release/3dstool" "$BIN/"
fi

if [ ! -x "$BIN/makerom" ] && ! command -v makerom >/dev/null 2>&1; then
    fetch_at https://github.com/3DSGuy/Project_CTR.git "$SRC/Project_CTR" "$MAKEROM_REF"
    make -C "$SRC/Project_CTR/makerom" deps -j"$(nproc)"
    make -C "$SRC/Project_CTR/makerom" -j"$(nproc)"
    cp "$SRC/Project_CTR/makerom/bin/makerom" "$BIN/"
fi
ls -la "$BIN"
