#!/usr/bin/env python3
"""
gui.py — Graphical front end for the QSF2LSS converter.

One window, no console:
  * pick .qsf files with a file dialog, or drag & drop them onto the window
  * press "Convert" — every file is inspected, converted and verified
  * the results are shown in the window (per-file overview + details)
  * the .lss files and a text report land in the chosen output folder

Cross-platform: Tkinter ships with Python on Windows and macOS. Drag & drop uses
the optional `tkinterdnd2` package (pip install tkinterdnd2); without it the
program still works — the drop zone becomes a click-to-browse area.

Run:   python gui.py
Build: pyinstaller QSF2LSS-GUI.spec
"""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# When running as a PyInstaller bundle, work relative to the executable.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent
sys.path.insert(0, str(APP_DIR))

from qsf_to_lss import convert_qsf_to_lss          # noqa: E402
from qsf_inspector import inspect_one              # noqa: E402
from app import (                                  # noqa: E402
    ReportWriter, analyse_lss, run_checks, LS_TYPE_NAMES,
    write_input_report, write_output_report, write_check_report,
    HEADER, THIN,
)

# Optional drag & drop support --------------------------------------------------
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAVE_DND = True
except Exception:  # ImportError, or a broken native lib on an exotic platform
    DND_FILES = None
    TkinterDnD = None
    HAVE_DND = False

APP_TITLE = "QSF2LSS"
IS_MAC = platform.system() == "Darwin"

# Colours (kept muted so the window looks native on both platforms)
C_BG = "#f4f5f7"
C_DROP = "#e8eef7"
C_DROP_ACTIVE = "#cfe0f7"
C_BORDER = "#8fa6c8"
C_OK = "#1e7d34"
C_WARN = "#b26a00"
C_FAIL = "#b00020"
C_INFO = "#3a5a8c"
C_MUTED = "#6b6b6b"


# ---------------------------------------------------------------------------
# Conversion of one file (runs in a worker thread, no Tk calls inside)
# ---------------------------------------------------------------------------
def convert_file(qsf_path: Path, output_dir: Path, w: ReportWriter) -> dict:
    """Inspect, convert, verify one .qsf. Returns a result dict for the GUI."""
    result = {
        "qsf": qsf_path,
        "lss": output_dir / qsf_path.with_suffix(".lss").name,
        "ok": False,
        "error": "",
        "summary": {},
        "lss_stats": {},
        "warnings": [],
        "checks": [],
    }
    report = None
    try:
        report = inspect_one(qsf_path)
        result["summary"] = report["summary"]
        write_input_report(w, qsf_path, report)
    except Exception as exc:
        w.section(f"INPUT: {qsf_path.name}")
        w.write(f"      (inspection failed: {exc})")
        result["checks"].append(("WARN", f"Inspection failed: {exc}"))

    try:
        lss_xml, warnings = convert_qsf_to_lss(qsf_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        result["lss"].write_text(lss_xml, encoding="utf-8")
        result["warnings"] = warnings
        result["ok"] = True

        lss_stats = analyse_lss(result["lss"])
        result["lss_stats"] = lss_stats
        write_output_report(w, result["lss"], warnings, lss_stats)

        if report and lss_stats:
            checks = run_checks(report, lss_stats, warnings)
            result["checks"].extend(checks)
            write_check_report(w, checks)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        w.blank()
        w.write(f"      CONVERSION FAILED: {exc}")

    w.blank()
    w.write(f"  {THIN}")
    return result


def verdict_of(result: dict) -> tuple[str, str]:
    """(status, short text) shown in the overview table."""
    if not result["ok"]:
        return "FAIL", "Conversion failed"
    n_fail = sum(1 for s, _ in result["checks"] if s == "FAIL")
    n_warn = sum(1 for s, _ in result["checks"] if s == "WARN")
    if n_fail:
        return "FAIL", f"{n_fail} check(s) failed, {n_warn} warning(s)"
    if n_warn:
        return "WARN", f"OK with {n_warn} warning(s)"
    return "OK", "OK"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def open_in_file_manager(path: Path) -> None:
    """Open a folder (or reveal a file) with the platform file manager."""
    try:
        if platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showerror(APP_TITLE, f"Could not open {path}:\n{exc}")


def parse_dropped_paths(data: str, widget: tk.Misc) -> list[Path]:
    """tkinterdnd2 delivers a Tcl list; braces protect paths with spaces."""
    try:
        items = widget.tk.splitlist(data)
    except Exception:
        items = data.split()
    return [Path(p) for p in items]


def expand_to_qsf(paths: list[Path]) -> list[Path]:
    """Files stay, folders are searched recursively; only .qsf survives."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(p.rglob("*.qsf")))
        elif p.suffix.lower() == ".qsf":
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
class ConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.files: list[Path] = []
        self.results: dict[str, dict] = {}   # key: str(qsf path)
        self.output_dir: Path | None = None
        self.worker: threading.Thread | None = None
        self.events: queue.Queue = queue.Queue()

        root.title(APP_TITLE)
        root.minsize(860, 560)
        root.geometry("1120x720")
        root.configure(bg=C_BG)

        self._style()
        self._build()
        self._poll_events()

    # -- look -------------------------------------------------------------
    def _style(self) -> None:
        style = ttk.Style(self.root)
        # 'clam' renders the same on Windows and macOS; aqua/vista ignore colours.
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=C_BG, font=("Segoe UI" if not IS_MAC else "Helvetica", 10))
        style.configure("TButton", padding=(10, 5))
        style.configure("Accent.TButton", padding=(14, 6), font=("Segoe UI" if not IS_MAC else "Helvetica", 10, "bold"))
        style.configure("Treeview", rowheight=24, fieldbackground="white", background="white")
        style.configure("Treeview.Heading", font=("Segoe UI" if not IS_MAC else "Helvetica", 10, "bold"))
        style.configure("Muted.TLabel", foreground=C_MUTED)
        style.configure("Title.TLabel", font=("Segoe UI" if not IS_MAC else "Helvetica", 15, "bold"))

    # -- layout -----------------------------------------------------------
    def _build(self) -> None:
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(2, weight=1)

        # Header
        head = ttk.Frame(r, padding=(16, 12, 16, 4))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Qualtrics → LimeSurvey", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="Convert .qsf survey files to .lss", style="Muted.TLabel").pack(side="left", padx=12)

        # Drop zone
        self.drop = tk.Label(
            r,
            text=self._drop_text(),
            bg=C_DROP, fg=C_INFO,
            relief="flat", bd=2,
            highlightthickness=2, highlightbackground=C_BORDER,
            font=("Segoe UI" if not IS_MAC else "Helvetica", 11),
            height=4, cursor="hand2",
        )
        self.drop.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 8))
        self.drop.bind("<Button-1>", lambda e: self.add_files_dialog())
        if HAVE_DND:
            for widget in (self.drop, r):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            self.drop.dnd_bind("<<DropEnter>>", lambda e: self.drop.configure(bg=C_DROP_ACTIVE))
            self.drop.dnd_bind("<<DropLeave>>", lambda e: self.drop.configure(bg=C_DROP))

        # Main area: overview table (left) + detail (right)
        main = ttk.Panedwindow(r, orient="horizontal")
        main.grid(row=2, column=0, sticky="nsew", padx=16)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=1)
        # Give the file table ~45% of the width once the window has a real size.
        self.root.after(50, lambda: main.sashpos(0, int(self.root.winfo_width() * 0.45)))

        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        cols = ("file", "status", "questions", "groups")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("file", text="File")
        self.tree.heading("status", text="Status")
        self.tree.heading("questions", text="Questions")
        self.tree.heading("groups", text="Groups")
        self.tree.column("file", width=260, anchor="w")
        self.tree.column("status", width=150, anchor="w")
        self.tree.column("questions", width=80, anchor="center")
        self.tree.column("groups", width=70, anchor="center")
        self.tree.tag_configure("OK", foreground=C_OK)
        self.tree.tag_configure("WARN", foreground=C_WARN)
        self.tree.tag_configure("FAIL", foreground=C_FAIL)
        self.tree.tag_configure("PENDING", foreground=C_MUTED)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_selected())
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda e: self.remove_selected())

        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.detail = tk.Text(
            right, wrap="word", bg="white", relief="flat", bd=0,
            padx=12, pady=10, state="disabled",
            font=("Consolas" if not IS_MAC else "Menlo", 10),
        )
        self.detail.grid(row=0, column=0, sticky="nsew", padx=(8, 0))
        dsb = ttk.Scrollbar(right, orient="vertical", command=self.detail.yview)
        dsb.grid(row=0, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=dsb.set)
        for tag, colour in (("OK", C_OK), ("WARN", C_WARN), ("FAIL", C_FAIL),
                            ("INFO", C_INFO), ("muted", C_MUTED)):
            self.detail.tag_configure(tag, foreground=colour)
        self.detail.tag_configure("h1", font=("Segoe UI" if not IS_MAC else "Helvetica", 13, "bold"))
        self.detail.tag_configure("h2", font=("Segoe UI" if not IS_MAC else "Helvetica", 10, "bold"),
                                  spacing1=8)
        self._set_detail([("Select files above, then press Convert.\n", "muted")])

        # Output folder row
        outrow = ttk.Frame(r, padding=(16, 8, 16, 0))
        outrow.grid(row=3, column=0, sticky="ew")
        ttk.Label(outrow, text="Output folder:").pack(side="left")
        self.out_var = tk.StringVar(value="(same folder as each .qsf file)")
        ttk.Label(outrow, textvariable=self.out_var, style="Muted.TLabel").pack(side="left", padx=8)
        ttk.Button(outrow, text="Change…", command=self.choose_output_dir).pack(side="left")
        ttk.Button(outrow, text="Open", command=self.open_output).pack(side="left", padx=(6, 0))

        # Buttons
        bar = ttk.Frame(r, padding=(16, 8, 16, 12))
        bar.grid(row=4, column=0, sticky="ew")
        ttk.Button(bar, text="Add files…", command=self.add_files_dialog).pack(side="left")
        ttk.Button(bar, text="Add folder…", command=self.add_folder_dialog).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Remove", command=self.remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="left", padx=(6, 0))
        # Right side first, so the (possibly long) status text can never push
        # the Convert button out of the window.
        self.convert_btn = ttk.Button(bar, text="Convert", style="Accent.TButton", command=self.convert)
        self.convert_btn.pack(side="right")
        self.progress = ttk.Progressbar(bar, mode="determinate", length=160)
        self.status_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.status_var, style="Muted.TLabel").pack(side="left", padx=16, fill="x")

    def _drop_text(self) -> str:
        if HAVE_DND:
            return "Drop .qsf files or folders here\n(or click to browse)"
        return "Click here to choose .qsf files\n(drag & drop needs the tkinterdnd2 package)"

    # -- file list --------------------------------------------------------
    def _on_drop(self, event) -> None:
        self.drop.configure(bg=C_DROP)
        paths = parse_dropped_paths(event.data, self.root)
        self.add_files(expand_to_qsf(paths))
        if not expand_to_qsf(paths):
            self.status_var.set("No .qsf files in what you dropped.")

    def add_files_dialog(self) -> None:
        picked = filedialog.askopenfilenames(
            title="Choose Qualtrics .qsf files",
            filetypes=[("Qualtrics survey", "*.qsf"), ("All files", "*.*")],
        )
        if picked:
            self.add_files([Path(p) for p in picked])

    def add_folder_dialog(self) -> None:
        folder = filedialog.askdirectory(title="Choose a folder containing .qsf files")
        if folder:
            found = expand_to_qsf([Path(folder)])
            if not found:
                messagebox.showinfo(APP_TITLE, "No .qsf files found in that folder.")
            self.add_files(found)

    def add_files(self, paths: list[Path]) -> None:
        added = 0
        for p in paths:
            p = p.resolve()
            if p.suffix.lower() != ".qsf" or p in self.files:
                continue
            self.files.append(p)
            self.tree.insert("", "end", iid=str(p), values=(p.name, "Ready", "", ""), tags=("PENDING",))
            added += 1
        self._update_status(f"{added} file(s) added." if added else "Nothing new added.")

    def remove_selected(self) -> None:
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.files = [f for f in self.files if str(f) != iid]
            self.results.pop(iid, None)
        self._update_status()

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.results.clear()
        self._set_detail([("Select files above, then press Convert.\n", "muted")])
        self._update_status()

    def _update_status(self, extra: str = "") -> None:
        n = len(self.files)
        done = sum(1 for r in self.results.values())
        text = f"{n} file(s)"
        if done:
            text += f", {done} converted"
        if extra:
            text += " — " + extra
        self.status_var.set(text)

    # -- output folder ----------------------------------------------------
    def choose_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Choose the output folder for .lss files")
        if folder:
            self.output_dir = Path(folder)
            self.out_var.set(str(self.output_dir))

    def _output_dir_for(self, qsf: Path) -> Path:
        return self.output_dir if self.output_dir else qsf.parent

    def open_output(self) -> None:
        if self.output_dir:
            open_in_file_manager(self.output_dir)
        elif self.files:
            open_in_file_manager(self.files[0].parent)
        else:
            messagebox.showinfo(APP_TITLE, "No output folder yet — add files first.")

    # -- conversion -------------------------------------------------------
    def convert(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo(APP_TITLE, "Add at least one .qsf file first.")
            return
        files = list(self.files)
        self.results.clear()
        for f in files:
            self.tree.item(str(f), values=(f.name, "Converting…", "", ""), tags=("PENDING",))
        self.convert_btn.state(["disabled"])
        self.progress.configure(maximum=len(files), value=0)
        self.progress.pack(side="right", padx=(0, 10))
        self.status_var.set("Converting…")

        out_for = {f: self._output_dir_for(f) for f in files}
        self.worker = threading.Thread(target=self._worker, args=(files, out_for), daemon=True)
        self.worker.start()

    def _worker(self, files: list[Path], out_for: dict[Path, Path]) -> None:
        w = ReportWriter()
        w.write = lambda text="": w.lines.append(text)  # silent: no console
        w.header("QSF2LSS — Conversion Report")
        w.write(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        w.write(f"  Found {len(files)} .qsf file(s)")

        n_ok = 0
        for f in files:
            try:
                res = convert_file(f, out_for[f], w)
            except Exception:
                res = {"qsf": f, "lss": None, "ok": False, "summary": {}, "lss_stats": {},
                       "warnings": [], "checks": [],
                       "error": traceback.format_exc(limit=1).strip().splitlines()[-1]}
            n_ok += int(res["ok"])
            self.events.put(("file", res))

        w.blank()
        w.write(HEADER)
        w.write(f"  SUMMARY: {n_ok} converted, {len(files) - n_ok} failed, {len(files)} total")
        w.write(HEADER)
        # One report per output folder used
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_paths = []
        for folder in sorted(set(out_for.values()), key=str):
            try:
                folder.mkdir(parents=True, exist_ok=True)
                rp = folder / f"conversion_report_{stamp}.txt"
                w.save(rp)
                report_paths.append(rp)
            except Exception:
                pass
        self.events.put(("done", {"ok": n_ok, "total": len(files), "reports": report_paths}))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "file":
                    self._apply_result(payload)
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _apply_result(self, res: dict) -> None:
        iid = str(res["qsf"])
        self.results[iid] = res
        status, text = verdict_of(res)
        s = res.get("summary", {})
        st = res.get("lss_stats", {})
        q = st.get("questions", s.get("n_questions", ""))
        g = st.get("groups", s.get("n_blocks", ""))
        if self.tree.exists(iid):
            self.tree.item(iid, values=(res["qsf"].name, text, q, g), tags=(status,))
        self.progress.step(1)
        sel = self.tree.selection()
        if not sel or sel[0] == iid:
            self.tree.selection_set(iid)
            self._show_result(res)

    def _finish(self, info: dict) -> None:
        self.convert_btn.state(["!disabled"])
        self.progress.pack_forget()
        failed = info["total"] - info["ok"]
        msg = f"Done: {info['ok']} converted"
        if failed:
            msg += f", {failed} failed"
        self._update_status(msg)

    # -- detail pane ------------------------------------------------------
    def _show_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        res = self.results.get(sel[0])
        if res:
            self._show_result(res)
        else:
            self._set_detail([(f"{Path(sel[0]).name}\n", "h1"),
                              ("Not converted yet. Press Convert.\n", "muted")])

    def _set_detail(self, chunks: list[tuple[str, str]]) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        for text, tag in chunks:
            self.detail.insert("end", text, tag)
        self.detail.configure(state="disabled")

    def _show_result(self, res: dict) -> None:
        s = res.get("summary", {})
        st = res.get("lss_stats", {})
        chunks: list[tuple[str, str]] = []
        chunks.append((f"{res['qsf'].name}\n", "h1"))
        status, text = verdict_of(res)
        chunks.append((f"{text}\n", status))
        if res.get("error"):
            chunks.append((f"\n{res['error']}\n", "FAIL"))
        if res.get("lss"):
            chunks.append((f"→ {res['lss']}\n", "muted"))

        if s:
            chunks.append(("\nInput (Qualtrics)\n", "h2"))
            chunks.append((f"  Survey: {s.get('survey_name', '—')}   Language: {s.get('language', '—')}\n", ""))
            chunks.append((f"  Questions: {s.get('n_questions', 0)}   Blocks: {s.get('n_blocks', 0)}"
                           f"   Risk score: {s.get('migration_risk_score', 0)}\n", ""))
            types = s.get("question_types", {})
            if types:
                chunks.append(("  Types: " + ", ".join(
                    f"{t} ×{c}" for t, c in sorted(types.items(), key=lambda x: -x[1])) + "\n", ""))
            feats = []
            for key, label in (("n_questions_with_display_logic", "display logic"),
                               ("n_questions_with_validation", "validation"),
                               ("n_piped_text_occurrences", "piped text"),
                               ("n_questions_with_javascript", "JavaScript"),
                               ("n_branches", "branches"),
                               ("n_randomizers", "randomizers"),
                               ("n_embedded_data_blocks", "embedded data")):
                if s.get(key):
                    feats.append(f"{label} {s[key]}")
            if feats:
                chunks.append(("  Features: " + ", ".join(feats) + "\n", ""))

        if st:
            chunks.append(("\nOutput (LimeSurvey)\n", "h2"))
            chunks.append((f"  Groups: {st.get('groups', 0)}   Questions: {st.get('questions', 0)}"
                           f"   Subquestions: {st.get('subquestions', 0)}   Answers: {st.get('answers', 0)}\n", ""))
            types = st.get("question_types", {})
            if types:
                chunks.append(("  Types: " + ", ".join(
                    f"{LS_TYPE_NAMES.get(c, c)} ×{n}"
                    for c, n in sorted(types.items(), key=lambda x: -x[1])) + "\n", ""))

        if res.get("checks"):
            chunks.append(("\nVerification\n", "h2"))
            sym = {"OK": "✓", "WARN": "!", "FAIL": "✗", "INFO": "i"}
            for stat, msg in res["checks"]:
                chunks.append((f"  {sym.get(stat, ' ')} {msg}\n", stat))

        if res.get("warnings"):
            chunks.append((f"\nConverter warnings ({len(res['warnings'])})\n", "h2"))
            for wmsg in res["warnings"]:
                chunks.append((f"  • {wmsg}\n", "WARN"))

        self._set_detail(chunks)


# ---------------------------------------------------------------------------
def _enable_high_dpi() -> None:
    """Windows: without this Tk is bitmap-scaled and looks blurry at 125%/150%.
    Must run before the Tk root is created. No-op elsewhere."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor v2 (Win 8.1+)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()         # Vista+ fallback
    except Exception:
        pass


def main() -> int:
    _enable_high_dpi()
    root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
    if platform.system() == "Windows":
        # Scale Tk's point-to-pixel ratio to the real DPI so fonts stay readable.
        try:
            dpi = root.winfo_fpixels("1i")
            root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
    app = ConverterApp(root)
    # Files given on the command line (or via "Open with…") are pre-loaded.
    initial = expand_to_qsf([Path(a) for a in sys.argv[1:]])
    if initial:
        app.add_files(initial)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
