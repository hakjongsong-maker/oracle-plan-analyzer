"""Oracle Plan Analyzer — Main Application (tkinter)."""
from __future__ import annotations
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
from typing import List, Optional, Dict

from db_manager import DBManager, DBConfig
from plan_analyzer import explain_plan, PlanResult
from tuning_advisor import analyze_plans
from tns_parser import get_aliases


# ── Color palette ─────────────────────────────────────────────────────────────
BG_ROOT       = "#f0f2f5"
BG_CARD       = "#ffffff"
BG_SQL        = "#1e1e2e"
FG_SQL        = "#cdd6f4"
BG_PLAN       = "#0d1117"
FG_PLAN       = "#e6edf3"
BG_CONNECTED  = "#22c55e"
BG_DISCONNECTED = "#94a3b8"
BG_ERROR      = "#ef4444"
BG_BUTTON     = "#3b82f6"
BG_BUTTON_DANGER = "#ef4444"
BG_BUTTON_RUN = "#10b981"
FG_WHITE      = "#ffffff"
BORDER_COLOR  = "#e2e8f0"

# Plan hash color bands (up to 6 distinct groups)
HASH_COLORS = ["#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#84cc16"]
HASH_FG     = [FG_WHITE,  "#1e1e2e", FG_WHITE,   FG_WHITE,   FG_WHITE,   "#1e1e2e"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _scrolled_text(parent, **kwargs) -> tk.Text:
    frame = tk.Frame(parent, bg=kwargs.pop("bg", BG_PLAN))
    text = tk.Text(frame, **kwargs)
    sb = tk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=sb.set)
    sb_x = tk.Scrollbar(frame, orient="horizontal", command=text.xview)
    text.configure(xscrollcommand=sb_x.set, wrap="none")
    text.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")
    sb_x.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, text


def _make_button(parent, text, command, bg=BG_BUTTON, width=12):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=FG_WHITE, relief="flat", bd=0,
        padx=8, pady=4, cursor="hand2",
        activebackground=bg, activeforeground=FG_WHITE,
        font=("Segoe UI", 9, "bold"), width=width,
    )
    return btn


# ── DB Connection Card ─────────────────────────────────────────────────────────
class DBCard(tk.LabelFrame):
    def __init__(self, parent, db_id: int, manager: DBManager, on_status_change, **kwargs):
        kwargs.setdefault("bg", BG_CARD)
        super().__init__(parent, text=f" DB {db_id + 1} ",
                         font=("Segoe UI", 9, "bold"), fg="#475569",
                         relief="solid", bd=1, **kwargs)
        self.db_id = db_id
        self.manager = manager
        self.on_status_change = on_status_change

        self._alias = tk.StringVar()
        self._label = tk.StringVar(value=f"DB{db_id + 1}")
        self._user = tk.StringVar()
        self._pwd = tk.StringVar()
        # tns_file은 App에서 set_tns_file()로 주입
        self._tns_file: str = ""

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 4, "pady": 2}

        # Row 0: Label + 상태 LED
        tk.Label(self, text="이름", bg=BG_CARD, font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self._label, width=14, font=("Segoe UI", 8)).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        self._status_canvas = tk.Canvas(self, width=14, height=14, bg=BG_CARD, highlightthickness=0)
        self._status_canvas.grid(row=0, column=3, sticky="e", **pad)
        self._status_oval = self._status_canvas.create_oval(2, 2, 12, 12, fill=BG_DISCONNECTED, outline="")

        # Row 1: Alias dropdown
        tk.Label(self, text="TNS Alias", bg=BG_CARD, font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w", **pad)
        self._alias_cb = ttk.Combobox(self, textvariable=self._alias, width=18,
                                      font=("Segoe UI", 8), state="readonly")
        self._alias_cb.grid(row=1, column=1, columnspan=3, sticky="ew", **pad)

        # Row 2: Username
        tk.Label(self, text="사용자", bg=BG_CARD, font=("Segoe UI", 8)).grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self._user, width=20, font=("Segoe UI", 8)).grid(row=2, column=1, columnspan=3, sticky="ew", **pad)

        # Row 3: Password
        tk.Label(self, text="비밀번호", bg=BG_CARD, font=("Segoe UI", 8)).grid(row=3, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self._pwd, width=20, show="●",
                 font=("Segoe UI", 8)).grid(row=3, column=1, columnspan=3, sticky="ew", **pad)

        # Row 4: Connect / Disconnect buttons
        btn_frame = tk.Frame(self, bg=BG_CARD)
        btn_frame.grid(row=4, column=0, columnspan=4, pady=(4, 2))
        self._conn_btn = _make_button(btn_frame, "접속", self._connect, bg=BG_BUTTON, width=7)
        self._conn_btn.pack(side="left", padx=2)
        self._disc_btn = _make_button(btn_frame, "접속 종료", self._disconnect, bg=BG_BUTTON_DANGER, width=8)
        self._disc_btn.pack(side="left", padx=2)
        self._disc_btn.config(state="disabled")

        self.columnconfigure(1, weight=1)

    # ── 공통 TNS 주입 (App에서 호출) ───────────────────────────────────────────
    def set_aliases(self, tns_file: str, aliases: List[str]):
        self._tns_file = tns_file
        current = self._alias.get()
        self._alias_cb.config(values=aliases)
        if current in aliases:
            self._alias.set(current)
        elif aliases:
            self._alias_cb.current(0)

    # ── Connect ────────────────────────────────────────────────────────────────
    def _connect(self):
        cfg = DBConfig(
            label=self._label.get() or f"DB{self.db_id + 1}",
            tns_file=self._tns_file,
            tns_alias=self._alias.get(),
            username=self._user.get(),
            password=self._pwd.get(),
        )
        self.manager.set_config(self.db_id, cfg)
        self._set_status("connecting")
        self._conn_btn.config(state="disabled")

        def _do():
            try:
                self.manager.connect(self.db_id)
                self.after(0, lambda: self._set_status("connected"))
                self.after(0, lambda: self.on_status_change(self.db_id, True, None))
            except Exception as e:
                self.after(0, lambda err=e: self._set_status("error", str(err)))
                self.after(0, lambda err=e: self.on_status_change(self.db_id, False, str(err)))

        threading.Thread(target=_do, daemon=True).start()

    def _disconnect(self):
        self.manager.disconnect(self.db_id)
        self._set_status("disconnected")
        self.on_status_change(self.db_id, False, None)

    def _set_status(self, status: str, detail: str = ""):
        color_map = {
            "connected":    BG_CONNECTED,
            "disconnected": BG_DISCONNECTED,
            "connecting":   "#f59e0b",
            "error":        BG_ERROR,
        }
        color = color_map.get(status, BG_DISCONNECTED)
        self._status_canvas.itemconfig(self._status_oval, fill=color)

        if status == "connected":
            self.config(fg="#16a34a")
            self._conn_btn.config(state="disabled")
            self._disc_btn.config(state="normal")
        elif status == "error":
            self.config(fg="#dc2626")
            self._conn_btn.config(state="normal")
            self._disc_btn.config(state="disabled")
            if detail:
                messagebox.showerror(f"DB {self.db_id + 1} 접속 오류", detail)
        else:
            self.config(fg="#475569")
            self._conn_btn.config(state="normal")
            self._disc_btn.config(state="disabled")

    def get_label(self) -> str:
        return self._label.get() or f"DB{self.db_id + 1}"


# ── Main Application Window ───────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Oracle Plan Analyzer")
        self.geometry("1280x900")
        self.minsize(900, 700)
        self.configure(bg=BG_ROOT)

        self._manager = DBManager()
        self._cards: List[DBCard] = []
        self._plan_results: List[PlanResult] = []
        self._hash_color_map: Dict[str, int] = {}   # hash → color index

        self._build_ui()

    # ── UI layout ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Title bar ──────────────────────────────────────────────────────────
        title_frame = tk.Frame(self, bg="#1e293b", height=42)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="Oracle Plan Analyzer",
                 bg="#1e293b", fg=FG_WHITE,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=16, pady=8)

        # ── DB cards (3 × 2) ──────────────────────────────────────────────────
        db_outer = tk.LabelFrame(self, text=" DB 접속 설정 (최대 6개) ",
                                 bg=BG_ROOT, font=("Segoe UI", 9, "bold"),
                                 fg="#334155", relief="flat")
        db_outer.pack(fill="x", padx=10, pady=(6, 0))

        # ── 공통 tnsnames.ora 설정 바 ──────────────────────────────────────────
        tns_bar = tk.Frame(db_outer, bg="#e8f0fe", bd=0)
        tns_bar.pack(fill="x", padx=4, pady=(4, 0))

        tk.Label(tns_bar, text="tnsnames.ora (공통):", bg="#e8f0fe",
                 font=("Segoe UI", 9, "bold"), fg="#1e40af").pack(side="left", padx=(8, 4), pady=4)

        self._tns_path_var = tk.StringVar()
        tns_entry = tk.Entry(tns_bar, textvariable=self._tns_path_var,
                             width=55, font=("Segoe UI", 9), state="readonly",
                             readonlybackground="#ffffff", fg="#1e293b")
        tns_entry.pack(side="left", padx=2, pady=4)

        _make_button(tns_bar, "파일 선택", self._browse_tns_global,
                     bg="#3b82f6", width=9).pack(side="left", padx=2)
        _make_button(tns_bar, "↻ 새로고침", self._reload_aliases_global,
                     bg="#64748b", width=9).pack(side="left", padx=2)

        self._tns_alias_count_label = tk.Label(tns_bar, text="", bg="#e8f0fe",
                                               font=("Segoe UI", 8), fg="#64748b")
        self._tns_alias_count_label.pack(side="left", padx=8)

        # ── 카드 그리드 ────────────────────────────────────────────────────────
        db_grid = tk.Frame(db_outer, bg=BG_ROOT)
        db_grid.pack(fill="x", padx=4, pady=4)

        for i in range(DBManager.MAX_DB):
            card = DBCard(db_grid, i, self._manager, self._on_db_status_change,
                          bg=BG_CARD, padx=4, pady=4)
            row, col = divmod(i, 3)
            card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            db_grid.columnconfigure(col, weight=1)
            self._cards.append(card)

        # ── SQL editor ────────────────────────────────────────────────────────
        sql_frame = tk.LabelFrame(self, text=" SQL 입력 ",
                                  bg=BG_ROOT, font=("Segoe UI", 9, "bold"),
                                  fg="#334155", relief="flat")
        sql_frame.pack(fill="both", padx=10, pady=(6, 0))

        sql_container, self._sql_text = _scrolled_text(
            sql_frame,
            bg=BG_SQL, fg=FG_SQL, insertbackground=FG_SQL,
            font=("Consolas", 11), height=8,
            relief="flat", bd=0, undo=True,
        )
        sql_container.pack(fill="both", expand=True, padx=4, pady=4)

        # Syntax highlighting on key release
        self._sql_text.bind("<KeyRelease>", self._highlight_sql)

        # Define SQL keyword tags
        self._sql_text.tag_configure("keyword", foreground="#89b4fa")
        self._sql_text.tag_configure("string",  foreground="#a6e3a1")
        self._sql_text.tag_configure("comment", foreground="#6c7086")

        # Run button
        run_frame = tk.Frame(sql_frame, bg=BG_ROOT)
        run_frame.pack(fill="x", padx=4, pady=(0, 4))
        self._run_btn = _make_button(run_frame, "▶  실행계획 조회", self._run_explain,
                                     bg=BG_BUTTON_RUN, width=20)
        self._run_btn.pack(side="right", padx=4)
        _make_button(run_frame, "SQL 지우기", self._clear_sql,
                     bg="#64748b", width=10).pack(side="right", padx=4)
        self._status_label = tk.Label(run_frame, text="", bg=BG_ROOT,
                                      font=("Segoe UI", 9), fg="#64748b")
        self._status_label.pack(side="left", padx=4)

        # ── Plan notebook ─────────────────────────────────────────────────────
        plan_frame = tk.LabelFrame(self, text=" 실행계획 (Execution Plan) ",
                                   bg=BG_ROOT, font=("Segoe UI", 9, "bold"),
                                   fg="#334155", relief="flat")
        plan_frame.pack(fill="both", expand=True, padx=10, pady=(6, 6))

        self._nb = ttk.Notebook(plan_frame)
        self._nb.pack(fill="both", expand=True, padx=4, pady=4)

        # Tabs: one per DB + Compare + Tuning
        self._plan_tabs: Dict[int, tk.Text] = {}
        self._plan_tab_frames: Dict[int, tk.Frame] = {}
        self._hash_labels: Dict[int, tk.Label] = {}

        for i in range(DBManager.MAX_DB):
            tab_frame = tk.Frame(self._nb, bg=BG_PLAN)
            self._nb.add(tab_frame, text=f"  DB {i+1}  ")
            self._plan_tab_frames[i] = tab_frame

            # Hash badge
            hdr = tk.Frame(tab_frame, bg=BG_PLAN)
            hdr.pack(fill="x", padx=4, pady=(4, 0))
            tk.Label(hdr, text="Plan hash value:", bg=BG_PLAN,
                     fg="#64748b", font=("Segoe UI", 9)).pack(side="left")
            hl = tk.Label(hdr, text="—", bg=BG_PLAN, fg="#94a3b8",
                          font=("Consolas", 10, "bold"), padx=8, pady=2)
            hl.pack(side="left", padx=4)
            self._hash_labels[i] = hl

            inner, plan_text = _scrolled_text(
                tab_frame, bg=BG_PLAN, fg=FG_PLAN,
                font=("Consolas", 10), state="disabled",
                relief="flat", bd=0,
            )
            inner.pack(fill="both", expand=True, padx=4, pady=4)
            self._plan_tabs[i] = plan_text

        # Compare tab
        self._compare_frame = tk.Frame(self._nb, bg=BG_PLAN)
        self._nb.add(self._compare_frame, text="  비교  ")
        _, self._compare_text = _scrolled_text(
            self._compare_frame, bg=BG_PLAN, fg=FG_PLAN,
            font=("Consolas", 10), state="disabled", relief="flat", bd=0,
        )
        self._compare_text.master.pack(fill="both", expand=True, padx=4, pady=4)

        # Tuning tab
        self._tuning_frame = tk.Frame(self._nb, bg=BG_PLAN)
        self._nb.add(self._tuning_frame, text="  튜닝 가이드  ")
        _, self._tuning_text = _scrolled_text(
            self._tuning_frame, bg="#0f172a", fg="#e2e8f0",
            font=("Consolas", 10), state="disabled", relief="flat", bd=0,
        )
        self._tuning_text.master.pack(fill="both", expand=True, padx=4, pady=4)
        self._tuning_text.tag_configure("warn",    foreground="#fbbf24", font=("Consolas", 10, "bold"))
        self._tuning_text.tag_configure("ok",      foreground="#4ade80", font=("Consolas", 10, "bold"))
        self._tuning_text.tag_configure("hint",    foreground="#60a5fa")
        self._tuning_text.tag_configure("section", foreground="#c084fc", font=("Consolas", 10, "bold"))
        self._tuning_text.tag_configure("code",    foreground="#fb923c")

        self._update_tab_titles()

    # ── 공통 TNS 파일 처리 ────────────────────────────────────────────────────
    def _browse_tns_global(self):
        path = filedialog.askopenfilename(
            title="tnsnames.ora 파일 선택",
            filetypes=[("TNS Names", "tnsnames.ora"), ("All Files", "*.*")],
        )
        if path:
            self._tns_path_var.set(path)
            self._reload_aliases_global()

    def _reload_aliases_global(self):
        path = self._tns_path_var.get()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("경고", "유효한 tnsnames.ora 파일 경로를 먼저 선택하세요.")
            return
        aliases = get_aliases(path)
        if not aliases:
            messagebox.showwarning("경고", f"tnsnames.ora에서 Alias를 찾을 수 없습니다.\n파일: {path}")
            return
        for card in self._cards:
            card.set_aliases(path, aliases)
        self._tns_alias_count_label.config(
            text=f"Alias {len(aliases)}개 로드됨",
            fg="#16a34a",
        )

    # ── DB status callback ─────────────────────────────────────────────────────
    def _on_db_status_change(self, db_id: int, connected: bool, error: Optional[str]):
        self._update_tab_titles()

    def _update_tab_titles(self):
        for i, card in enumerate(self._cards):
            lbl = card.get_label()
            connected = self._manager.is_connected(i)
            dot = "●" if connected else "○"
            self._nb.tab(i, text=f"  {dot} {lbl}  ")

    # ── SQL editor ─────────────────────────────────────────────────────────────
    def _clear_sql(self):
        self._sql_text.delete("1.0", "end")

    SQL_KEYWORDS = (
        "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "EXISTS",
        "INNER", "OUTER", "LEFT", "RIGHT", "FULL", "JOIN", "ON",
        "GROUP", "BY", "HAVING", "ORDER", "UNION", "ALL", "DISTINCT",
        "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
        "CREATE", "TABLE", "INDEX", "VIEW", "ALTER", "DROP",
        "EXPLAIN", "PLAN", "WITH", "AS", "CASE", "WHEN", "THEN", "ELSE", "END",
        "NULL", "IS", "BETWEEN", "LIKE", "ROWNUM", "ROWID",
        "BEGIN", "END", "DECLARE", "PROCEDURE", "FUNCTION",
    )

    def _highlight_sql(self, event=None):
        import re as _re
        text = self._sql_text
        text.tag_remove("keyword", "1.0", "end")
        text.tag_remove("comment", "1.0", "end")
        content = text.get("1.0", "end")
        # Keywords
        for kw in self.SQL_KEYWORDS:
            for m in _re.finditer(rf"\b{kw}\b", content, _re.IGNORECASE):
                start = f"1.0+{m.start()}c"
                end   = f"1.0+{m.end()}c"
                text.tag_add("keyword", start, end)
        # Line comments
        for m in _re.finditer(r"--[^\n]*", content):
            text.tag_add("comment", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    # ── Run explain plan ───────────────────────────────────────────────────────
    def _run_explain(self):
        sql = self._sql_text.get("1.0", "end").strip()
        if not sql:
            messagebox.showwarning("경고", "SQL을 입력하세요.")
            return

        connected_ids = self._manager.connected_ids()
        if not connected_ids:
            messagebox.showwarning("경고", "접속된 DB가 없습니다.\n먼저 DB에 접속하세요.")
            return

        self._run_btn.config(state="disabled")
        self._status_label.config(text="실행계획 조회 중...", fg="#f59e0b")
        self._clear_plan_views()

        def _do():
            results = []
            for db_id in connected_ids:
                conn = self._manager.get_connection(db_id)
                label = self._cards[db_id].get_label()
                cfg = self._manager.get_config(db_id)
                if cfg:
                    label = cfg.label or label
                result = explain_plan(conn, sql, db_id, label)
                results.append(result)
            self.after(0, lambda: self._show_results(results))

        threading.Thread(target=_do, daemon=True).start()

    def _clear_plan_views(self):
        for i in range(DBManager.MAX_DB):
            self._set_plan_text(i, "")
            self._hash_labels[i].config(text="—", bg=BG_PLAN, fg="#94a3b8")
            self._nb.tab(i, state="normal")
        self._set_text(self._compare_text, "")
        self._set_text(self._tuning_text, "")

    def _show_results(self, results: List[PlanResult]):
        self._plan_results = results

        # Build hash → color index mapping
        self._hash_color_map = {}
        color_idx = 0
        hashes_seen = []
        for r in results:
            if r.plan_hash and r.plan_hash not in self._hash_color_map:
                self._hash_color_map[r.plan_hash] = color_idx % len(HASH_COLORS)
                hashes_seen.append(r.plan_hash)
                color_idx += 1

        all_same = len(set(r.plan_hash for r in results if r.plan_hash)) <= 1

        for r in results:
            db_id = r.db_id
            if r.success:
                self._set_plan_text(db_id, r.plan_text)
                if r.plan_hash:
                    cidx = self._hash_color_map.get(r.plan_hash, 0)
                    bg = HASH_COLORS[cidx] if not all_same else BG_CONNECTED
                    fg = HASH_FG[cidx] if not all_same else FG_WHITE
                    self._hash_labels[db_id].config(
                        text=r.plan_hash, bg=bg, fg=fg
                    )
            else:
                self._set_plan_text(db_id, f"[오류]\n{r.error or '알 수 없는 오류'}")
                self._hash_labels[db_id].config(text="ERROR", bg=BG_ERROR, fg=FG_WHITE)

        # Update DB tab colors
        for r in results:
            if r.success and r.plan_hash:
                cidx = self._hash_color_map.get(r.plan_hash, 0)
                lbl = self._cards[r.db_id].get_label()
                dot = "●"
                if not all_same:
                    self._nb.tab(r.db_id, text=f"  {dot} {lbl}  ")

        self._build_compare_view(results)
        self._build_tuning_view(results)

        # Switch to Compare tab if plans differ
        if not all_same:
            self._nb.select(DBManager.MAX_DB)  # Compare tab index
        else:
            self._nb.select(DBManager.MAX_DB + 1)  # Tuning tab

        self._run_btn.config(state="normal")
        ok_count = sum(1 for r in results if r.success)
        self._status_label.config(
            text=f"완료: {ok_count}/{len(results)}개 DB 조회됨",
            fg="#4ade80" if all_same else "#fbbf24"
        )

    def _build_compare_view(self, results: List[PlanResult]):
        lines = []
        hashes = {r.plan_hash for r in results if r.success and r.plan_hash}
        if len(hashes) == 1:
            lines.append("✅  모든 DB의 Plan hash value가 동일합니다: " + next(iter(hashes)))
        else:
            lines.append("⚠️  Plan hash value가 다른 DB가 있습니다!\n")
            for r in results:
                if r.success:
                    cidx = self._hash_color_map.get(r.plan_hash, 0)
                    lines.append(f"[{r.db_label}]  Plan hash: {r.plan_hash}")
            lines.append("")

        lines.append("=" * 70)
        for r in results:
            if r.success:
                lines.append(f"\n[{r.db_label}]  ({'Plan hash: ' + r.plan_hash if r.plan_hash else '오류'})")
                lines.append("─" * 70)
                lines.append(r.plan_text)
            else:
                lines.append(f"\n[{r.db_label}]  [ERROR: {r.error}]")

        self._set_text(self._compare_text, "\n".join(lines))

        # Color the hash badges in compare view
        text = self._compare_text
        text.config(state="normal")
        text.tag_configure("hash_diff", foreground="#fbbf24", font=("Consolas", 10, "bold"))
        text.tag_configure("hash_same", foreground="#4ade80", font=("Consolas", 10, "bold"))
        text.config(state="disabled")

    def _build_tuning_view(self, results: List[PlanResult]):
        successful = [r for r in results if r.success]
        if not successful:
            self._set_text(self._tuning_text, "조회된 실행계획이 없습니다.")
            return

        advice = analyze_plans(successful)
        text = self._tuning_text
        text.config(state="normal")
        text.delete("1.0", "end")

        import re as _re
        for line in advice.splitlines():
            tag = None
            if line.startswith("✅"):
                tag = "ok"
            elif line.startswith("⚠️") or line.startswith("WARNING"):
                tag = "warn"
            elif line.startswith("💡") or line.startswith("🔧") or line.startswith("🔍") or line.startswith("📋"):
                tag = "section"
            elif "/*+" in line or "EXEC" in line or "BEGIN" in line:
                tag = "code"
            elif "INDEX" in line or "HINT" in line or "hint" in line.lower():
                tag = "hint"
            if tag:
                text.insert("end", line + "\n", tag)
            else:
                text.insert("end", line + "\n")

        text.config(state="disabled")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _set_plan_text(self, db_id: int, content: str):
        self._set_text(self._plan_tabs[db_id], content)

    def _set_text(self, widget: tk.Text, content: str):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.config(state="disabled")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Check dependencies
    try:
        import oracledb  # noqa: F401
    except ImportError:
        import tkinter.messagebox as _mb
        _root = tk.Tk()
        _root.withdraw()
        _mb.showerror(
            "패키지 누락",
            "oracledb 패키지가 설치되지 않았습니다.\n\n"
            "터미널에서 아래 명령어를 실행하세요:\n\n"
            "  pip install oracledb",
        )
        sys.exit(1)

    app = App()
    app.mainloop()
