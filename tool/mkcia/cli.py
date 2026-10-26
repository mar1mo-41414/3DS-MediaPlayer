import argparse
import sys
from pathlib import Path

from . import video
from .errors import MkciaError
from .pipeline import DEFAULT_ELF, BuildOptions, build_cia


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="mkcia",
        description="テンプレートディレクトリ (video.mp4 / icon.png / bottom.png / select_sound.(wav|mp3|ogg|flac|m4a) / meta.json) から"
        " 3DS 動画再生用の .cia を生成する",
    )
    ap.add_argument("template", type=Path, help="テンプレートディレクトリ")
    ap.add_argument("-o", "--output", type=Path, help="出力 .cia (既定: <template>/../<ディレクトリ名>.cia)")
    ap.add_argument("--preset", choices=sorted(video.PRESETS), default=video.DEFAULT_PRESET, help="エンコードプリセット")
    ap.add_argument("--elf", type=Path, default=DEFAULT_ELF, help="ROM 本体の ELF")
    ap.add_argument("--keep-work", type=Path, metavar="DIR", help="中間生成物を DIR に残す")
    args = ap.parse_args(argv)

    tpl = args.template.resolve()
    out = args.output or tpl.parent / f"{tpl.name}.cia"
    try:
        build_cia(
            BuildOptions(tpl, out, preset=args.preset, elf=args.elf, keep_work=args.keep_work),
            log=lambda m: print(m, flush=True),
        )
    except MkciaError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
