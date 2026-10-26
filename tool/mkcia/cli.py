import argparse
import sys
import traceback
from pathlib import Path
from typing import List

from . import video
from .errors import MkciaError
from .pipeline import DEFAULT_ELF, BuildOptions, build_cia
from .proc import OUT_ROOT, TEMPLATE_ROOT, Cancelled
from .scaffold import create_from_example

EXIT_OK = 0
EXIT_USER_ERROR = 1  # 入力の不備など、ユーザーが直せるエラー
EXIT_INTERNAL = 2  # 想定外の例外 (バグ)
EXIT_INTERRUPTED = 130


def list_templates() -> List[str]:
    """template/ 配下のテンプレート (meta.json があるディレクトリ) の名前一覧。"""
    if not TEMPLATE_ROOT.is_dir():
        return []
    return sorted(p.name for p in TEMPLATE_ROOT.iterdir() if (p / "meta.json").exists())


def resolve_template(arg: Path) -> Path:
    """テンプレートの指定を解決する。パスとして存在すればそれ、無ければ template/<名前>。

    どちらも meta.json を持つディレクトリなら、パス指定を優先する。
    """
    cands = [arg]
    if not arg.is_absolute():
        cands.append(TEMPLATE_ROOT / arg)
    for c in cands:  # meta.json があるものを優先
        if (c / "meta.json").exists():
            return c
    for c in cands:  # 無ければ、存在するものを (具体的なエラーが出るように)
        if c.exists():
            return c
    avail = list_templates()
    hint = ("\n  使えるテンプレート: " + ", ".join(avail)) if avail else ""
    raise MkciaError(
        f"テンプレートが見つかりません: {arg}\n  (パスとしても {TEMPLATE_ROOT / arg} としても存在しません){hint}"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="mkcia",
        description="テンプレートディレクトリ (video.mp4 / icon.png / bottom.png / select_sound.(wav|mp3|ogg|flac|m4a) / meta.json) から"
        " 3DS 動画再生用の .cia を生成する。プリセットと出力名は meta.json の preset / output に書ける",
    )
    ap.add_argument("template", type=Path, nargs="?",
                    help=f"テンプレート名 ({TEMPLATE_ROOT}/ 配下) またはテンプレートディレクトリのパス")
    ap.add_argument("--list", action="store_true", help="使えるテンプレートの一覧を表示して終了")
    ap.add_argument("--new", metavar="NAME", help=f"template/example をコピーして新しいテンプレート {TEMPLATE_ROOT}/NAME を作る "
                    "(タイトルは NAME、タイトルIDは他と重ならない有効な値を自動で付ける)")
    ap.add_argument("-o", "--output", type=Path, help="出力 .cia のパス (指定すると meta.json の output / --output-dir より優先)")
    ap.add_argument("--output-dir", type=Path, help=f"出力先ディレクトリ (既定: {OUT_ROOT})")
    ap.add_argument("--preset", choices=sorted(video.PRESETS),
                    help=f"エンコードプリセット (meta.json の preset より優先。どちらも無ければ {video.DEFAULT_PRESET})")
    ap.add_argument("--elf", type=Path, default=DEFAULT_ELF, help="ROM 本体の ELF")
    ap.add_argument("--keep-work", type=Path, metavar="DIR", help="中間生成物を DIR に残す")
    ap.add_argument("--no-compress", action="store_true", help="ELF コードの圧縮を省いて速く作る (主にテスト用。CIA が約 0.7MB 大きくなる)")
    ap.add_argument("--debug", action="store_true", help="想定外のエラー時にトレースバックを表示する")
    args = ap.parse_args(argv)

    if args.list:
        names = list_templates()
        print("\n".join(names) if names else f"(テンプレートがありません: {TEMPLATE_ROOT})")
        return EXIT_OK
    if args.new is not None:
        if args.template is not None:
            ap.error("--new と、ビルドするテンプレートは同時に指定できません")
        try:
            dest = create_from_example(args.new, TEMPLATE_ROOT)
        except MkciaError as e:
            print(f"エラー: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"作成しました: {dest}\n"
              "  雛形 (example) の素材が入っています。動画・画像・音声と meta.json を自分のものに差し替えてください。\n"
              f"  ビルド: scripts/mkcia.sh {dest.name}")
        return EXIT_OK
    if args.template is None:
        ap.error("テンプレート名 (またはパス) を指定してください (--list で一覧)")

    try:
        tpl = resolve_template(args.template)
        build_cia(
            BuildOptions(tpl, args.output, preset=args.preset, output_dir=args.output_dir, elf=args.elf,
                         keep_work=args.keep_work, compress_code=not args.no_compress),
            log=lambda m: print(m, flush=True),
        )
    except Cancelled:
        print("中止しました", file=sys.stderr)
        return EXIT_INTERRUPTED
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
