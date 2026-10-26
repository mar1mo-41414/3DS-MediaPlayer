"""テンプレートディレクトリから CIA を作る一連の処理。"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import assets, banner, cia, romfs, video
from .errors import MkciaError
from .meta import load_meta
from .proc import REPO_ROOT, Log
from .validate import (
    check_elf,
    check_output,
    check_size,
    check_template,
    check_tools,
    validate_audio,
    validate_image,
    validate_video,
)

DEFAULT_ELF = REPO_ROOT / "prebuilt" / "mediaplayer.elf"


@dataclass
class BuildOptions:
    template_dir: Path
    output: Path
    preset: str = video.DEFAULT_PRESET
    elf: Path = DEFAULT_ELF
    keep_work: Optional[Path] = None  # 指定すると中間生成物をそのディレクトリに残す
    compress_code: bool = True  # False にすると ELF コードの圧縮を省く (makerom が約 8 秒速くなる。主にテスト用)


def validate_inputs(opt: BuildOptions, log: Log):
    """重い処理の前に、入力・出力先・ROM・外部ツールをまとめて検証する。戻り値: (files, meta, video_info)。"""
    video.get_preset(opt.preset)  # 不明なプリセットは最初に弾く
    check_tools()
    check_elf(opt.elf)
    files = check_template(opt.template_dir)
    check_output(opt.output, [files.meta, files.video, files.icon, files.bottom,
                              *(p for p in (files.sound, files.banner) if p)])
    meta = load_meta(files.meta)
    for w in meta.warnings:
        log("警告: " + w)
    vinfo = validate_video(files.video)
    validate_image(files.icon)
    validate_image(files.bottom)
    if files.banner:
        validate_image(files.banner)
    if files.sound:
        validate_audio(files.sound)
    preset = video.get_preset(opt.preset)
    check_size(vinfo.duration, preset.video_kbps, preset.audio_kbps)
    if not vinfo.has_audio:
        log("警告: 動画に音声がありません (映像のみになります)")
    return files, meta, vinfo


def build_cia(opt: BuildOptions, log: Optional[Log] = None) -> Path:
    log = log or (lambda _msg: None)

    # 1. 入力の検証 (重い処理の前に全部確認する)
    log("[1/6] meta.json / テンプレートの確認")
    files, meta, vinfo = validate_inputs(opt, log)

    work_ctx = None
    if opt.keep_work:
        work = Path(opt.keep_work)
        try:
            work.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise MkciaError(f"作業ディレクトリを作れません: {work} ({e.strerror})") from e
    else:
        work_ctx = tempfile.TemporaryDirectory(prefix="mkcia-")
        work = Path(work_ctx.name)
    tmp_out: Optional[Path] = None
    try:
        # 2. 動画の事前エンコード
        log(f"[2/6] 動画エンコード (preset={opt.preset})")
        enc = video.encode_video(files.video, work / "video.mp4", opt.preset, log, info=vinfo)

        # 3. icon / banner / 選択音 -> SMDH, banner
        log("[3/6] SMDH / banner 生成")
        icon = assets.make_icon(files.icon, work / "icon48.png", log)
        banner_png = assets.make_banner_image(files.banner or files.icon, work / "banner.png", log)
        wav = assets.make_banner_audio(files.sound, work / "banner.wav", log)
        smdh = banner.make_smdh(icon, work / "app.smdh", meta.title, meta.long_title, meta.publisher, log)
        bnr = banner.make_banner(banner_png, wav, work / "app.bnr", log)

        # 4. romfs
        log("[4/6] romfs 構築")
        bottom = assets.make_bottom_image(files.bottom, work / "bottom320.png", log)
        romfs_dir = romfs.stage_romfs(work / "romfs", enc, bottom, meta.loop, meta.volume,
                                      video.get_preset(opt.preset).deblock)
        romfs_bin = romfs.build_romfs_bin(romfs_dir, work / "romfs.bin", log)

        # 5. RSF
        log("[5/6] RSF 生成")
        rsf = cia.write_rsf(meta, work / "app.rsf", opt.compress_code)

        # 6. CIA。失敗しても既存の出力を壊さないよう、同じディレクトリの一時ファイルに作ってから置き換える
        log("[6/6] CIA 生成")
        out = Path(opt.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise MkciaError(f"出力先ディレクトリを作れません: {out.parent} ({e.strerror})") from e
        fd, tmp_name = tempfile.mkstemp(prefix=f".{out.stem}-", suffix=".cia.tmp", dir=out.parent)
        os.close(fd)
        tmp_out = Path(tmp_name)
        cia.build_cia(Path(opt.elf), rsf, romfs_bin, smdh, bnr, meta, tmp_out, log)
        if not tmp_out.is_file() or tmp_out.stat().st_size == 0:
            raise MkciaError("CIA の生成結果が空です")
        os.replace(tmp_out, out)
        tmp_out = None
        log(f"完了: {out} ({out.stat().st_size / 1024 / 1024:.1f} MiB)")
        return out
    finally:
        if tmp_out is not None:
            try:
                tmp_out.unlink()
            except OSError:
                pass
        if work_ctx:
            work_ctx.cleanup()
