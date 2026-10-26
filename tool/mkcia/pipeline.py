"""テンプレートディレクトリから CIA を作る一連の処理。"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import math

from . import assets, banner, cia, extract, romfs, video
from .errors import MkciaError
from .fsutil import create_tmp_file
from .meta import load_meta
from .proc import OUT_ROOT, REPO_ROOT, Log
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
    output: Optional[Path] = None  # 出力ファイルのパス。省略時は output_dir / (meta の output またはテンプレート名.cia)
    preset: Optional[str] = None  # 省略時は meta.json の preset、それも無ければ既定
    output_dir: Optional[Path] = None  # output 省略時の出力先ディレクトリ (既定: <リポジトリ>/out)
    elf: Path = DEFAULT_ELF
    keep_work: Optional[Path] = None  # 指定すると中間生成物をそのディレクトリに残す
    compress_code: bool = True  # False にすると ELF コードの圧縮を省く (makerom が約 8 秒速くなる。主にテスト用)
    frame_at: Optional[float] = None  # icon / bottom が無いとき動画から取るフレームの秒数 (省略時は meta.json、無ければ自動)


@dataclass
class Resolved:
    """検証済みの入力と、設定の優先順位 (引数 > meta.json > 既定) で決めた値。"""
    files: object
    meta: object
    video_info: object
    preset: str
    output: Path
    frame_at: Optional[float] = None  # 引数 > meta.json (None = 埋め込み画像 → 自動の位置)


def resolve_preset(opt: BuildOptions, meta) -> str:
    if opt.preset:
        video.get_preset(opt.preset)
        return opt.preset
    if meta.preset:
        try:
            video.get_preset(meta.preset)
        except MkciaError:
            raise MkciaError(
                f"meta.json の preset が不正です: {meta.preset!r} (選べるのは {', '.join(video.PRESETS)})"
            ) from None
        return meta.preset
    return video.DEFAULT_PRESET


def resolve_frame_at(opt: BuildOptions, meta) -> Optional[float]:
    v = opt.frame_at if opt.frame_at is not None else meta.frame_at
    if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0):
        raise MkciaError(f"frame_at は 0 以上の秒数で指定してください: {v!r}")
    return None if v is None else float(v)


def resolve_output(opt: BuildOptions, meta, template_root: Path) -> Path:
    if opt.output:
        return Path(opt.output)
    name = meta.output or f"{template_root.resolve().name or 'output'}.cia"
    return Path(opt.output_dir or OUT_ROOT) / name


def validate_inputs(opt: BuildOptions, log: Log) -> Resolved:
    """重い処理の前に、入力・出力先・ROM・外部ツールをまとめて検証する。"""
    if opt.preset:
        video.get_preset(opt.preset)  # 引数で指定された不明なプリセットは最初に弾く
    check_tools()
    check_elf(opt.elf)
    files = check_template(opt.template_dir)
    meta = load_meta(files.meta)
    preset_name = resolve_preset(opt, meta)
    output = resolve_output(opt, meta, files.root)
    frame_at = resolve_frame_at(opt, meta)
    check_output(output, [p for p in (files.meta, files.video, files.icon, files.bottom, files.sound, files.banner) if p])
    for w in meta.warnings:
        log("警告: " + w)
    vinfo = validate_video(files.video)
    for img in (files.icon, files.bottom, files.banner):  # 無いものは動画から作るので、ある物だけ検証する
        if img:
            validate_image(img)
    if files.icon is None or files.bottom is None:
        extract.check_frame_at(frame_at, vinfo)
    elif frame_at is not None:
        log("警告: icon と bottom が両方あるので、frame_at は使われません")
    if files.sound:
        validate_audio(files.sound)
    preset = video.get_preset(preset_name)
    check_size(vinfo.duration, preset.video_kbps, preset.audio_kbps)
    if not vinfo.has_audio:
        log("警告: 動画に音声がありません (映像のみになります)")
    return Resolved(files, meta, vinfo, preset_name, output, frame_at)


def build_cia(opt: BuildOptions, log: Optional[Log] = None) -> Path:
    log = log or (lambda _msg: None)

    # 1. 入力の検証 (重い処理の前に全部確認する)
    log("[1/6] meta.json / テンプレートの確認")
    r = validate_inputs(opt, log)
    files, meta, vinfo = r.files, r.meta, r.video_info

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
        log(f"[2/6] 動画エンコード (preset={r.preset})")
        enc = video.encode_video(files.video, work / "video.mp4", r.preset, log, info=vinfo)

        # 3. icon / banner / 選択音 -> SMDH, banner。icon / bottom が無ければ動画から作る
        log("[3/6] SMDH / banner 生成")
        generated = None
        if files.icon is None or files.bottom is None:
            missing = " / ".join(n for n, p in (("icon", files.icon), ("bottom", files.bottom)) if p is None)
            generated, how = extract.source_image(files.video, vinfo, r.frame_at, work, log)
            log(f"{missing} が無いので、{how}から作ります")
        icon = (assets.make_icon(generated, work / "icon48.png", log, crop_square=True) if files.icon is None
                else assets.make_icon(files.icon, work / "icon48.png", log))
        banner_png = assets.make_banner_image(files.banner or files.icon or generated, work / "banner.png", log)
        if files.sound is None:
            log("select_sound が無いので、既定のタイトル選択音を使います")
        wav = assets.make_banner_audio(files.sound, work / "banner.wav", log)
        smdh = banner.make_smdh(icon, work / "app.smdh", meta.title, meta.long_title, meta.publisher, log)
        bnr = banner.make_banner(banner_png, wav, work / "app.bnr", log)

        # 4. romfs
        log("[4/6] romfs 構築")
        bottom = assets.make_bottom_image(files.bottom or generated, work / "bottom320.png", log)
        romfs_dir = romfs.stage_romfs(work / "romfs", enc, bottom, meta.loop, meta.volume,
                                      video.get_preset(r.preset).deblock)
        romfs_bin = romfs.build_romfs_bin(romfs_dir, work / "romfs.bin", log)

        # 5. RSF
        log("[5/6] RSF 生成")
        rsf = cia.write_rsf(meta, work / "app.rsf", opt.compress_code)

        # 6. CIA。失敗しても既存の出力を壊さないよう、同じディレクトリの一時ファイルに作ってから置き換える
        log("[6/6] CIA 生成")
        out = r.output
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise MkciaError(f"出力先ディレクトリを作れません: {out.parent} ({e.strerror})") from e
        # makerom は Windows ではパスをシステムのコードページで扱うため、出力名や出力先に日本語などがあると書けないことがある。
        # そこで ASCII の作業ディレクトリに作り、Python (Unicode 対応) で出力先にコピーしてから置き換える。
        built = work / "app.cia"
        cia.build_cia(Path(opt.elf), rsf, romfs_bin, smdh, bnr, meta, built, log)
        if not built.is_file() or built.stat().st_size == 0:
            raise MkciaError("CIA の生成結果が空です")
        try:
            tmp_out = create_tmp_file(out.parent, prefix=f".{out.stem}-", suffix=".cia.tmp")
            shutil.copyfile(built, tmp_out)
            os.replace(tmp_out, out)
        except OSError as e:
            raise MkciaError(f"出力先に書き込めません: {out} ({e.strerror})") from e
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
