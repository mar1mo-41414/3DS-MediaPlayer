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
- **Not verified on a New 3DS** (the `high` / `standard` presets and the extra-core decoding path are untested there).
- The build tool is developed and tested on Linux (Python 3.12).

## Requirements

- Python 3 (developed and tested on 3.12; tkinter is needed only for the GUI)
- `ffmpeg` / `ffprobe` (with libx264 and aac; the stock ffmpeg of most distributions is fine)
- `bannertool` / `3dstool` / [`makerom`](https://github.com/3DSGuy/Project_CTR) (`scripts/setup-tools.sh` builds known-good versions from source into
  `tools/bin/`; needs git, make, cmake, g++, libssl-dev. `makerom` is skipped if one is already on `PATH`)
- For sound on a real console: the DSP firmware dumped from your own 3DS (`sdmc:/3ds/dspfirm.cdc`).
  Without it, only the video plays.

The ROM is shipped prebuilt as `prebuilt/mediaplayer.elf`, so Docker/devkitPro are not needed unless you rebuild it.

## Quick start

```bash
scripts/setup-tools.sh                  # build bannertool / 3dstool / makerom into tools/bin/ (once)
scripts/mkcia.sh example                # first, build the bundled sample as it is -> out/Example.cia
scripts/mkcia.sh --new MyMovie          # copy the sample into your own template, template/MyMovie
                                        #   (title = MyMovie, with a valid, non-colliding title ID)
#  -> replace the video, images, sound and meta.json in template/MyMovie with yours
scripts/mkcia.sh MyMovie                # -> out/<output>.cia
scripts/mkcia-gui.sh                    # the same thing in a GUI (needs python3-tk)
```

A prebuilt sample (`Example.cia`) is on the [Releases](https://github.com/mar1mo-41414/3DS-MediaPlayer/releases) page,
so you can check that it runs on your console before setting anything up.

### Template

Put these files in `template/<name>/` (example: `template/example/`).

| File | Content |
|---|---|
| `video.mp4` | Source video (any format/resolution; the tool re-encodes it for the 3DS) |
| `icon.png` | HOME Menu icon (optional; made from the video if absent) |
| `bottom.png` | Still image shown on the bottom screen (optional; made from the video if absent) |
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
- If `icon.png` / `bottom.png` are missing, they are made from the video: from an image embedded in it (e.g. an attachment in an mkv),
  otherwise from a frame in the middle of the video (`frame_at` chooses the second). Files that exist are used as they are.
- `preset` trades quality for speed. On an Old 3DS use `medium` (default) or `light`. `high` / `standard` are meant for a New 3DS but are **untested there**.

All keys, the presets, the CLI options and how errors are reported: [docs/EN/USAGE.md](docs/EN/USAGE.md).

## Controls (on the 3DS)

- Launch it from the HOME Menu; playback starts immediately.
- **START**: quit at any time and return to the HOME Menu.
- A non-looping video (`"loop": false`) plays to the end, then both screens fade out to black over about a second
  and the app returns to the HOME Menu by itself.
- A looping video (`"loop": true`) repeats until you press START.
- The HOME button opens the HOME Menu as usual (the app does nothing special for it; resuming afterwards has not been verified).
- There is no volume, pause or seek control (the volume is set by `volume` in `meta.json`).

## No sound?

Sound on a real console needs the **DSP firmware** (`sdmc:/3ds/dspfirm.cdc`) on the SD card. It is a standard file that you
dump when setting up custom firmware, so follow your CFW installation guide (e.g. the [3DS Hacks Guide](https://3ds.hacks.guide/)).
Without it the app plays the video only (it does not fail).

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
