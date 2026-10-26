# Third-party notices / サードパーティについて

This project's own code is under the MIT License (see `LICENSE`).
It builds on, and the prebuilt ROM binary contains, the following third-party software.
This file is informational and is not legal advice.

本プロジェクト自身のコードは MIT ライセンスです (`LICENSE`)。以下のソフトウェアを利用しており、
事前ビルド済みの ROM (`prebuilt/mediaplayer.elf`) には一部が静的に組み込まれています。
このファイルは情報提供であり、法的助言ではありません。

## Linked into `prebuilt/mediaplayer.elf`

| Component | License | Notes |
|---|---|---|
| [FFmpeg](https://ffmpeg.org/) 4.4.6 (libavformat, libavcodec, libavutil, libswresample) | **LGPL v2.1 or later** | Built by `scripts/build-ffmpeg.sh` **without** `--enable-gpl` / `--enable-nonfree`. Only the H.264 and AAC decoders, the MOV/H.264 demuxers and the `file` protocol are enabled. Statically linked into the ROM. |
| [libctru](https://github.com/devkitPro/libctru), [citro2d / citro3d](https://github.com/devkitPro/citro2d) | zlib license | Provided by devkitPro (`devkitpro/devkitarm` image). |
| [devkitARM](https://devkitpro.org/) toolchain / newlib | various permissive licenses | C runtime linked into the ROM. |
| libpng, zlib | libpng license, zlib license | From devkitPro portlibs. |

### How to rebuild / relink the ROM (LGPL)

The ROM source (`rom/`) and the build scripts are in this repository under MIT, so the ROM can be relinked
against a modified FFmpeg:

```bash
scripts/build-ffmpeg.sh      # downloads the FFmpeg 4.4.6 source from ffmpeg.org and builds LGPL static libs
scripts/make-prebuilt.sh     # rebuilds the ROM and replaces prebuilt/mediaplayer.elf
```

FFmpeg source: <https://ffmpeg.org/releases/ffmpeg-4.4.6.tar.xz>. The exact `configure` options are in
`scripts/build-ffmpeg.sh`.

FFmpeg のソースは上記から取得し、`configure` のオプションは `scripts/build-ffmpeg.sh` にあります。
ROM のソースとビルドスクリプトが本リポジトリにあるので、FFmpeg を差し替えて再リンクできます。

## Used at build time, not bundled / ビルド時に使うが同梱しないもの

- **ffmpeg / ffprobe** on your PC (with libx264) — encodes your video. The encoded output is your own data.
- **makerom** ([Project_CTR](https://github.com/3DSGuy/Project_CTR)), **bannertool**, **3dstool** — external tools.
  `scripts/setup-tools.sh` builds all three from their upstream sources (pinned revisions); check each project's license.
- **Docker** image `devkitpro/devkitarm` — only needed to rebuild the ROM.

## Ideas and references / 参考にしたもの

- [3Damnesic](https://github.com/Lectem/3Damnesic): the approach for building a minimal FFmpeg for the 3DS and
  for using the Y2R hardware converter. No code was copied.

## Sample data / サンプルデータ

`template/example/` and `rom/romfs/` contain only synthetic test patterns generated with FFmpeg's `lavfi`
sources (no third-party content). The default title-select sound (`tool/mkcia/default_select_sound.wav`) is a chime synthesised
from sine waves by `scripts/make-default-sound.sh` (no third-party audio); it is covered by this project's MIT license.

## Not distributed / 同梱しないもの

- The 3DS DSP firmware (`dspfirm.cdc`). Audio on a real console needs it; dump it from your own console.
- Any Nintendo software, keys or firmware.
