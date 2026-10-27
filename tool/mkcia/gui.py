"""テンプレートから CIA を作る GUI (Tkinter)。

ロジックは gui_model.py にあり、ここは画面と入力イベントだけ。
起動: scripts/mkcia-gui.sh  (または  python3 -m mkcia.gui)
"""

import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, Dict, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # tkinter が無い Python (Debian の python3-tk 未導入、Homebrew の python-tk 未導入など)
    tk = None

from . import gui_model as gm
from . import video
from .errors import MkciaError
from .pipeline import BuildOptions
from .proc import OUT_ROOT, TEMPLATE_ROOT

THUMB = 44  # サムネイルの最大辺 (px)
TOTAL_STAGES = 6
PAD = 6

FILETYPES = {
    "video": [("動画", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"), ("すべて", "*.*")],
    "image": [("画像", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"), ("すべて", "*.*")],
    "audio": [("音声", "*.wav *.mp3 *.ogg *.flac *.m4a *.aac"), ("すべて", "*.*")],
}


class StringDialog:
    """1 行の文字列を尋ねるモーダルなダイアログ。

    tkinter.simpledialog は使わない。macOS の Tk 9 (Homebrew の python-tk など) には、simpledialog が呼ぶ
    `::tk::unsupported::MacWindowStyle` が無く、開いた瞬間に TclError で落ちるため。
    """

    def __init__(self, parent, title: str, prompt: str, initial: str = ""):
        self.parent = parent
        self.result: Optional[str] = None
        self.top = top = tk.Toplevel(parent)
        top.title(title)
        top.transient(parent)
        top.resizable(False, False)
        top.protocol("WM_DELETE_WINDOW", self.cancel)
        frame = ttk.Frame(top, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=prompt).pack(anchor="w")
        self.var = tk.StringVar(value=initial)
        self.entry = ttk.Entry(frame, textvariable=self.var, width=44)
        self.entry.pack(fill="x", pady=(6, 10))
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e")
        self.ok_button = ttk.Button(buttons, text="OK", command=self.ok)
        self.ok_button.pack(side="left", padx=(0, 6))
        self.cancel_button = ttk.Button(buttons, text="キャンセル", command=self.cancel)
        self.cancel_button.pack(side="left")
        top.bind("<Return>", lambda _e: self.ok())
        top.bind("<Escape>", lambda _e: self.cancel())

    def ok(self) -> None:
        self.result = self.var.get()
        self.top.destroy()

    def cancel(self) -> None:
        self.result = None
        self.top.destroy()

    def show(self) -> Optional[str]:
        """親ウィンドウの中央に出し、閉じるまで待つ。OK なら入力した文字列、キャンセルなら None。"""
        top = self.top
        top.update_idletasks()
        try:
            x = self.parent.winfo_rootx() + (self.parent.winfo_width() - top.winfo_reqwidth()) // 2
            y = self.parent.winfo_rooty() + (self.parent.winfo_height() - top.winfo_reqheight()) // 3
            top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except tk.TclError:
            pass
        self.entry.focus_set()
        try:
            top.wait_visibility()
            top.grab_set()
        except tk.TclError:  # 画面に出せない/グラブできない環境でも、入力自体はできる
            pass
        if top.winfo_exists():  # 表示を待つ間に閉じられていたら、待たない
            self.parent.wait_window(top)
        return self.result


class App:
    def __init__(self, root: "tk.Tk", template_root: Optional[Path] = None):
        self.root = root
        self.template_root = Path(template_root or TEMPLATE_ROOT)
        self.template: Optional[gm.TemplateDir] = None
        self.job: Optional[gm.Job] = None
        self.last_output: Optional[Path] = None
        self._loading = False
        self._dirty = False
        self._thumbs: Dict[str, "tk.PhotoImage"] = {}
        self._bg: "queue.Queue[tuple]" = queue.Queue()
        self._bg_busy = 0
        self._after_id = None

        root.title("3DS-MediaPlayer CIA ビルダー")
        root.minsize(900, 600)
        h = min(900, max(600, root.winfo_screenheight() - 80))
        root.geometry(f"960x{h}")
        self._build_ui()
        self.refresh_template_list()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-s>", lambda e: self.save())
        root.bind("<Destroy>", self._on_destroy, add="+")
        self._after_id = self.root.after(100, self.pump)

    # ================================================================ 画面の組み立て
    def _build_ui(self) -> None:
        r = self.root
        style = ttk.Style(r)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Problem.TLabel", foreground="#b00020")
        style.configure("Warn.TLabel", foreground="#9a6700")
        style.configure("Ok.TLabel", foreground="#1a7f37")
        style.configure("Hint.TLabel", foreground="#666666")
        outer = ttk.Frame(r, padding=PAD)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)

        # ---- テンプレート選択
        bar = ttk.Frame(outer)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, text="テンプレート:").pack(side="left")
        self.tpl_var = tk.StringVar()
        self.tpl_box = ttk.Combobox(bar, textvariable=self.tpl_var, state="readonly", width=40)
        self.tpl_box.pack(side="left", padx=PAD)
        self.tpl_box.bind("<<ComboboxSelected>>", lambda e: self.on_template_selected())
        ttk.Button(bar, text="新規作成…", command=self.on_new_template).pack(side="left")
        ttk.Button(bar, text="フォルダを選ぶ…", command=self.on_open_template_dir).pack(side="left", padx=PAD)
        ttk.Button(bar, text="再読込", command=self.refresh_template_list).pack(side="left")

        # ---- 基本情報
        meta = ttk.LabelFrame(outer, text="基本情報 (ホームメニュー)", padding=PAD)
        meta.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)
        self.vars: Dict[str, "tk.Variable"] = {}

        def entry(row, col, label, key, width=28, hint=None):
            ttk.Label(meta, text=label).grid(row=row, column=col * 2, sticky="e", padx=(0, PAD), pady=2)
            v = tk.StringVar()
            self.vars[key] = v
            e = ttk.Entry(meta, textvariable=v, width=width)
            e.grid(row=row, column=col * 2 + 1, sticky="ew", pady=2, padx=(0, PAD * 2))
            v.trace_add("write", lambda *a: self.on_field_changed())
            return e

        entry(0, 0, "タイトル *", "title")
        entry(0, 1, "公開者 *", "publisher")
        entry(1, 0, "長いタイトル", "long_title")
        entry(1, 1, "製品コード", "product_code")
        ttk.Label(meta, text="タイトルID *").grid(row=2, column=0, sticky="e", padx=(0, PAD), pady=2)
        idbar = ttk.Frame(meta)
        idbar.grid(row=2, column=1, sticky="ew", pady=2, padx=(0, PAD * 2))
        idbar.columnconfigure(0, weight=1)
        self.vars["title_id"] = tk.StringVar()
        self.vars["title_id"].trace_add("write", lambda *a: self.on_field_changed())
        ttk.Entry(idbar, textvariable=self.vars["title_id"]).grid(row=0, column=0, sticky="ew")
        ttk.Button(idbar, text="自動", width=5, command=self.on_auto_title_id).grid(row=0, column=1, padx=(PAD, 0))
        entry(2, 1, "バージョン *", "version")
        self._id_hint = "* は必須。タイトルIDは 000400000xxxxx00 形式 (x は16進5桁)。バージョンは 1.0.0 のように。製品コードは空欄可 (CTR-P-XXXX)"
        self.id_warn = ttk.Label(meta, text=self._id_hint, style="Hint.TLabel")
        self.id_warn.grid(row=3, column=0, columnspan=4, sticky="w")

        # ---- 再生・出力
        play = ttk.LabelFrame(outer, text="再生・出力", padding=PAD)
        play.grid(row=2, column=0, sticky="ew", pady=(PAD, 0))
        play.columnconfigure(1, weight=1)
        ttk.Label(play, text="プリセット").grid(row=0, column=0, sticky="e", padx=(0, PAD))
        self._preset_pairs = gm.preset_choices()
        self._preset_default_label = f"(指定なし = 既定の {video.DEFAULT_PRESET})"
        self.preset_var = tk.StringVar()
        self.preset_box = ttk.Combobox(play, textvariable=self.preset_var, state="readonly", width=60,
                                       values=[self._preset_default_label] + [l for _, l in self._preset_pairs])
        self.preset_box.grid(row=0, column=1, sticky="ew")
        self.preset_box.bind("<<ComboboxSelected>>", lambda e: self.on_field_changed())
        self.size_label = ttk.Label(play, text="", style="Hint.TLabel")
        self.size_label.grid(row=0, column=2, sticky="w", padx=PAD)

        ttk.Label(play, text="ループ再生").grid(row=1, column=0, sticky="e", padx=(0, PAD))
        loopbar = ttk.Frame(play)
        loopbar.grid(row=1, column=1, sticky="w")
        self.loop_var = tk.BooleanVar()
        ttk.Checkbutton(loopbar, text="最後まで再生したら最初に戻る (オフなら終了時にフェードアウトしてホームへ)",
                        variable=self.loop_var, command=self.on_field_changed).pack(side="left")

        ttk.Label(play, text="音量").grid(row=2, column=0, sticky="e", padx=(0, PAD))
        volbar = ttk.Frame(play)
        volbar.grid(row=2, column=1, sticky="ew")
        self.volume_var = tk.DoubleVar(value=1.0)
        self.volume_text = tk.StringVar(value="1.00")
        ttk.Scale(volbar, from_=0.0, to=1.0, variable=self.volume_var, command=self.on_volume_moved,
                  length=260).pack(side="left")
        ttk.Label(volbar, textvariable=self.volume_text, width=5).pack(side="left", padx=PAD)

        ttk.Label(play, text="出力ファイル名").grid(row=3, column=0, sticky="e", padx=(0, PAD), pady=2)
        self.vars["output"] = tk.StringVar()
        self.vars["output"].trace_add("write", lambda *a: self.on_field_changed())
        ttk.Entry(play, textvariable=self.vars["output"]).grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Label(play, text="空欄 = テンプレート名。.cia は自動で付く", style="Hint.TLabel").grid(row=3, column=2, sticky="w", padx=PAD)

        ttk.Label(play, text="画像の抽出位置").grid(row=4, column=0, sticky="e", padx=(0, PAD), pady=2)
        frbar = ttk.Frame(play)
        frbar.grid(row=4, column=1, sticky="ew", pady=2)
        self.vars["frame_at"] = tk.StringVar()
        self.vars["frame_at"].trace_add("write", lambda *a: self.on_field_changed())
        ttk.Entry(frbar, textvariable=self.vars["frame_at"], width=10).pack(side="left")
        ttk.Label(frbar, text="秒 (空欄 = 埋め込み画像、無ければ長さの15%。アイコン/下画面が無いときだけ)",
                  style="Hint.TLabel").pack(side="left", padx=PAD)

        ttk.Label(play, text="出力先フォルダ").grid(row=5, column=0, sticky="e", padx=(0, PAD), pady=2)
        self.outdir_var = tk.StringVar()
        ttk.Entry(play, textvariable=self.outdir_var).grid(row=5, column=1, sticky="ew", pady=2)
        ttk.Button(play, text="参照…", command=self.on_choose_outdir).grid(row=5, column=2, sticky="w", padx=PAD)
        
        ttk.Label(play, text=f"空欄 = {OUT_ROOT}", style="Hint.TLabel").grid(row=6, column=1, sticky="w")

        self.compress_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(play, text="ELF コードを圧縮する (推奨。オフにすると約 8 秒速いが CIA が約 0.7MB 大きい)",
                        variable=self.compress_var).grid(row=7, column=1, sticky="w")

        # ---- 素材
        assets = ttk.LabelFrame(outer, text="素材", padding=PAD)
        assets.grid(row=3, column=0, sticky="ew", pady=(PAD, 0))
        assets.columnconfigure(1, weight=1)
        self.asset_status: Dict[str, "tk.StringVar"] = {}
        self.asset_thumb: Dict[str, "ttk.Label"] = {}
        self.asset_remove: Dict[str, "ttk.Button"] = {}
        for i, spec in enumerate(gm.ASSETS):
            box = ttk.Frame(assets, width=THUMB + 8, height=THUMB + 4, relief="groove")
            box.grid(row=i, column=0, padx=(0, PAD), pady=0)
            box.pack_propagate(False)
            th = ttk.Label(box, anchor="center")
            th.pack(fill="both", expand=True)
            self.asset_thumb[spec.stem] = th
            col = ttk.Frame(assets)
            col.grid(row=i, column=1, sticky="ew")
            col.columnconfigure(0, weight=1)
            ttk.Label(col, text=spec.label + (" *" if spec.required else " (任意)"), font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w")
            sv = tk.StringVar()
            self.asset_status[spec.stem] = sv
            ttk.Label(col, textvariable=sv, wraplength=560, justify="left").grid(row=1, column=0, sticky="w")
            btns = ttk.Frame(assets)
            btns.grid(row=i, column=2, padx=PAD)
            ttk.Button(btns, text="選択…", command=lambda s=spec.stem: self.on_choose_asset(s)).pack(side="left")
            if not spec.required:
                b = ttk.Button(btns, text="削除", command=lambda s=spec.stem: self.on_remove_asset(s))
                b.pack(side="left", padx=(PAD, 0))
                self.asset_remove[spec.stem] = b

        # ---- 操作
        act = ttk.Frame(outer)
        act.grid(row=4, column=0, sticky="ew", pady=(PAD, 0))
        self.btn_save = ttk.Button(act, text="保存 (Ctrl+S)", command=self.save)
        self.btn_save.pack(side="left")
        self.btn_validate = ttk.Button(act, text="検証", command=self.validate)
        self.btn_validate.pack(side="left", padx=PAD)
        self.btn_build = ttk.Button(act, text="CIA を作る", command=self.build)
        self.btn_build.pack(side="left")
        self.btn_cancel = ttk.Button(act, text="中止", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=PAD)
        self.status_var = tk.StringVar(value="テンプレートを選んでください")
        self.status_label = ttk.Label(act, textvariable=self.status_var)
        self.status_label.pack(side="left", padx=PAD * 2)
        self.btn_open = ttk.Button(act, text="出力フォルダを開く", command=self.open_output_folder, state="disabled")
        self.btn_open.pack(side="right")

        # ---- 進捗とログ
        logf = ttk.LabelFrame(outer, text="進捗とログ", padding=PAD)
        logf.grid(row=5, column=0, sticky="nsew", pady=(PAD, 0))
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(2, weight=1)
        self.progress = ttk.Progressbar(logf, maximum=TOTAL_STAGES, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")
        stagebar = ttk.Frame(logf)
        stagebar.grid(row=1, column=0, sticky="ew")
        self.stage_var = tk.StringVar(value="")
        ttk.Label(stagebar, textvariable=self.stage_var, style="Hint.TLabel").pack(side="left")
        self.verbose_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(stagebar, text="コマンドも表示", variable=self.verbose_var).pack(side="right")
        self.problem_var = tk.StringVar(value="")
        self.log = tk.Text(logf, height=7, wrap="word", state="disabled")
        self.log.grid(row=2, column=0, sticky="nsew")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        sb.grid(row=2, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)
        self.problem_label = ttk.Label(logf, textvariable=self.problem_var, style="Problem.TLabel", wraplength=820, justify="left")
        self.problem_label.grid(row=3, column=0, sticky="w")

    # ================================================================ ダイアログ (テストで差し替える)
    def ask_open_file(self, title: str, kind: str) -> Optional[str]:
        return filedialog.askopenfilename(parent=self.root, title=title, filetypes=FILETYPES[kind]) or None

    def ask_directory(self, title: str) -> Optional[str]:
        return filedialog.askdirectory(parent=self.root, title=title, mustexist=True) or None

    def ask_new_name(self) -> Optional[str]:
        return StringDialog(self.root, "新規テンプレート", "テンプレート名 (template/ 配下のフォルダ名):").show()

    def confirm(self, title: str, text: str) -> Optional[bool]:
        """はい=True / いいえ=False / キャンセル=None"""
        return messagebox.askyesnocancel(title, text, parent=self.root)

    def show_error(self, text: str) -> None:
        messagebox.showerror("エラー", text, parent=self.root)

    def show_info(self, text: str) -> None:
        messagebox.showinfo("情報", text, parent=self.root)

    # ================================================================ 状態表示
    def set_status(self, text: str, kind: str = "") -> None:
        self.status_var.set(text)
        self.status_label.configure(style={"ok": "Ok.TLabel", "error": "Problem.TLabel", "warn": "Warn.TLabel"}.get(kind, "TLabel"))

    def log_line(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def set_busy(self, busy: bool) -> None:
        for b in (self.btn_save, self.btn_validate, self.btn_build, self.tpl_box):
            b.configure(state="disabled" if busy else ("readonly" if b is self.tpl_box else "normal"))
        self.btn_cancel.configure(state="normal" if busy else "disabled")

    # ================================================================ テンプレート
    def refresh_template_list(self) -> None:
        names = gm.list_templates(self.template_root)
        cur = self.tpl_var.get()
        if cur and cur not in names and self.template is not None:
            names.append(cur)  # 任意のフォルダを開いている場合は残す
        self.tpl_box.configure(values=names)
        if not names:
            self.set_status(f"テンプレートがありません。「新規作成…」で作るか、{self.template_root} に置いてください", "warn")

    def _path_for(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else self.template_root / name

    def confirm_discard(self) -> bool:
        """未保存の変更があれば確認する。続けてよければ True。"""
        if not self._dirty or self.template is None:
            return True
        ans = self.confirm("未保存の変更", "変更を保存しますか?")
        if ans is None:
            return False
        if ans:
            return self.save()
        self._dirty = False
        return True

    def on_template_selected(self) -> None:
        name = self.tpl_var.get()
        prev = self.template
        if not self.confirm_discard():
            self.tpl_var.set(prev.name if prev else "")
            return
        self.open_template(self._path_for(name))

    def on_open_template_dir(self) -> None:
        if not self.confirm_discard():
            return
        d = self.ask_directory("テンプレートのフォルダを選ぶ")
        if d:
            self.open_template(Path(d))

    def on_new_template(self) -> None:
        if not self.confirm_discard():
            return
        name = self.ask_new_name()
        if name is None:
            return
        try:
            t = gm.TemplateDir.create(name, self.template_root)
        except MkciaError as e:
            self.show_error(str(e))
            return
        self.refresh_template_list()
        self.open_template(t.path)
        self.set_status("新規テンプレートを作りました。素材と基本情報を設定してください", "ok")

    def open_template(self, path: Path) -> None:
        path = Path(path)
        if not path.is_dir():
            self.show_error(f"テンプレートが見つかりません: {path}")
            return
        self.template = gm.TemplateDir(path)
        display = path.name if path.parent == self.template_root else str(path)
        self.tpl_var.set(display)
        if display not in self.tpl_box.cget("values"):
            self.tpl_box.configure(values=list(self.tpl_box.cget("values")) + [display])
        form, warnings = self.template.load_form()
        self.apply_form(form)
        self._dirty = False
        self.clear_log()
        for w in warnings:
            self.log_line("警告: " + w)
        self.problem_var.set("")
        self.progress.configure(value=0)
        self.stage_var.set("")
        self.btn_open.configure(state="disabled")
        self.last_output = None
        self.refresh_assets()
        self.on_field_changed(mark_dirty=False)
        self.set_status(f"{self.template.name} を開きました")

    # ================================================================ フォーム <-> 画面
    def apply_form(self, f: gm.TemplateForm) -> None:
        self._loading = True
        try:
            for k in ("title", "long_title", "publisher", "title_id", "version", "product_code", "output", "frame_at"):
                self.vars[k].set(getattr(f, k))
            self.loop_var.set(f.loop)
            self.volume_var.set(f.volume)
            self.volume_text.set(f"{f.volume:.2f}")
            label = dict(self._preset_pairs).get(f.preset) if f.preset else None
            self.preset_var.set(label or self._preset_default_label)
        finally:
            self._loading = False

    def collect_form(self) -> gm.TemplateForm:
        label_to_name = {l: n for n, l in self._preset_pairs}
        return gm.TemplateForm(
            title=self.vars["title"].get(), long_title=self.vars["long_title"].get(),
            publisher=self.vars["publisher"].get(), title_id=self.vars["title_id"].get(),
            version=self.vars["version"].get(), product_code=self.vars["product_code"].get(),
            loop=bool(self.loop_var.get()), volume=round(float(self.volume_var.get()), 2),
            preset=label_to_name.get(self.preset_var.get(), ""), output=self.vars["output"].get(),
            frame_at=self.vars["frame_at"].get(),
        )

    def on_volume_moved(self, _value=None) -> None:
        self.volume_text.set(f"{float(self.volume_var.get()):.2f}")
        self.on_field_changed()

    def on_field_changed(self, mark_dirty: bool = True) -> None:
        if self._loading:
            return
        if mark_dirty and self.template is not None:
            self._dirty = True
        self.refresh_live_checks()

    def refresh_live_checks(self) -> None:
        """入力中の検証結果 (赤字)・title_id の重複・サイズ見積もりを更新する。"""
        form = self.collect_form()
        try:
            gm.validate_form(form)
            self.problem_var.set("")
        except MkciaError as e:
            self.problem_var.set("入力エラー: " + str(e))
        if self.template is not None:
            dup = gm.title_id_conflicts(form.title_id, self.template_root, exclude=self.template.name)
            if dup:
                self.id_warn.configure(style="Warn.TLabel", text="注意: 同じタイトルIDのテンプレートがあります "
                                       "(両方インストールすると上書きし合います): " + ", ".join(dup))
            else:
                self.id_warn.configure(style="Hint.TLabel", text=self._id_hint)
        self.size_label.configure(text="")
        if self.template is not None:
            v = self.template.find_asset("video")
            if v is not None and getattr(self, "_video_duration", None) is not None:
                self.size_label.configure(text="CIA 見積もり: " + gm.estimate_size_text(self._video_duration, form.preset))

    def on_auto_title_id(self) -> None:
        if self.template is None:
            return
        taken = [f.title_id for n, f in gm._all_forms(self.template_root) if n != self.template.name]
        self.vars["title_id"].set(gm.suggest_title_id(self.template.name, taken))

    # ================================================================ 素材
    def refresh_assets(self) -> None:
        if self.template is None:
            return
        self._video_duration = None
        for spec in gm.ASSETS:
            self.asset_status[spec.stem].set("確認中…")
            self.asset_thumb[spec.stem].configure(image="", text="")
            self._thumbs.pop(spec.stem, None)
            self.run_bg(lambda t=self.template, s=spec: self._load_asset(t, s.stem), self._asset_loaded)

    @staticmethod
    def _load_asset(t: gm.TemplateDir, stem: str):
        """(別スレッド) 素材の説明・サムネイル・動画の長さを調べる。"""
        text = t.describe_asset(stem)
        p = t.find_asset(stem)
        thumb = None
        duration = None
        if p is not None:
            kind = gm.ASSET_BY_STEM[stem].kind
            seek = 0.0
            if kind == "video":
                try:
                    duration = gm.validate_video(p).duration
                except MkciaError:
                    duration = None
                if duration:
                    seek = min(duration * 0.15, 30.0)  # 冒頭の暗転を避ける
            if kind in ("video", "image"):
                thumb = gm.make_thumbnail(p, THUMB, seek=seek)
        return stem, t.path, text, thumb, duration

    def _asset_loaded(self, result) -> None:
        stem, path, text, thumb, duration = result
        if self.template is None or self.template.path != path:
            return  # 読み込み中に別のテンプレートへ切り替わった
        self.asset_status[stem].set(text)
        lab = self.asset_thumb[stem]
        if thumb:
            try:
                img = tk.PhotoImage(data=thumb)
                self._thumbs[stem] = img
                lab.configure(image=img, text="")
            except tk.TclError:
                lab.configure(image="", text="(表示不可)")
        elif gm.ASSET_BY_STEM[stem].kind == "audio":
            lab.configure(image="", text="♪" if "未設定" not in text else "")
        else:
            lab.configure(image="", text="" if "未設定" in text else "(表示不可)")
        if stem == "video":
            self._video_duration = duration
            self.refresh_live_checks()

    def on_choose_asset(self, stem: str) -> None:
        if self.template is None:
            self.show_error("先にテンプレートを選ぶか、新規作成してください")
            return
        spec = gm.ASSET_BY_STEM[stem]
        path = self.ask_open_file(f"{spec.label}を選ぶ", spec.kind)
        if path:
            self.set_asset_from_path(stem, Path(path))

    def set_asset_from_path(self, stem: str, path: Path) -> None:
        t = self.template
        self.asset_status[stem].set("コピー中…")
        self.set_status(f"{gm.ASSET_BY_STEM[stem].label}をコピーしています…")

        def done(_):
            self.set_status(f"{gm.ASSET_BY_STEM[stem].label}を設定しました", "ok")
            self.refresh_assets()

        def failed(msg):
            self.set_status("素材を設定できませんでした", "error")
            self.show_error(msg)
            self.refresh_assets()

        self.run_bg(lambda: t.set_asset(stem, path), done, failed)

    def on_remove_asset(self, stem: str) -> None:
        if self.template is None:
            return
        try:
            self.template.remove_asset(stem)
        except MkciaError as e:
            self.show_error(str(e))
            return
        self.refresh_assets()

    def on_choose_outdir(self) -> None:
        d = self.ask_directory("出力先フォルダを選ぶ")
        if d:
            self.outdir_var.set(d)

    # ================================================================ バックグラウンド処理 (UI を止めない)
    def run_bg(self, fn: Callable, on_ok: Callable, on_err: Optional[Callable] = None) -> None:
        self._bg_busy += 1

        def work():
            try:
                res = ("ok", fn())
            except MkciaError as e:
                res = ("err", str(e))
            except Exception:
                res = ("err", "内部エラー:\n" + traceback.format_exc())
            self._bg.put((res, on_ok, on_err))

        threading.Thread(target=work, daemon=True).start()

    def pump(self) -> None:
        """定期的に呼ばれ、バックグラウンド処理とビルドジョブの結果を画面に反映する。"""
        try:
            while True:
                (kind, val), on_ok, on_err = self._bg.get_nowait()
                self._bg_busy -= 1
                if kind == "ok":
                    on_ok(val)
                elif on_err:
                    on_err(val)
                else:
                    self.show_error(val)
        except queue.Empty:
            pass
        if self.job is not None:
            try:
                while True:
                    self.handle_event(self.job.events.get_nowait())
            except queue.Empty:
                pass
        try:
            self._after_id = self.root.after(100, self.pump)
        except tk.TclError:
            self._after_id = None  # ウィンドウが閉じられた

    # ================================================================ 保存・検証・ビルド
    def save(self) -> bool:
        if self.template is None:
            self.show_error("テンプレートが選ばれていません")
            return False
        try:
            self.template.save_form(self.collect_form())
        except MkciaError as e:
            self.set_status("保存できません (入力エラー)", "error")
            self.show_error(str(e))
            return False
        self._dirty = False
        self.set_status("meta.json を保存しました", "ok")
        return True

    def _options(self) -> BuildOptions:
        outdir = self.outdir_var.get().strip()
        return BuildOptions(
            self.template.path,
            preset=None,  # 保存済みの meta.json の preset (無ければ既定) を使う
            output_dir=Path(outdir).expanduser() if outdir else None,
            compress_code=bool(self.compress_var.get()),
        )

    def _start(self, starter, label: str) -> None:
        if self.template is None:
            self.show_error("テンプレートが選ばれていません")
            return
        if self.job is not None and self.job.is_running():
            return
        if not self.save():
            return
        self.clear_log()
        self.progress.configure(value=0)
        self.stage_var.set("")
        self.btn_open.configure(state="disabled")
        self.set_busy(True)
        self.set_status(label)
        self.job = starter(self._options())

    def validate(self) -> None:
        self._start(gm.start_validation, "検証中…")

    def build(self) -> None:
        self._start(gm.start_build, "ビルド中…")

    def cancel(self) -> None:
        if self.job is not None and self.job.is_running():
            self.job.cancel()
            self.set_status("中止しています…", "warn")

    def handle_event(self, ev: tuple) -> None:
        kind = ev[0]
        if kind == "log":
            if self.verbose_var.get() or not ev[1].startswith("$ "):  # 外部コマンドの行は既定では隠す
                self.log_line(ev[1])
        elif kind == "stage":
            self.progress.configure(value=ev[1] - 1)
            self.stage_var.set(f"[{ev[1]}/{ev[2]}] {ev[3]}")
        elif kind == "done":
            self.set_busy(False)
            res = ev[1]
            if isinstance(res, Path):  # ビルド完了
                self.last_output = res
                self.progress.configure(value=TOTAL_STAGES)
                self.stage_var.set("完了")
                size = res.stat().st_size / 1024 / 1024 if res.exists() else 0
                self.set_status(f"完了: {res.name} ({size:.1f} MiB)", "ok")
                self.btn_open.configure(state="normal")
            else:  # 検証の結果 (文字列)
                self.log_line("--- 検証OK ---\n" + str(res))
                self.stage_var.set("検証OK")
                self.set_status("検証OK。ビルドできます", "ok")
        elif kind == "cancelled":
            self.set_busy(False)
            self.progress.configure(value=0)
            self.stage_var.set("")
            self.log_line("中止しました")
            self.set_status("中止しました", "warn")
        elif kind == "error":
            self.set_busy(False)
            self.log_line("エラー: " + ev[1])
            self.set_status("失敗しました", "error")
            self.show_error(ev[1])
        elif kind == "crash":
            self.set_busy(False)
            self.log_line("内部エラー:\n" + ev[1])
            self.set_status("内部エラー", "error")
            self.show_error("想定外のエラーです。ログを確認してください。\n\n" + ev[1].strip().splitlines()[-1])

    def open_output_folder(self) -> None:
        if self.last_output is not None and not gm.open_folder(self.last_output.parent):
            self.show_error(f"フォルダを開けませんでした: {self.last_output.parent}")

    def _on_destroy(self, event) -> None:
        """ウィンドウが壊れるときに、予約済みの定期処理を取り消す (取り消さないと Tk が警告を出す)。"""
        if event.widget is self.root and self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def on_close(self) -> None:
        if self.job is not None and self.job.is_running():
            if not self.confirm("終了", "ビルド中です。中止して終了しますか?"):
                return
            self.job.cancel()
            self.job.join(5)
        elif not self.confirm_discard():
            return
        self.root.destroy()


def main(argv=None) -> int:
    if tk is None:
        print(gm.tkinter_missing_message(), file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"エラー: GUI を起動できません (画面が見つかりません?): {e}", file=sys.stderr)
        return 1
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
