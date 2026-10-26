import argparse
import sys
import traceback
from pathlib import Path

from . import video
from .errors import MkciaError
from .pipeline import DEFAULT_ELF, BuildOptions, build_cia

EXIT_OK = 0
EXIT_USER_ERROR = 1  # 入力の不備など、ユーザーが直せるエラー
EXIT_INTERNAL = 2  # 想定外の例外 (バグ)
EXIT_INTERRUPTED = 130


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
    ap.add_argument("--no-compress", action="store_true", help="ELF コードの圧縮を省いて速く作る (主にテスト用。CIA が約 0.7MB 大きくなる)")
    ap.add_argument("--debug", action="store_true", help="想定外のエラー時にトレースバックを表示する")
    args = ap.parse_args(argv)

    tpl = args.template
    # 末尾スラッシュや "." / ".." でも名前が取れるように解決してから既定の出力名を決める
    tpl_resolved = tpl.resolve()
    out = args.output or tpl_resolved.parent / f"{tpl_resolved.name or 'output'}.cia"
    try:
        build_cia(
            BuildOptions(tpl, out, preset=args.preset, elf=args.elf, keep_work=args.keep_work,
                         compress_code=not args.no_compress),
            log=lambda m: print(m, flush=True),
        )
    except MkciaError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    except KeyboardInterrupt:
        print("\n中断しました", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as e:  # 想定外 = ツールのバグ。利用者には簡潔に、--debug で詳細
        print(f"内部エラー: {type(e).__name__}: {e}\n  (詳細は --debug を付けて再実行してください)", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return EXIT_INTERNAL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
