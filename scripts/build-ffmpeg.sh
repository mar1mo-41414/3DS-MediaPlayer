#!/bin/bash
# ARM11(3DS)向け ffmpeg 最小構成を devkitARM コンテナ内でクロスビルドする。
# 使い方: scripts/build-ffmpeg.sh   (ホストから実行。成果物は deps/ffmpeg-3ds/ に出る)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
FFMPEG_VER="${FFMPEG_VER:-4.4.6}"

if [ -z "${IN_CONTAINER:-}" ]; then
    exec docker run --rm --user "$(id -u):$(id -g)" -e IN_CONTAINER=1 -e HOME=/tmp \
        -v "$ROOT":/project -w /project devkitpro/devkitarm:latest bash scripts/build-ffmpeg.sh
fi

export DEVKITPRO=/opt/devkitpro DEVKITARM=/opt/devkitpro/devkitARM
export PATH=$DEVKITARM/bin:$PATH
ARCH="-march=armv6k -mtune=mpcore -mfloat-abi=hard"
PREFIX=/project/deps/ffmpeg-3ds
SRC=/project/deps/src

mkdir -p "$SRC" "$PREFIX"
cd "$SRC"
if [ ! -d "ffmpeg-$FFMPEG_VER" ]; then
    [ -f "ffmpeg-$FFMPEG_VER.tar.xz" ] || curl -fL -o "ffmpeg-$FFMPEG_VER.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz"
    tar xf "ffmpeg-$FFMPEG_VER.tar.xz"
fi
cd "ffmpeg-$FFMPEG_VER"

# 再生に必要な分だけ: mov(mp4) demux + h264/aac decode + swresample(fltp->s16)。
# 映像の色変換は Y2R(HW) が担当するので swscale/avfilter は不要。
./configure --prefix="$PREFIX" \
  --enable-cross-compile --cross-prefix=$DEVKITARM/bin/arm-none-eabi- \
  --disable-shared --enable-static --enable-small \
  --disable-runtime-cpudetect --disable-armv5te --disable-armv6t2 --disable-neon \
  --disable-programs --disable-doc --disable-everything \
  --disable-pthreads --disable-w32threads --disable-os2threads --disable-avdevice --disable-avfilter --disable-swscale --disable-network \
  --disable-bzlib --disable-iconv --disable-lzma --disable-sdl2 --disable-securetransport --disable-xlib --disable-zlib \
  --enable-decoder=h264,aac --enable-parser=h264,aac \
  --enable-demuxer=mov,h264 --enable-protocol=file \
  --arch=armv6k --cpu=mpcore --target-os=none \
  --extra-cflags="-Wno-error=incompatible-pointer-types -Wno-error=int-conversion -DARM11 -D_3DS -mword-relocations -fomit-frame-pointer -ffast-math $ARCH" \
  --extra-ldflags="-specs=3dsx.specs $ARCH -L$DEVKITARM/lib -L$DEVKITPRO/libctru/lib -lctru"

make -j"$(nproc)"
make install
echo "== done: $PREFIX"
ls -la "$PREFIX/lib"
