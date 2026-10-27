# Usage (CLI / GUI)

The detailed version of the README's quick start.

## Template

A template is one directory holding the video, images, sound and settings. Put it in `template/<name>/` and
refer to it by name (everything under `template/` except `example` is ignored by git).

```
template/<name>/
├── video.mp4          source video (any format/resolution; re-encoded for the 3DS. mkv/mov/avi/webm/m4v also work)
├── icon.png           HOME Menu icon (optional; resized to 48x48; jpg/bmp/webp/gif also work)
├── bottom.png         still image for the bottom screen (optional; resized to 320x240; same formats)
├── select_sound.wav   sound played when the icon is selected (optional; the default sound if absent; mp3/ogg/flac/m4a/aac also work;
│                      the first 3 seconds are used, with a short fade-out)
├── banner.png         banner image (optional; generated from icon.png if absent)
└── meta.json
```

Any of the listed extensions is accepted and the content only has to be readable by ffmpeg (a file whose extension
does not match its content is fine). If several files of one kind exist, the first extension in the order above wins.
Only `meta.json` and the video are required.

### When select_sound is missing (the default sound)

Without `select_sound.*`, the sound played when the icon is selected in the HOME Menu is a **default sound** (a short two-note chime,
synthesised for this project: `tool/mkcia/default_select_sound.wav`; regenerate it with `scripts/make-default-sound.sh`). Many homebrew apps
simply reuse a default sound instead of shipping their own. Put a `select_sound.*` in the template to use your own.

**To make it silent, put a silent audio file in as `select_sound.wav`** (when the file is absent the default sound plays). A broken
`select_sound.*` is an error and is not silently replaced by the default. Templates made with `--new` start without a `select_sound`
(= the default sound).

### When icon / bottom are missing (made from the video)

If `icon.*` or `bottom.*` is missing, the build makes the image from the video. Files that exist are used as they are (never replaced).

1. If the video has an **embedded image** (an attachment in an mkv, cover art in an mp4, ... anything ffmpeg recognises as an image;
   names containing `cover` come first), that image is used. An unreadable embedded image is ignored.
2. Otherwise a **frame from the middle of the video** is used. `frame_at` (below) chooses the second; by default it is at 15 % of
   the duration (at most 30 s, to avoid a dark intro or a logo).

An explicit `frame_at` is honoured even when an embedded image exists. Rotated and non-square-pixel videos are corrected.
The icon is a centre square crop of the image; the bottom image and the banner keep the aspect ratio with margins.
If only one of `icon` / `bottom` is missing, only that one is made.

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
| `frame_at` | no | Second of the video to take the frame from when icon / bottom are missing (0 or more, less than the duration; default: the embedded image, else 15 % of the duration) |
| `output` | no | Output file name (`.cia` optional; no directories or `<>:"/\|?*`; default `<template name>.cia`) |

Two CIAs with the same title ID overwrite each other when installed, so give every app its own ID.

## Presets

You cannot pick values above these limits (the 3DS CPU could not keep up).

| preset | Resolution | fps | Video | Audio | Target |
|---|---|---|---|---|---|
| `light` | 320x192 (the ROM scales it to full screen) | 20 | 250 kbps | AAC 48 kbps / 32 kHz | Old 3DS, with headroom (verified on an Old 3DS) |
| `medium` (default) | 360x216 (same) | 20 | 400 kbps | AAC 48 kbps / 32 kHz | Old 3DS, recommended (verified on an Old 3DS) |
| `high` | 400x240 | 20 | 400 kbps | AAC 48 kbps / 32 kHz | New 3DS (**untested on a New 3DS**; on an Old 3DS the audio can sound slightly stretched) |
| `standard` | 400x240 | 24 | 350 kbps | AAC 64 kbps / 32 kHz | New 3DS (**untested on a New 3DS**) |

On a real Old 3DS `light` and `medium` are smooth. `high` plays, but decoding barely keeps up with real time and the
audio can sound slightly stretched.
No preset has been tested on a real New 3DS (it uses the extra application core for decoding, which has not been tried yet).

## CLI

```bash
scripts/mkcia.sh --new MyMovie            # copy template/example to template/MyMovie (see below)
scripts/mkcia.sh MyMovie                  # template/MyMovie -> out/<output>.cia
scripts/mkcia.sh --list                   # list the templates under template/
scripts/mkcia.sh MyMovie --preset light   # override meta.json's preset for this run
scripts/mkcia.sh MyMovie --frame-at 45    # if icon/bottom are missing, make them from the frame at 45 s
scripts/mkcia.sh MyMovie --output-dir ~/Downloads
scripts/mkcia.sh path/to/dir -o /tmp/x.cia   # a path works too (-o names the output file directly)
```

- Precedence: command line > meta.json > defaults.
- If the argument is both a path and a template name, the one containing `meta.json` is used (the path if both do).
- The default output directory is `out/`.
- `--new NAME`: copies `template/example` to `template/NAME` (without its title sound, so the default sound is used), sets `title` to `NAME` and `title_id` to a valid value that does not
  collide with other templates (the example's `long_title` and `output` are not carried over). The copy builds right away, so you can
  replace the assets and `meta.json` step by step. It fails for a duplicate or invalid name, or if `template/example` is missing.
- `--frame-at SEC`: second of the video to take the frame from when icon / bottom are missing (overrides `frame_at` in `meta.json`).
- Options: `--elf` (ROM ELF), `--keep-work DIR` (keep intermediate files), `--no-compress` (skip compressing the ELF
  code: ~8 s faster, CIA ~0.7 MB larger; mostly for tests), `--debug` (print a traceback on unexpected errors).
- Exit codes: `0` success / `1` a problem with the input that you can fix / `2` unexpected error / `130` interrupted.

### Input validation

Before any heavy work (encoding), everything below is checked and a problem is reported as "which file, what is wrong"
(raw ffmpeg logs are not shown).

- The external tools (ffmpeg / ffprobe / bannertool / 3dstool / makerom) exist, and ffmpeg has libx264 and aac.
- The ROM ELF is a 32-bit ARM ELF.
- The required template files (`meta.json` and the video) exist; the files that exist are not empty or directories, and are readable.
  `frame_at` is within the video (only when icon / bottom are missing).
- `meta.json`: JSON syntax, types, lengths, value ranges (title ID range, version range, characters not allowed in `output`, ...).
- The video has a video stream and is at least 0.5 s long; the images and audio can be read; the CIA stays under
  4 GB (the FAT32 limit).
- The output ends in `.cia`, is writable, and does not overwrite an input file.

The output is written to a temporary file in the same directory and then moved into place, so a failure never
damages an existing output.

## GUI

```bash
scripts/mkcia-gui.sh          # Tkinter GUI (needs a Python with tkinter, see below)
PYTHON=python3.14 scripts/mkcia-gui.sh   # run it with another Python (the same variable works for mkcia.sh)
```

Installing tkinter (if the script says it is missing; the message names the Python it used):

- Debian/Ubuntu: `sudo apt install python3-tk` (Fedora: `sudo dnf install python3-tkinter`)
- macOS (Homebrew): `brew install python-tk@3.X`, where 3.X is the version of the `python3` you run (`python3 --version`).
  Homebrew's Python does not include tkinter by itself. Apple's `/usr/bin/python3` has an old Tk 8.5 (not recommended).
- Windows: tcl/tk is included by python.org's installer by default.

- Choose or create a template (a new one gets an automatically assigned title ID), edit the basic info, replace
  assets (with thumbnails and details), set preset / loop / volume / output name / output folder, and validate,
  build or cancel — all in one window. It calls the same code as the CLI.
- "Choose…" on an asset validates the file before copying it into the template (a broken file is rejected and the
  template is left unchanged; older files with another extension are removed).
- Fields are validated as you type, and problems show in red. A warning appears if another template uses the same title ID.
- "Build" and "Validate" save `meta.json` first. Switching templates or closing with unsaved changes asks first.
- The build runs in a worker thread with a progress bar and a log. "Cancel" stops the external commands (and leaves no
  temporary files). Command lines are hidden from the log unless "show commands" is ticked.

## Windows

The tool is plain Python, so it runs on Windows (64-bit) as well. Install Python 3 from python.org (tick "tcl/tk" if you want the GUI;
the installer includes it by default), then, from a clone of this repository:

```bat
REM once: download makerom, bannertool, 3dstool and ffmpeg into tools\bin\
powershell -ExecutionPolicy Bypass -File scripts\setup-tools.ps1

REM build the sample -> out\Example.cia
scripts\mkcia.cmd example

REM your own template, and the GUI
scripts\mkcia.cmd --new MyMovie
scripts\mkcia.cmd MyMovie
scripts\mkcia-gui.cmd
```


- `scripts\mkcia.cmd` / `scripts\mkcia-gui.cmd` are the Windows counterparts of `mkcia.sh` / `mkcia-gui.sh` (same arguments). They use the
  `py` launcher if there is one, otherwise `python` (the "python" stub that opens the Microsoft Store does not work; install Python or use `py`).
- `setup-tools.ps1` fetches released binaries of known-good versions (`ffmpeg` is skipped if it is already on `PATH`; the essentials build of
  [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) includes libx264 and aac). To use tools you already have, put them on `PATH` or in
  a directory named by `MKCIA_TOOLS_DIR`.
- Spaces and non-ASCII characters in the template name, output name and output folder are fine (`makerom` never writes to the output folder;
  the CIA is built in a work folder and copied). `makerom` and the other tools read their *input* paths in the system code page, though,
  so keep this repository (and `%TEMP%`) in a folder whose name the code page can represent — plain ASCII is safest.
  Output files get normal permissions inherited from the folder.
- Not available on Windows: the shell scripts for building the ROM (`build-rom.sh` and friends, which need Docker/devkitPro and are only
  for developing the ROM itself).

## macOS / arm64

The same `scripts/setup-tools.sh` / `scripts/mkcia.sh` work on **arm64 Linux** and **Apple-Silicon macOS**. The upstream build files of
`bannertool` and `3dstool` only know x86, so the script patches them right after fetching (arm64 hosts accepted; the x86-only prebuilt
libraries of `3dstool` are not used, and the system OpenSSL / libcurl are used instead).

- Debian/Ubuntu arm64: `sudo apt install git make cmake g++ libssl-dev libcurl4-openssl-dev ffmpeg python3`
- macOS: `brew install cmake openssl@3 ffmpeg` (the script finds Homebrew's `openssl@3` itself, even from a non-login shell such as ssh; otherwise
  pass `OPENSSL_ROOT_DIR=<prefix>`). macOS does not ship OpenSSL headers, so without one the script stops with a message.
  The GUI needs `python3 -m tkinter` to work (Homebrew: `brew install python-tk@3.X` for your Python's version, see [GUI](#gui)).
- Verified: the three tools build, `example` builds, and the whole test suite passes (GUI tests skipped, no display) on arm64 Ubuntu and on an M4 Mac;
  the CIA's ExHeader and ExeFS are byte-identical to the ones built on x86_64 Linux. Not verified: the GUI on macOS, and playing a CIA built there on a console.

## Controls (on the 3DS)

- **START**: quit at any time and return to the HOME Menu.
- With `loop` false, the video plays to the end, both screens fade out to black over about a second, and the app returns by itself.
  With `true` it repeats until START.
- The HOME button works as on any 3DS (the app does nothing special for it; resuming afterwards is untested).
- There is no volume, pause or seek control.

## On a real console

- Install the CIA with FBI or similar. A CFW console is assumed (the CIA is signed with makerom's default test key).
- Audio uses ndsp, which needs the DSP firmware (`sdmc:/3ds/dspfirm.cdc`) on a real console. It is a standard file dumped during CFW
  setup, so follow your CFW installation guide. Without it only the video plays (it does not fail).
