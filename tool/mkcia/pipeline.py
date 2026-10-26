"""テンプレートディレクトリから CIA を作る一連の処理。"""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import assets, banner, cia, romfs, video
from .errors import MkciaError
from .meta import load_meta
from .proc import REPO_ROOT, Log

DEFAULT_ELF = REPO_ROOT / "prebuilt" / "mediaplayer.elf"


@dataclass
class BuildOptions:
    template_dir: Path
    output: Path
    preset: str = video.DEFAULT_PRESET
    elf: Path = DEFAULT_ELF
    keep_work: Optional[Path] = None  # 指定すると中間生成物をそのディレクトリに残す


def _need(template: Path, name: str, required: bool = True) -> Optional[Path]:
    p = template / name
    if p.is_file():
        return p
    if required:
        raise MkciaError(f"テンプレートに {name} がありません: {template}")
    return None


def build_cia(opt: BuildOptions, log: Optional[Log] = None) -> Path:
    log = log or (lambda _msg: None)
    tpl = Path(opt.template_dir)
    if not tpl.is_dir():
        raise MkciaError(f"テンプレートディレクトリが見つかりません: {tpl}")
    if not Path(opt.elf).is_file():
        raise MkciaError(
            f"ROM 本体の ELF が見つかりません: {opt.elf}\n"
            " scripts/build-rom.sh でビルドして prebuilt/mediaplayer.elf を用意するか --elf で指定してください"
        )

    # 1. 入力チェック
    log("[1/6] meta.json / テンプレートの確認")
    meta = load_meta(tpl / "meta.json")
    src_video = _need(tpl, "video.mp4")
    src_icon = _need(tpl, "icon.png")
    src_bottom = _need(tpl, "bottom.png")
    src_sound = _need(tpl, "select_sound.wav", required=False)
    src_banner = _need(tpl, "banner.png", required=False)

    work_ctx = None
    if opt.keep_work:
        work = Path(opt.keep_work)
        work.mkdir(parents=True, exist_ok=True)
    else:
        work_ctx = tempfile.TemporaryDirectory(prefix="mkcia-")
        work = Path(work_ctx.name)
    try:
        # 2. 動画の事前エンコード
        log(f"[2/6] 動画エンコード (preset={opt.preset})")
        enc = video.encode_video(src_video, work / "video.mp4", opt.preset, log)

        # 3. icon / banner / 選択音 -> SMDH, banner
        log("[3/6] SMDH / banner 生成")
        icon = assets.make_icon(src_icon, work / "icon48.png", log)
        banner_png = assets.make_banner_image(src_banner or src_icon, work / "banner.png", log)
        wav = assets.make_banner_audio(src_sound, work / "banner.wav", log)
        smdh = banner.make_smdh(icon, work / "app.smdh", meta.title, meta.long_title, meta.publisher, log)
        bnr = banner.make_banner(banner_png, wav, work / "app.bnr", log)

        # 4. romfs
        log("[4/6] romfs 構築")
        bottom = assets.make_bottom_image(src_bottom, work / "bottom320.png", log)
        romfs_dir = romfs.stage_romfs(work / "romfs", enc, bottom, meta.loop, meta.volume)
        romfs_bin = romfs.build_romfs_bin(romfs_dir, work / "romfs.bin", log)

        # 5. RSF
        log("[5/6] RSF 生成")
        rsf = cia.write_rsf(meta, work / "app.rsf")

        # 6. CIA
        log("[6/6] CIA 生成")
        out = Path(opt.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        cia.build_cia(Path(opt.elf), rsf, romfs_bin, smdh, bnr, meta, out, log)
        log(f"完了: {out} ({out.stat().st_size / 1024 / 1024:.1f} MiB)")
        return out
    finally:
        if work_ctx:
            work_ctx.cleanup()
