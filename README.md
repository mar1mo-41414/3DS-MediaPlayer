# 3DS-MediaPlayer

**English** | [日本語](README.ja.md)

**A video-only app for the Nintendo 3DS (`.cia`), plus a tool that builds it from one video and a few images.**
For 3DS consoles with custom firmware (CFW); install the result with FBI or similar.

- Plays a video on the top screen (H.264 + AAC) and shows any still image you like on the bottom screen.
- Build a `.cia` just by giving a video, an icon, a title, an icon-select sound, and so on — from the CLI or a GUI.
- Video follows the audio position, so it stays in sync. Looping is supported; a non-looping video fades
  out to black at the end and returns to the HOME Menu.

## Status

- Verified on a real **Old 3DS**: video, audio, the title sound, and the fade-out all work (smooth up to the `medium` preset).
- Not verified on a New 3DS.
- The build tool is developed and tested on Linux (Python 3.12).

## Requirements

- Python 3 (developed and tested on 3.12; tkinter is needed only for the GUI)
- `ffmpeg` / `ffprobe` (with libx264 and aac), [`makerom`](https://github.com/3DSGuy/Project_CTR)
- `bannertool` / `3dstool` (`scripts/setup-tools.sh` builds them from source; needs git, make, cmake, g++, libssl-dev)
- For sound on a real console: the DSP firmware dumped from your own 3DS (`sdmc:/3ds/dspfirm.cdc`).
  Without it, only the video plays.

The ROM is shipped prebuilt as `prebuilt/mediaplayer.elf`, so Docker/devkitPro are not needed unless you rebuild it.

## Quick start

```bash
scripts/setup-tools.sh                  # build bannertool / 3dstool into tools/bin/ (once)
mkdir -p template/MyMovie               # create a template (see below)
cp -r template/example/* template/MyMovie/   # start from the example, then replace the files with yours
scripts/mkcia.sh MyMovie                # -> out/<output>.cia
scripts/mkcia-gui.sh                    # the same thing in a GUI (needs python3-tk)
```

### Template

Put these files in `template/<name>/` (example: `template/example/`).

| File | Content |
|---|---|
| `video.mp4` | Source video (any format/resolution; the tool re-encodes it for the 3DS) |
| `icon.png` | HOME Menu icon |
| `bottom.png` | Still image shown on the bottom screen |
| `select_sound.wav` | Sound played when the icon is selected (optional; mp3 etc. also work) |
| `meta.json` | Title, publisher, title ID, version, ... |

Example `meta.json`:

```json
{
  "title": "My Movie",
  "publisher": "me",
  "title_id": "000400000FF3A000",
  "version": "1.0.0",
  "loop": false,
  "volume": 1.0,
  "preset": "medium",
  "output": "My-Movie"
}
```

- `title_id` must look like `000400000xxxxx00` (`x` = 5 hex digits). Use a different one per app
  (two CIAs with the same ID overwrite each other).
- `preset` trades quality for speed. On an Old 3DS use `medium` (default) or `light`; on a New 3DS `high` / `standard` also work.

All keys, the presets, the CLI options and how errors are reported: [docs/EN/USAGE.md](docs/EN/USAGE.md).

## Documentation

- [Usage (CLI / GUI / meta.json / presets)](docs/EN/USAGE.md)
- [Architecture (design of the ROM and the build tool)](docs/EN/ARCHITECTURE.md)
- [Development (building, testing, emulator)](docs/EN/DEVELOPMENT.md)
- [HISTORY.md](HISTORY.md) — investigation log, dead ends and open issues (Japanese)

## Notes

- Use it with content you are entitled to use (your own videos and images). This is an unofficial tool, not
  affiliated with Nintendo.
- It assumes a console with custom firmware. Use at your own risk.

## License

MIT ([LICENSE](LICENSE)). The prebuilt ROM contains FFmpeg (LGPL v2.1 or later) and other components; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details and rebuild instructions.
