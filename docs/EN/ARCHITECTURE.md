# Architecture

The design of the video-only 3DS app (the ROM) and of the tool that turns a template into a CIA.

```
template/<name>/  ──►  build tool (tool/mkcia)  ──►  <name>.cia
 video/images/audio/meta.json   validate → encode → banner/SMDH → romfs → RSF → makerom
                                          │
                  ROM (prebuilt/mediaplayer.elf, shared by all templates) ─┘
```

There is a single ROM. Everything that differs between templates lives in its romfs (`video.mp4` / `bottom.png` / `config.json`).

## The ROM (`rom/`)

devkitARM + libctru + citro2d/citro3d. FFmpeg is cross-built as a minimal H.264 / AAC / MOV configuration and linked statically.

### romfs

| File | Content |
|---|---|
| `video.mp4` | H.264 Baseline + AAC-LC, pre-encoded for the 3DS by the tool. Width and height are multiples of 8 and at most 512x256 |
| `bottom.png` | The still image (320x240) for the bottom screen |
| `config.json` | `{"loop": bool, "volume": 0.0-1.0, "deblock": bool}` |

`config.json` is flat and read with a minimal scanner.

### Playback

- **Top screen**: decode with FFmpeg → write the output of Y2R (the hardware YUV→RGB converter) directly into texture memory in the PICA200
  texture layout (8x8 blocks in Z-order) → draw with citro2d. A video smaller than the screen is scaled to full screen, keeping its aspect ratio.
- **Bottom screen**: `bottom.png` is read with libpng and written straight into the raw framebuffer (BGR8). A copy is kept for the end fade-out.
- **Audio**: swresample converts float planar to 16-bit stereo, queued into 48 ndsp wave buffers.
- **Sync**: the audio position (start of the playing wave buffer + the position inside it) is the master clock. The video shows
  the newest frame that has caught up with the clock and drops older ones (frame skipping when late); frames that are not due yet wait.
- **Threads**: decoding runs on its own thread — the extra application core (2) on a New 3DS, a low-priority thread on the application
  core (0) on an Old 3DS (the main thread mostly sleeps, so decoding gets the rest of the CPU). The Old 3DS system core (1) is limited
  to 30 % of the CPU time and could not keep up, so it is not used. Decoded frames reach the main thread through a 12-frame queue.
- **Deblocking**: by default the decoder's deblocking filter is skipped (`skip_loop_filter`). The encoder also produces deblock-free
  streams, so nothing drifts. `deblock` in `config.json` enables it, but it costs a lot for a small quality gain, so no preset uses it.
- **End**: a video with `loop` false fades the top screen (a black rectangle with rising alpha) and the bottom screen (the saved copy,
  darkened) to black over about a second once both video and audio have finished, then exits.
- **No audio**: if the DSP firmware is missing and `ndspInit` fails, the audio stream is dropped and only the video plays.
- **Stack**: the main thread's stack is 256 KB (`__stacksize__`); libctru's 32 KB default overflows during H.264 decoding.
  In a CIA the RSF `StackSize` applies.

### Debug build

Building with `-DDEBUG_LOG` writes progress, FFmpeg's log and decode times to `mediaplayer.log` in the SD card root, and uses
`sdmc:/test_video.mp4` and `sdmc:/test_config.json` instead of the romfs files when present (to compare settings).

## The build tool (`tool/mkcia`)

Plain-stdlib Python. Each step is an independent function; the CLI and the GUI call the same functions.

| Module | Role |
|---|---|
| `validate.py` | Up-front validation of inputs, output, ELF and external tools (everything before heavy work) |
| `meta.py` | Reading and validating `meta.json` (types, lengths, ranges) |
| `video.py` | Presets and the ffmpeg pre-encode |
| `assets.py` | Icon (48x48), banner (256x128), bottom image (320x240) and banner sound (WAV, ≤ 3 s) |
| `banner.py` | SMDH / banner via bannertool |
| `romfs.py` | Staging the romfs directory and `romfs.bin` via 3dstool |
| `cia.py` | Generating the RSF and building the CIA with makerom |
| `pipeline.py` | Runs the steps in order; also resolves command line > meta.json > defaults |
| `proc.py` | Running external commands (cancellable) and locating tools |
| `gui_model.py` / `gui.py` | GUI logic (no Tk) / the window (Tkinter) |

### Encoding

Fixed by presets so that software decoding on the 3DS CPU (ARM11, 268 MHz) keeps up.

- H.264 Baseline (CAVLC), no B-frames, one reference frame, a keyframe every 2 s, no deblocking, `-movflags +faststart`.
- Resolutions are multiples of 8. Anything smaller than the top screen (400x240) is scaled up by the ROM. The aspect ratio is kept
  and the margins are black. Non-square-pixel videos (SAR ≠ 1) are first converted to their display width, then fitted.
- The frame rate follows a source that is slower than the preset (it is never raised).
- Audio is AAC-LC, 32 kHz, stereo.
- Bitrate decides the picture quality. Raising the resolution is cheap (+5–13 % on an Old 3DS); deblocking costs +24–31 % for little gain.

### CIA (RSF)

The permission settings (RSF) are **not checked by emulators but mandatory on a real console**; missing entries make the app crash right
after launch on hardware only. `cia.py`'s RSF was matched against the ExHeader of homebrew CIAs known to work.

- `SystemCallAccess` (allowed SVCs), `MemoryMapping` (VRAM), `IORegisterMapping` (DSP), `FileSystemAccess` (SD read/write),
  `ServiceAccessControl` (service list), `Logo: Nintendo`.
- `makerom -desc app:N` is not used (its template overrides the service list and SVC limits, and the app then fails to start on hardware).
- The product name (NCCH internal name) is ASCII, up to 7 characters: non-ASCII characters are dropped, falling back to `MPLAYER`.
  The name shown in the HOME Menu comes from the SMDH.
- The unique ID of the title ID (`low 32 bits >> 8`) is at most 20 bits (makerom's limit).

### Failing safely

The output is written to a temporary file and then moved into place. Whether the run fails, is cancelled or is interrupted with Ctrl+C,
no intermediate or temporary files remain and an existing output is untouched.

## Performance guide (measured on an emulator approximating an Old 3DS)

Decode time (ms/frame; the budget at 20 fps is 50 ms), compared against `light`, which is smooth on a real Old 3DS.

| Setting | ms/frame | vs `light` |
|---|---|---|
| 320x192 / 250 kbps (`light`) | 42.8 | — |
| 360x216 / 400 kbps (`medium`) | 45.1 | +5 % |
| 400x240 / 400 kbps (`high`) | 48.4 | +13 % |
| 400x240 / 400 kbps + deblocking | 56.0 | +31 % |

Emulator timings do not equal real-hardware timings; use them only as a comparison against settings known to be smooth on hardware.
