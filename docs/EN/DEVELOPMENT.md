# Development

## Layout

```
rom/            the ROM (C). rom/romfs is a development romfs
prebuilt/       the generic ROM used by the build tool (mediaplayer.elf)
tool/mkcia/     the build tool (Python) and GUI
tool/tests/     tests
scripts/        build and run scripts
template/       templates (only `example` is committed)
out/            generated CIAs (not committed)
docs/           documentation
```

## Using only the build tool

`prebuilt/mediaplayer.elf` is included, so you do not need to build the ROM. You need Python 3, ffmpeg/ffprobe (with libx264),
makerom, bannertool and 3dstool.

```bash
scripts/setup-tools.sh        # builds bannertool, 3dstool and makerom into tools/bin/ (needs git, make, cmake, g++, libssl-dev)
```

The sources are pinned to known-good revisions (commits/tags). `makerom` is not built if one is already on `PATH` or in `tools/bin/`.
External tools are searched in `MKCIA_TOOLS_DIR` → `tools/bin/` → `PATH`.

## Building the ROM

Built through Docker (`devkitpro/devkitarm`); devkitPro is not needed on the host.

```bash
scripts/build-ffmpeg.sh       # cross-build the minimal ARM FFmpeg into deps/ffmpeg-3ds/ (once, a few minutes)
scripts/make-prebuilt.sh      # build the ROM and refresh prebuilt/mediaplayer.elf (debug info stripped)
scripts/build-rom.sh          # build only rom/mediaplayer.3dsx (for emulator checks)
scripts/build-rom.sh EXTRA_CFLAGS=-DDEBUG_LOG   # debug build that writes mediaplayer.log to the SD card
```

- After changing `rom/romfs/`, run `scripts/build-rom.sh clean` before building again (the romfs is not a tracked dependency).
- FFmpeg 4.4.6 is used: 6.x adds about 17 MB of memory (BSS) for the AAC FFT tables alone.

## Tests

```bash
cd tool && python3 -m unittest discover -s tests
```

About 370 tests, about 2 minutes. Tests that need the external tools and `prebuilt/mediaplayer.elf` are skipped automatically
when those are missing. The GUI tests need a display (`DISPLAY`) and are skipped without one (they also run under Xvfb).

| File | Covers |
|---|---|
| `test_meta.py` / `test_meta_edge.py` | meta.json validation (types, lengths, ranges, malformed JSON, BOM, ...) |
| `test_template.py` | Template layout (missing/empty files, links, extensions) |
| `test_media.py` | Broken or wrong-kind video, image and audio |
| `test_environment.py` | ELF, output path and external-tool checks |
| `test_cli.py` / `test_resolution.py` | CLI exit codes, template-name resolution, preset/output precedence |
| `test_cancel.py` | Cancelling external commands |
| `test_gui_model.py` / `test_gui.py` | GUI logic / driving the real Tk window |
| `test_scaffold.py` | Template scaffolding (`--new`): copying, avoiding title-ID collisions, leaving nothing behind on failure, builds right away |
| `test_e2e.py` | Builds real CIAs (odd input formats, Japanese titles, leaving the output intact on failure, fps, aspect ratio) |

The end-to-end tests are slow because makerom compresses the ELF code (about 8 s each); the tests skip it with `compress_code=False`.

## CI (GitHub Actions)

`.github/workflows/ci.yml`:

- `unit`: runs the tests without any external tools on Python 3.9 / 3.12 / 3.13 (this guarantees that the tool-dependent tests are skipped, not failed).
- `full`: on Ubuntu, sets up all the tools (`scripts/setup-tools.sh`) and a virtual display (xvfb), runs every test, and builds a CIA from
  `template/example`. The resulting `Example.cia` is kept as an artifact.
- `release`: when a `v*` tag is pushed, attaches `Example.cia` to the Release (creating it if needed).

```bash
git tag v1.0.0 && git push github v1.0.0     # Example.cia gets attached to the Release
```

The workflow can be checked with `actionlint`, and the steps of `full` can be reproduced in a clean Docker container (ubuntu:24.04).

## Checking on an emulator

`scripts/run-emu.sh` starts an Azahar-family emulator on a virtual display (Xvfb) and takes screenshots.

```bash
AZAHAR=/path/to/azahar scripts/run-emu.sh start rom/mediaplayer.3dsx
scripts/run-emu.sh shot /tmp/shot.png
scripts/run-emu.sh stop
```

- A `.cia` asks to be installed the first time.
- For audio, put a dummy file (e.g. zero-filled) at `3ds/dspfirm.cdc` in the emulator's SD area so that `ndspInit` succeeds with the HLE DSP.
  Without it, audio is disabled and only the video plays.
- **Emulators do not check a CIA's permissions (RSF) or memory map.** Working on an emulator does not mean working on hardware —
  test on a real console. If you have a CIA known to work, comparing ExHeaders is the most reliable check.
- When checking screenshots, look at several taken some time apart and make sure they show different scenes, not just that one
  looks right (an early bug froze the video on its first frame and went unnoticed).

## History and pitfalls

The investigation log, dead ends and open issues are in [HISTORY.md](../../HISTORY.md) (Japanese). The main pitfalls:

- The main thread's 32 KB default stack (libctru) overflows during H.264 decoding. The symptom is "it hangs in decoding".
- citro2d reads a `Tex3DS_SubTexture` with `top < bottom` as a 90°-rotated image. Use `top > bottom`.
- Passing `romfs:/...` to FFmpeg fails because it is parsed as a protocol name. Use `file:romfs:/...`.
- Missing RSF permissions crash only on real hardware, right after launch. makerom's file-system permission names change between
  versions (e.g. `TwlCardBackup`).
- Measure an external tool's limits (ranges, lengths) instead of trusting memory before adding them to the validation
  (e.g. the title-ID limit 0xFFFFF).
