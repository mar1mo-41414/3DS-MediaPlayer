# Usage (CLI / GUI)

The detailed version of the README's quick start.

## Template

A template is one directory holding the video, images, sound and settings. Put it in `template/<name>/` and
refer to it by name (everything under `template/` except `example` is ignored by git).

```
template/<name>/
├── video.mp4          source video (any format/resolution; re-encoded for the 3DS. mkv/mov/avi/webm/m4v also work)
├── icon.png           HOME Menu icon (resized to 48x48; jpg/bmp/webp/gif also work)
├── bottom.png         still image for the bottom screen (resized to 320x240; same formats)
├── select_sound.wav   sound played when the icon is selected (optional; mp3/ogg/flac/m4a/aac also work;
│                      the first 3 seconds are used, with a short fade-out)
├── banner.png         banner image (optional; generated from icon.png if absent)
└── meta.json
```

Any of the listed extensions is accepted and the content only has to be readable by ffmpeg (a file whose extension
does not match its content is fine). If several files of one kind exist, the first extension in the order above wins.

### meta.json

| Key | Required | Meaning |
|---|---|---|
| `title` | yes | Name shown in the HOME Menu (up to 64 characters) |
| `publisher` | yes | Publisher name (up to 64 characters) |
| `title_id` | yes | 16 hex digits, `000400000xxxxx00` (`x` = 5 hex digits; range `0004000000000000`–`000400000FFFFF00`; e.g. `000400000FF3A000`) |
| `version` | yes | `major.minor.micro` (e.g. `1.0.0`; 0-63 / 0-63 / 0-15) |
| `long_title` | no | Long title (up to 128 characters; defaults to `title`) |
| `product_code` | no | `CTR-P-XXXX` (default `CTR-P-MPLY`) |
| `loop` | no | Loop playback (default `false`; if `false` the video plays to the end, fades out to black and returns to the HOME Menu) |
| `volume` | no | Volume 0.0–1.0 (default `1.0`) |
| `preset` | no | Encoding preset name (see below; default `medium`) |
| `output` | no | Output file name (`.cia` optional; no directories or `<>:"/\|?*`; default `<template name>.cia`) |

Two CIAs with the same title ID overwrite each other when installed, so give every app its own ID.

## Presets

You cannot pick values above these limits (the 3DS CPU could not keep up).

| preset | Resolution | fps | Video | Audio | Target |
|---|---|---|---|---|---|
| `light` | 320x192 (the ROM scales it to full screen) | 20 | 250 kbps | AAC 48 kbps / 32 kHz | Old 3DS, with headroom |
| `medium` (default) | 360x216 (same) | 20 | 400 kbps | AAC 48 kbps / 32 kHz | Old 3DS, recommended |
| `high` | 400x240 | 20 | 400 kbps | AAC 48 kbps / 32 kHz | New 3DS |
| `standard` | 400x240 | 24 | 350 kbps | AAC 64 kbps / 32 kHz | New 3DS |

On a real Old 3DS `light` and `medium` are smooth. `high` plays, but decoding barely keeps up with real time and the
audio can sound slightly stretched.

## CLI

```bash
scripts/mkcia.sh MyMovie                  # template/MyMovie -> out/<output>.cia
scripts/mkcia.sh --list                   # list the templates under template/
scripts/mkcia.sh MyMovie --preset light   # override meta.json's preset for this run
scripts/mkcia.sh MyMovie --output-dir ~/Downloads
scripts/mkcia.sh path/to/dir -o /tmp/x.cia   # a path works too (-o names the output file directly)
```

- Precedence: command line > meta.json > defaults.
- If the argument is both a path and a template name, the one containing `meta.json` is used (the path if both do).
- The default output directory is `out/`.
- Options: `--elf` (ROM ELF), `--keep-work DIR` (keep intermediate files), `--no-compress` (skip compressing the ELF
  code: ~8 s faster, CIA ~0.7 MB larger; mostly for tests), `--debug` (print a traceback on unexpected errors).
- Exit codes: `0` success / `1` a problem with the input that you can fix / `2` unexpected error / `130` interrupted.

### Input validation

Before any heavy work (encoding), everything below is checked and a problem is reported as "which file, what is wrong"
(raw ffmpeg logs are not shown).

- The external tools (ffmpeg / ffprobe / bannertool / 3dstool / makerom) exist, and ffmpeg has libx264 and aac.
- The ROM ELF is a 32-bit ARM ELF.
- The template files exist, are not empty or directories, and are readable.
- `meta.json`: JSON syntax, types, lengths, value ranges (title ID range, version range, characters not allowed in `output`, ...).
- The video has a video stream and is at least 0.5 s long; the images and audio can be read; the CIA stays under
  4 GB (the FAT32 limit).
- The output ends in `.cia`, is writable, and does not overwrite an input file.

The output is written to a temporary file in the same directory and then moved into place, so a failure never
damages an existing output.

## GUI

```bash
scripts/mkcia-gui.sh          # Tkinter GUI (needs python3-tk; on Debian/Ubuntu: sudo apt install python3-tk)
```

- Choose or create a template (a new one gets an automatically assigned title ID), edit the basic info, replace
  assets (with thumbnails and details), set preset / loop / volume / output name / output folder, and validate,
  build or cancel — all in one window. It calls the same code as the CLI.
- "Choose…" on an asset validates the file before copying it into the template (a broken file is rejected and the
  template is left unchanged; older files with another extension are removed).
- Fields are validated as you type, and problems show in red. A warning appears if another template uses the same title ID.
- "Build" and "Validate" save `meta.json` first. Switching templates or closing with unsaved changes asks first.
- The build runs in a worker thread with a progress bar and a log. "Cancel" stops the external commands (and leaves no
  temporary files). Command lines are hidden from the log unless "show commands" is ticked.

## On a real console

- Install the CIA with FBI or similar. A CFW console is assumed (the CIA is signed with makerom's default test key).
- Audio uses ndsp, which needs the DSP firmware (`sdmc:/3ds/dspfirm.cdc`) on a real console. Without it only the video plays.
