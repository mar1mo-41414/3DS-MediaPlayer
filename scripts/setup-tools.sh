#!/bin/bash
# 生成ツールが使う外部ツール (bannertool / 3dstool / makerom) をソースからビルドして tools/bin/ に置く。
# ソースは動作確認した版 (コミット/タグ) に固定してある。ffmpeg / ffprobe (libx264 付き) は別途 PATH 上に必要。
# 依存: git, make, cmake, g++ (または clang), libssl-dev, python3
# 対応: x86_64 / arm64 の Linux (arm64 は QEMU 上のコンテナでの確認)。macOS も同じ手順 (Apple Silicon は実機で未確認 -> HISTORY.md)。
# makerom は PATH 上や tools/bin/ に既にあればビルドしない。
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=tools/src; BIN=tools/bin
mkdir -p "$SRC" "$BIN"
JOBS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)   # macOS には nproc が無い

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
    # 上流の buildtools (make_base) は x86_64 / i686 のホストしか受け付けず、arm64 (Apple Silicon や arm64 Linux) では
    # "Unsupported host architecture." で止まる。ネイティブビルドはコンパイラ任せなので、arm64 / aarch64 を受け付けるように直す。
    python3 - "$SRC/bannertool/buildtools/make_base" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
old = """    else ifeq ($(UNAME_M),$(filter $(UNAME_M),i386 i686))
        HOST_ARCH := i686
    else
        $(error "Unsupported host architecture.")"""
new = """    else ifeq ($(UNAME_M),$(filter $(UNAME_M),i386 i686))
        HOST_ARCH := i686
    else ifeq ($(UNAME_M),$(filter $(UNAME_M),arm64 aarch64))
        HOST_ARCH := aarch64
    else
        $(error "Unsupported host architecture.")"""
if "arm64 aarch64" not in s:
    if old not in s:
        sys.exit("make_base の形が想定と違うので、arm64 対応の修正を当てられません")
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
PY
    case "$(uname -s)" in Darwin) bt_os=mac ;; *) bt_os=linux ;; esac
    case "$(uname -m)" in arm64|aarch64) bt_arch=aarch64 ;; i386|i686) bt_arch=i686 ;; *) bt_arch=x86_64 ;; esac
    # 既定の make は配布用の zip まで作ろうとして、zip が無い環境で失敗する。必要なのはバイナリだけ
    make -C "$SRC/bannertool" -j"$JOBS" "output/$bt_os-$bt_arch/bannertool"
    cp "$SRC/bannertool/output/$bt_os-$bt_arch/bannertool" "$BIN/"
fi

if [ ! -x "$BIN/3dstool" ]; then
    fetch_at https://github.com/dnasdw/3dstool.git "$SRC/3dstool" "$TOOL3DS_REF"
    cmake_args=(-DCMAKE_BUILD_TYPE=Release)
    case "$(uname -m)" in
        arm64|aarch64)
            # 同梱の事前ビルド済みライブラリ (dep/lib) は x86 用なので使わず、システムの OpenSSL / libcurl を使う
            # (Debian/Ubuntu: libssl-dev libcurl4-openssl-dev)。また CMakeLists が固定で付ける -m64 は arm64 のコンパイラが受け付けない
            cmake_args+=(-DUSE_DEP=OFF)
            python3 - "$SRC/3dstool/CMakeLists.txt" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
old = """  if((UNIX AND BUILD64) OR (MINGW AND CMAKE_SIZEOF_VOID_P EQUAL 8))
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -m64")"""
new = """  if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(arm64|aarch64)$")
    # arm64: -m64 / -m32 は無い。コンパイラ任せにする
  elseif((UNIX AND BUILD64) OR (MINGW AND CMAKE_SIZEOF_VOID_P EQUAL 8))
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -m64")"""
if "arm64|aarch64" not in s:
    if old not in s:
        sys.exit("3dstool の CMakeLists.txt の形が想定と違うので、arm64 対応の修正を当てられません")
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
PY
            ;;
    esac
    # OpenSSL (3dstool が必要とする) の場所。OPENSSL_ROOT_DIR の指定 > Homebrew の openssl@3 > システム標準 (Linux の libssl-dev)
    ssl_root=${OPENSSL_ROOT_DIR:-}
    if [ -z "$ssl_root" ]; then
        # ssh 越しなどの非ログインシェルでは Homebrew が PATH に無いことがあるので、標準の場所も見る
        for brew in "$(command -v brew 2>/dev/null || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
            if [ -n "$brew" ] && [ -x "$brew" ]; then
                ssl_root=$("$brew" --prefix openssl@3 2>/dev/null || true)
                break
            fi
        done
    fi
    if [ -n "$ssl_root" ] && [ -f "$ssl_root/include/openssl/sha.h" ]; then
        cmake_args+=("-DCMAKE_C_FLAGS=-I$ssl_root/include" "-DCMAKE_CXX_FLAGS=-I$ssl_root/include" "-DCMAKE_EXE_LINKER_FLAGS=-L$ssl_root/lib")
    elif [ "$(uname -s)" = Darwin ]; then
        echo "エラー: OpenSSL のヘッダが見つかりません (macOS には標準で入っていません)。" >&2
        echo "  brew install openssl@3 するか、OPENSSL_ROOT_DIR=<OpenSSL のインストール先> を付けて再実行してください。" >&2
        exit 1
    fi
    mkdir -p "$SRC/3dstool-build"
    (cd "$SRC/3dstool-build" && cmake ../3dstool "${cmake_args[@]}" >/dev/null && make -j"$JOBS")
    cp "$SRC/3dstool/bin/Release/3dstool" "$BIN/"
fi

if [ ! -x "$BIN/makerom" ] && ! command -v makerom >/dev/null 2>&1; then
    fetch_at https://github.com/3DSGuy/Project_CTR.git "$SRC/Project_CTR" "$MAKEROM_REF"
    make -C "$SRC/Project_CTR/makerom" deps -j"$JOBS"
    make -C "$SRC/Project_CTR/makerom" -j"$JOBS"
    cp "$SRC/Project_CTR/makerom/bin/makerom" "$BIN/"
fi
ls -la "$BIN"
