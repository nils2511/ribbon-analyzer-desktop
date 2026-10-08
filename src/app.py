"""
Main Application GUI
====================
Primary window with:
- Project setup (folder selection, API key, scale)
- Folder tree showing discovered images by age/genotype
- Batch analysis queue with progress
- Summary dashboard
- Review trigger
- Export panel
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import os
from pathlib import Path
from typing import Optional
import time

import anthropic

from .config import (
    IMAGE_EXTENSIONS, DEFAULT_SCALE_PX, DEFAULT_SCALE_NM, DEFAULT_SCALE_UNIT,
    UI_BG, UI_PANEL, UI_ACCENT, UI_ACCENT2, UI_TEXT, UI_TEXT_DIM, UI_BORDER,
    MORPHOLOGY_COLORS,
)
from .models import Project, ImageResult, RibbonAnnotation
from .engine import analyze_image, parse_folder_name, fetch_literature, save_training_example, log_improvement
from .review_panel import ReviewPanel
from .export_module import export_all
from .knowledge_base import build_or_update_knowledge_base, get_kb_summary, get_knowledge_context, KB_PATH


def _btn(parent, text, command, bg="#2a3a5a", fg="#e0e0e0", font=None, **kw):
    """Button helper that always sets correct macOS-safe colors."""
    f = font or ("Helvetica", 10)
    return tk.Button(parent, text=text, command=command,
                     bg=bg, fg=fg, font=f,
                     activebackground=bg, activeforeground=fg,
                     highlightbackground=bg,
                     relief="flat", **kw)


class RibbonAnalyzerApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Ribbon Synapse EM Analyzer — Nils Hampel, FAU Erlangen-Nürnberg")
        self.root.geometry("1440x900")
        self.root.minsize(1100, 700)
        self.root.configure(bg=UI_BG)

        self.project: Optional[Project] = None
        self.client: Optional[anthropic.Anthropic] = None
        self.analysis_queue: queue.Queue = queue.Queue()
        self.is_analyzing = False
        self._review_index = 0
        self._log_lines = []
        self._kb: Optional[dict] = None          # loaded knowledge base
        self._kb_ready = False                    # True once KB is usable
        self._left_sidebar_open = True
        self._project_path = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_queue()
        # KB build is now button-triggered only (Literature tab)
        # Check if KB already exists and load it silently
        from .knowledge_base import KB_PATH, _load_kb, get_kb_summary
        if KB_PATH.exists():
            self._kb = _load_kb()
            self._kb_ready = True
            self._log(f'Loaded existing KB: {get_kb_summary(self._kb)}')
        else:
            self._log('No knowledge base found. Go to Literature tab to build one.')

    def run(self):
        self.root.mainloop()

    # ─── UI Construction ──────────────────────────────────────────────

    def _build_ui(self):
        # ── ttk button styles (macOS fix) ────────────────────────
        style = ttk.Style()
        style.theme_use("clam")
        for name, bg, fg, abg in [
            ("Green.TButton",  "#1D9E75", "white",   "#0f6e56"),
            ("Blue.TButton",   "#1a5fa8", "white",   "#0d4a8a"),
            ("Purple.TButton", "#533AB7", "white",   "#3a2a8a"),
            ("Red.TButton",    "#6B1A0A", "white",   "#4a1008"),
            ("Dark.TButton",   "#2a3a5a", "#e0e0e0", "#1a2a3a"),
            ("Gray.TButton",   "#333333", "#e0e0e0", "#222222"),
        ]:
            style.configure(name, background=bg, foreground=fg, borderwidth=0,
                            font=("Helvetica", 10), padding=(8, 4))
            style.map(name, background=[("active", abg)], foreground=[("active", fg)])
        style.configure("BigGreen.TButton", background="#1D9E75", foreground="white",
                        borderwidth=0, font=("Helvetica", 11, "bold"), padding=(14, 6))
        style.map("BigGreen.TButton",
                  background=[("active", "#0f6e56")], foreground=[("active", "white")])
        style.configure("BigBlue.TButton", background="#1a5fa8", foreground="white",
                        borderwidth=0, font=("Helvetica", 11, "bold"), padding=(14, 6))
        style.map("BigBlue.TButton",
                  background=[("active", "#0d4a8a")], foreground=[("active", "white")])
        style.configure("BigPurple.TButton", background="#533AB7", foreground="white",
                        borderwidth=0, font=("Helvetica", 11), padding=(14, 6))
        style.map("BigPurple.TButton",
                  background=[("active", "#3a2a8a")], foreground=[("active", "white")])

        # Menu bar
        menubar = tk.Menu(self.root, bg=UI_PANEL, fg=UI_TEXT, tearoff=0)
        file_menu = tk.Menu(menubar, tearoff=0, bg=UI_PANEL, fg=UI_TEXT)
        file_menu.add_command(label="New Project", command=self._new_project)
        file_menu.add_command(label="Open Project (.json)", command=self._open_project)
        file_menu.add_command(label="Save Project", command=self._save_project)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

        # Top title bar
        title_bar = tk.Frame(self.root, bg="#10171d", pady=8)
        title_bar.pack(fill="x")
        self._sidebar_btn = tk.Button(
            title_bar,
            text="☰",
            command=self._toggle_left_sidebar,
            bg="#121a2f",
            fg="#e7f0ff",
            activebackground="#1a2442",
            activeforeground="#ffffff",
            highlightbackground="#121a2f",
            relief="flat",
            font=("Helvetica", 14, "bold"),
            padx=10,
            pady=3,
            cursor="hand2",
        )
        self._sidebar_btn.pack(side="left", padx=(10, 6))
        tk.Label(title_bar, text="  Ribbon Synapse EM Analyzer",
                 bg="#10171d", fg=UI_TEXT,
                 font=("Helvetica", 14, "bold")).pack(side="left")
        tk.Label(title_bar, text="  Manual annotation & measurement",
                 bg="#10171d", fg=UI_TEXT_DIM,
                 font=("Helvetica", 10)).pack(side="left")

        # Main layout: left sidebar + center/right
        paned = tk.PanedWindow(self.root, orient="horizontal",
                                bg=UI_BG, sashwidth=4, sashrelief="flat")
        paned.pack(fill="both", expand=True)
        self.main_paned = paned

        # ─── Left panel: setup + file tree ────────────────────────
        left_frame = tk.Frame(paned, bg=UI_PANEL)
        self.left_frame = left_frame
        paned.add(left_frame, minsize=340, width=340)
        self.root.after(300, lambda: paned.sash_place(0, 340 if self._left_sidebar_open else 44, 0))
        self.left_content = tk.Frame(left_frame, bg=UI_PANEL)
        self.left_content.pack(fill="both", expand=True)

        self._build_setup_panel(self.left_content)
        self._build_file_tree(self.left_content)

        # ─── Right panel: tabs ────────────────────────────────────
        right_frame = tk.Frame(paned, bg=UI_BG)
        paned.add(right_frame, minsize=600)

        self.notebook = ttk.Notebook(right_frame)
        self.notebook.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=UI_BG, borderwidth=0)
        # Button styles for macOS compatibility
        for sname, bg, fg, abg in [
            ("App.Green.TButton",  "#22a879", "white",   "#138564"),
            ("App.Blue.TButton",   "#2267b5", "white",   "#174f96"),
            ("App.Purple.TButton", "#6a49c8", "white",   "#5237ab"),
            ("App.Dark.TButton",   "#2e324d", "#eef4ff", "#232742"),
        ]:
            style.configure(sname, background=bg, foreground=fg, borderwidth=0,
                            font=("Helvetica", 10, "bold"), padding=(14, 8))
            style.map(sname, background=[("active", abg), ("pressed", abg)], foreground=[("active", fg), ("pressed", fg)])
        style.configure("App.BigGreen.TButton", background="#22a879", foreground="white",
                        borderwidth=0, font=("Helvetica", 10, "bold"), padding=(16, 9))
        style.map("App.BigGreen.TButton", background=[("active", "#0f6e56")], foreground=[("active", "white")])
        style.configure("App.BigBlue.TButton", background="#2267b5", foreground="white",
                        borderwidth=0, font=("Helvetica", 11, "bold"), padding=(18, 9))
        style.map("App.BigBlue.TButton", background=[("active", "#0d4a8a")], foreground=[("active", "white")])
        style.configure("TNotebook.Tab", background=UI_PANEL, foreground=UI_TEXT_DIM,
                        padding=[12, 6], font=("Helvetica", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", UI_BG)],
                  foreground=[("selected", UI_TEXT)])

        # Queue tab
        queue_frame = tk.Frame(self.notebook, bg=UI_BG)
        self.notebook.add(queue_frame, text="  Detection · experimental  ")
        self._build_queue_tab(queue_frame)

        # Dashboard tab
        dash_frame = tk.Frame(self.notebook, bg=UI_BG)
        self.notebook.add(dash_frame, text="  Dashboard  ")
        self._build_dashboard_tab(dash_frame)

        # Log tab
        log_frame = tk.Frame(self.notebook, bg=UI_BG)
        self.notebook.add(log_frame, text="  Log  ")
        self._build_log_tab(log_frame)

        # Literature tab
        lit_frame = tk.Frame(self.notebook, bg=UI_BG)
        self.notebook.add(lit_frame, text="  Literature · experimental  ")
        self._build_literature_tab(lit_frame)

        # Review tab — embedded panel, no window flicker
        review_frame = tk.Frame(self.notebook, bg=UI_BG)
        self.notebook.add(review_frame, text="  Detection review  ")
        self.review_panel = ReviewPanel(review_frame)
        self.review_panel.pack(fill="both", expand=True)

        # Manual Annotation tab — load images, annotate by hand, export
        manual_frame = tk.Frame(self.notebook, bg=UI_BG)
        self.notebook.add(manual_frame, text="  Manual Annotate  ")
        self.manual_panel = ReviewPanel(manual_frame)
        self.manual_panel.pack(fill="both", expand=True)
        # Add extra "Load Images" button to manual panel toolbar
        self._add_manual_load_btn(manual_frame)
        self.manual_frame = manual_frame
        self.review_frame = review_frame
        self.notebook.insert(0, manual_frame)
        self.notebook.select(manual_frame)
        from .ui_theme import apply_theme
        apply_theme(self.root)
        self.root.after_idle(self._toggle_left_sidebar)

        # Status bar
        self.status_var = tk.StringVar(value="Ready — open a folder to start")
        tk.Label(self.root, textvariable=self.status_var,
                 bg="#0c1217", fg=UI_TEXT_DIM,
                 font=("Helvetica", 9), anchor="w", padx=10).pack(fill="x", side="bottom")

    def _toggle_left_sidebar(self):
        if self._left_sidebar_open:
            self.left_content.pack_forget()
            self.left_frame.configure(width=44)
            self.main_paned.paneconfigure(self.left_frame, minsize=44, width=44)
            self.root.after_idle(lambda: self.main_paned.sash_place(0, 44, 0))
            self._sidebar_btn.config(text="☰")
            self._left_sidebar_open = False
        else:
            self.left_content.pack(fill="both", expand=True)
            self.left_frame.configure(width=340)
            self.main_paned.paneconfigure(self.left_frame, minsize=340, width=340)
            self.root.after_idle(lambda: self.main_paned.sash_place(0, 340, 0))
            self._sidebar_btn.config(text="✕")
            self._left_sidebar_open = True
        self._project_path = None

    def _build_setup_panel(self, parent):
        setup = tk.LabelFrame(parent, text=" Project Setup ", bg=UI_PANEL,
                               fg=UI_TEXT_DIM, font=("Helvetica", 9),
                               bd=1, relief="flat")
        setup.pack(fill="x", padx=8, pady=8)

        # API Key
        tk.Label(setup, text="API key (optional)", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9)).grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self.api_key_var = tk.StringVar()
        # Try to load from env
        self.api_key_var.set(os.environ.get("ANTHROPIC_API_KEY", ""))
        api_entry = tk.Entry(setup, textvariable=self.api_key_var, show="•",
                             bg="#10171d", fg=UI_TEXT, insertbackground="white",
                             font=("Helvetica", 10), relief="flat", width=28)
        api_entry.grid(row=0, column=1, padx=6, pady=2, sticky="ew")

        # Root folder
        tk.Label(setup, text="Image Folder", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9)).grid(row=1, column=0, sticky="w", padx=6, pady=2)
        folder_frame = tk.Frame(setup, bg=UI_PANEL)
        folder_frame.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.folder_var = tk.StringVar(value="(not set)")
        tk.Label(folder_frame, textvariable=self.folder_var, bg=UI_PANEL, fg=UI_TEXT,
                 font=("Helvetica", 9), width=20, anchor="w").pack(side="left")
        ttk.Button(folder_frame, text="Browse", command=self._browse_folder,
                  style="App.Blue.TButton").pack(side="right")

        # Scale
        scale_frame = tk.Frame(setup, bg=UI_PANEL)
        scale_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
        tk.Label(scale_frame, text="Scale:", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9)).pack(side="left")
        self.scale_px_var = tk.StringVar(value=str(DEFAULT_SCALE_PX))
        tk.Entry(scale_frame, textvariable=self.scale_px_var, width=6,
                 bg="#10171d", fg=UI_TEXT, insertbackground="white",
                 font=("Helvetica", 10), relief="flat").pack(side="left", padx=4)
        tk.Label(scale_frame, text="px =", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9)).pack(side="left")
        self.scale_nm_var = tk.StringVar(value=str(DEFAULT_SCALE_NM))
        tk.Entry(scale_frame, textvariable=self.scale_nm_var, width=6,
                 bg="#10171d", fg=UI_TEXT, insertbackground="white",
                 font=("Helvetica", 10), relief="flat").pack(side="left", padx=4)
        self.scale_unit_var = tk.StringVar(value=DEFAULT_SCALE_UNIT)
        tk.OptionMenu(scale_frame, self.scale_unit_var, "nm", "µm",
                      ).pack(side="left")

        # Output folder
        tk.Label(setup, text="Output Folder", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9)).grid(row=3, column=0, sticky="w", padx=6, pady=2)
        out_frame = tk.Frame(setup, bg=UI_PANEL)
        out_frame.grid(row=3, column=1, sticky="ew", padx=6, pady=2)
        self.output_var = tk.StringVar(value="./ribbon_output")
        tk.Entry(out_frame, textvariable=self.output_var, width=18,
                 bg="#10171d", fg=UI_TEXT, insertbackground="white",
                 font=("Helvetica", 9), relief="flat").pack(side="left")
        ttk.Button(out_frame, text="...", command=self._browse_output,
                  style="App.Dark.TButton").pack(side="right")

        setup.columnconfigure(1, weight=1)

    def _build_file_tree(self, parent):
        tree_frame = tk.LabelFrame(parent, text=" Image Library ", bg=UI_PANEL,
                                    fg=UI_TEXT_DIM, font=("Helvetica", 9),
                                    bd=1, relief="flat")
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        style = ttk.Style()
        style.configure("Custom.Treeview",
                         background="#10171d",
                         foreground=UI_TEXT,
                         fieldbackground="#10171d",
                         rowheight=22,
                         font=("Helvetica", 10))
        style.configure("Custom.Treeview.Heading",
                         background=UI_PANEL, foreground=UI_TEXT_DIM,
                         font=("Helvetica", 9, "bold"))
        style.map("Custom.Treeview",
                  background=[("selected", UI_ACCENT)],
                  foreground=[("selected", "white")])

        self.tree = ttk.Treeview(tree_frame, style="Custom.Treeview",
                                  columns=("status", "count"), show="tree headings")
        self.tree.heading("#0", text="Folder / Image")
        self.tree.heading("status", text="Status")
        self.tree.heading("count", text="Ribbons")
        self.tree.column("#0", width=160)
        self.tree.column("status", width=70)
        self.tree.column("count", width=50)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # Bottom buttons
        btn_frame = tk.Frame(parent, bg=UI_PANEL)
        btn_frame.pack(fill="x", padx=8, pady=4)
        for row, column, text, command, style in [
            (0, 0, "Scan folder", self._scan_folder, "App.Blue.TButton"),
            (0, 1, "AI batch", self._start_batch, "App.Dark.TButton"),
            (1, 0, "Local detector", self._start_local_batch, "App.Dark.TButton"),
            (1, 1, "Stop", self._stop_batch, "App.Dark.TButton"),
        ]:
            ttk.Button(btn_frame, text=text, command=command, style=style).grid(
                row=row, column=column, sticky="ew", padx=2, pady=2)
        btn_frame.columnconfigure((0, 1), weight=1)
        tk.Label(parent, text="Detection is experimental. Review every candidate.",
                 bg=UI_PANEL, fg=UI_TEXT_DIM, font=("Helvetica", 9), wraplength=310).pack(pady=6)

    def _build_queue_tab(self, parent):
        # Progress section
        prog_frame = tk.Frame(parent, bg=UI_BG, pady=10)
        prog_frame.pack(fill="x", padx=12)

        top_row = tk.Frame(prog_frame, bg=UI_BG)
        top_row.pack(fill="x")
        self.progress_label = tk.Label(top_row, text="No analysis running",
                                        bg=UI_BG, fg=UI_TEXT_DIM, font=("Helvetica", 10))
        self.progress_label.pack(side="left")
        self.progress_count = tk.Label(top_row, text="",
                                        bg=UI_BG, fg=UI_TEXT_DIM, font=("Helvetica", 10))
        self.progress_count.pack(side="right")

        style = ttk.Style()
        style.configure("Green.Horizontal.TProgressbar",
                         troughcolor="#10171d", background=UI_ACCENT, borderwidth=0)
        self.progress_bar = ttk.Progressbar(prog_frame, style="Green.Horizontal.TProgressbar",
                                             length=400, mode="determinate")
        self.progress_bar.pack(fill="x", pady=4)

        # Queue table
        cols = ("filename", "folder", "age", "genotype", "status", "ribbons", "quality")
        self.queue_tree = ttk.Treeview(parent, columns=cols, show="headings",
                                        style="Custom.Treeview", height=20)
        headers = {"filename": ("Filename", 200), "folder": ("Folder", 120),
                   "age": ("Age", 50), "genotype": ("Genotype", 60),
                   "status": ("Status", 80), "ribbons": ("Ribbons", 60),
                   "quality": ("Quality", 70)}
        for col, (label, width) in headers.items():
            self.queue_tree.heading(col, text=label)
            self.queue_tree.column(col, width=width)

        qs = ttk.Scrollbar(parent, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=qs.set)
        qs.pack(side="right", fill="y")
        self.queue_tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.queue_tree.tag_configure("done", foreground=UI_ACCENT)
        self.queue_tree.tag_configure("error", foreground="#D85A30")
        self.queue_tree.tag_configure("pending", foreground=UI_TEXT_DIM)
        self.queue_tree.tag_configure("analyzing", foreground=UI_ACCENT2)
        self.queue_tree.bind("<Double-1>", self._on_queue_double_click)

        # Review button
        rev_frame = tk.Frame(parent, bg=UI_BG, pady=8)
        rev_frame.pack(fill="x", padx=12)
        ttk.Button(rev_frame, text="Review candidates",
                  command=self._open_review,
                  style="App.BigBlue.TButton").pack(side="left")
        ttk.Button(rev_frame, text="Save project",
                  command=self._save_project,
                  style="App.Blue.TButton").pack(side="left", padx=8)
        ttk.Button(rev_frame, text="Open project",
                  command=self._open_project,
                  style="App.Dark.TButton").pack(side="left")
        ttk.Button(rev_frame, text="Export all",
                  command=self._export_all,
                  style="App.BigGreen.TButton").pack(side="left", padx=8)
        ttk.Button(rev_frame, text="Show plots",
                  command=self._show_plots,
                  style="App.Purple.TButton").pack(side="left")

    def _build_dashboard_tab(self, parent):
        self.dash_frame = tk.Frame(parent, bg=UI_BG)
        self.dash_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self._update_dashboard()

    def _build_log_tab(self, parent):
        self.log_text = tk.Text(parent, bg="#0c1217", fg="#88cc88",
                                 font=("Courier", 10), wrap="word",
                                 relief="flat", padx=8, pady=8)
        log_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.config(state="disabled")

    def _build_literature_tab(self, parent):
        btn_row = tk.Frame(parent, bg=UI_BG, pady=8)
        btn_row.pack(fill="x", padx=12)

        ttk.Button(btn_row, text="Build all topics",
                  command=self._rebuild_kb_full,
                  style="App.BigBlue.TButton").pack(side="left")
        ttk.Button(btn_row, text="Update recent papers",
                  command=self._rebuild_kb_quick,
                  style="App.Purple.TButton").pack(side="left", padx=8)

        # KB status label
        self._kb_status_lbl = tk.Label(btn_row, text="", bg=UI_BG, fg=UI_TEXT_DIM,
                                        font=("Helvetica", 10))
        self._kb_status_lbl.pack(side="left", padx=8)

        self.lit_text = tk.Text(parent, bg="#0c1217", fg="#aaddff",
                                 font=("Helvetica", 10), wrap="word",
                                 relief="flat", padx=12, pady=12)
        lit_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.lit_text.yview)
        self.lit_text.configure(yscrollcommand=lit_scroll.set)
        lit_scroll.pack(side="right", fill="y")
        self.lit_text.pack(fill="both", expand=True)
        self.lit_text.insert("1.0", "Build or update the literature notes with the buttons above. These optional actions send queries to Anthropic and may incur API charges. Check generated statements against the original papers.\n\nThis will use Claude with web search to compile background knowledge about:\n• Ribbon morphology in EM\n• Typical dimensions (WT vs Piccolino cKO)\n• Developmental stages P0-P35\n• Key structural markers")
        self.lit_text.config(state="disabled")

    # ─── Knowledge Base ───────────────────────────────────────────────

    def _start_kb_build(self):
        """Called once on startup. Builds/updates KB in background thread."""
        key = self.api_key_var.get().strip()
        if not key:
            self._log("ℹ  No API key set — knowledge base will build after you enter your key.")
            self.status_var.set("Enter API key, then knowledge base will auto-update")
            return

        client = anthropic.Anthropic(api_key=key)
        is_first = not KB_PATH.exists()

        if is_first:
            self._log("=" * 55)
            self._log("FIRST RUN — Building Ribbon Synapse Knowledge Base")
            self._log("Researching 6 topics from current literature.")
            self._log("This takes ~5 minutes and only happens once.")
            self._log("The app is fully usable in the meantime.")
            self._log("=" * 55)
            self.status_var.set("First run: building knowledge base from literature (~5 min)…")
        else:
            self._log(f"Checking knowledge base for updates…")

        def worker():
            def cb(msg):
                self.analysis_queue.put(("kb_progress", msg))
            try:
                kb = build_or_update_knowledge_base(client, progress_callback=cb)
                self.analysis_queue.put(("kb_done", kb))
            except Exception as e:
                self.analysis_queue.put(("kb_error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_kb(self):
        """Force full KB rebuild (menu / button trigger)."""
        key = self.api_key_var.get().strip()
        if not key:
            messagebox.showwarning("API Key", "Enter API key first.")
            return
        client = anthropic.Anthropic(api_key=key)
        self._log("Forcing full knowledge base rebuild…")

        def worker():
            def cb(msg):
                self.analysis_queue.put(("kb_progress", msg))
            try:
                kb = build_or_update_knowledge_base(client, force_full_rebuild=True, progress_callback=cb)
                self.analysis_queue.put(("kb_done", kb))
            except Exception as e:
                self.analysis_queue.put(("kb_error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    # ─── Project management ───────────────────────────────────────────

    def _active_panel(self):
        selected = self.notebook.select()
        if selected == str(self.manual_frame):
            return self.manual_panel
        if selected == str(self.review_frame):
            return self.review_panel
        return None

    def _close(self):
        for panel in (self.manual_panel, self.review_panel):
            if not panel.confirm_replace():
                return
        if self.project and not self.review_panel.project and self._project_path is None:
            if not messagebox.askyesno("Unsaved project", "Close without saving the detection project?"):
                return
        self._stop_flag = True
        self.root.destroy()

    def _new_project(self):
        if self.is_analyzing:
            messagebox.showinfo("Analysis running", "Stop the analysis before replacing its project.")
            return
        for panel in (self.manual_panel, self.review_panel):
            if not panel.confirm_replace():
                return
        self.project = None
        self._project_path = None
        for panel in (self.manual_panel, self.review_panel):
            panel.project = None
            panel._img_results = []
            panel._ribbons = []
            panel._selected = None
            panel._pil_raw = panel._pil_adj = panel._photo = None
            panel._refresh_overview()
            panel._refresh_ribbon_list()
            panel._redraw()
            panel._update_save_status()
        self.tree.delete(*self.tree.get_children())
        self.queue_tree.delete(*self.queue_tree.get_children())
        self._update_dashboard()
        self._log("New project started.")

    def _open_project(self):
        if self.is_analyzing:
            messagebox.showinfo("Analysis running", "Stop the analysis before opening another project.")
            return
        panel = self._active_panel() or self.manual_panel
        panel._load_project_dialog()
        if panel.project:
            self.scale_px_var.set(str(panel.project.scale_px))
            self.scale_nm_var.set(str(panel.project.scale_nm))
            self.scale_unit_var.set(panel.project.scale_unit)
            self.folder_var.set(panel.project.root_folder)
            self.notebook.select(self.manual_frame if panel is self.manual_panel else self.review_frame)
            self._log(f"Project loaded: {panel.project.name}")

    def _save_project(self):
        panel = self._active_panel()
        if panel and panel.project:
            return panel._save_project()
        if not self.project:
            messagebox.showwarning("No project", "Load an image folder or open a project first.")
            return False
        if self.review_panel.project is self.project and not self.review_panel._save_current():
            return False
        selected = filedialog.asksaveasfilename(defaultextension=".json",
            filetypes=[("JSON project file", "*.json")])
        if not selected:
            return False
        try:
            self.project.save(Path(selected))
            self._project_path = Path(selected)
            self._log(f"Project saved: {selected}")
            return True
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not save project", str(error))
            return False

    def _read_scale(self):
        import math
        try:
            px = float(self.scale_px_var.get())
            value = float(self.scale_nm_var.get())
            if not all(math.isfinite(v) and v > 0 for v in (px, value)):
                raise ValueError
            return px, value, self.scale_unit_var.get()
        except ValueError:
            messagebox.showerror("Invalid calibration", "Enter positive, finite values for pixels and scale-bar length.")
            return None

    # ─── Folder scanning ──────────────────────────────────────────────

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select root image folder")
        if folder:
            self.folder_var.set(folder)
            self._scan_folder()

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_var.set(folder)

    def _scan_folder(self):
        if self.is_analyzing:
            messagebox.showinfo("Analysis running", "Stop the analysis before scanning another folder.")
            return
        if not self.review_panel.confirm_replace():
            return
        root = Path(self.folder_var.get())
        if not root.is_dir():
            messagebox.showerror("Folder Error", f"Folder not found: {root}")
            return

        scale = self._read_scale()
        if not scale:
            return
        scale_px, scale_nm, scale_unit = scale
        self._project_path = None

        project_name = root.name
        self.project = Project(
            name=project_name,
            root_folder=str(root),
            scale_px=scale_px,
            scale_nm=scale_nm,
            scale_unit=scale_unit,
        )

        self.tree.delete(*self.tree.get_children())
        self.queue_tree.delete(*self.queue_tree.get_children())

        total_images = 0

        # Walk directories
        subdirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
        if not subdirs:
            # Flat folder - all images in root
            subdirs = [root]

        for subdir in subdirs:
            images = [f for f in sorted(subdir.iterdir())
                      if f.suffix.lower() in IMAGE_EXTENSIONS]
            if not images:
                continue

            meta = parse_folder_name(subdir.name)
            folder_id = self.tree.insert("", "end",
                                          text=f"📁 {subdir.name}",
                                          values=("", str(len(images))),
                                          open=True)

            for img_path in images:
                ir = ImageResult(
                    image_path=str(img_path),
                    image_filename=img_path.name,
                    folder_name=subdir.name,
                    age=meta["age"],
                    genotype=meta["genotype"],
                    scale_px=scale_px,
                    scale_nm=scale_nm,
                    scale_unit=scale_unit,
                )
                self.project.image_results.append(ir)

                self.tree.insert(folder_id, "end",
                                  text=f"  {img_path.name}",
                                  values=("pending", "—"))

                self.queue_tree.insert("", "end",
                                        values=(img_path.name, subdir.name,
                                                meta["age"], meta["genotype"],
                                                "pending", "—", "—"),
                                        tags=("pending",))
                total_images += 1

        self._log(f"Scanned {root}: found {total_images} images in {len(subdirs)} folders")
        self.status_var.set(f"Found {total_images} images · Ready to analyze")

    def _populate_tree_from_project(self):
        self.tree.delete(*self.tree.get_children())
        folders = {}
        for ir in self.project.image_results:
            if ir.folder_name not in folders:
                folders[ir.folder_name] = self.tree.insert(
                    "", "end", text=f"📁 {ir.folder_name}",
                    values=("", ""), open=True)
            status = "done" if ir.analyzed else "pending"
            count = str(len(ir.ribbons)) if ir.analyzed else "—"
            self.tree.insert(folders[ir.folder_name], "end",
                              text=f"  {ir.image_filename}",
                              values=(status, count))

    def _populate_queue_from_project(self):
        self.queue_tree.delete(*self.queue_tree.get_children())
        for ir in self.project.image_results:
            status = "done" if ir.analyzed else "pending"
            count = str(len(ir.ribbons)) if ir.analyzed else "—"
            tag = "done" if ir.analyzed else "pending"
            self.queue_tree.insert("", "end",
                                    values=(ir.image_filename, ir.folder_name,
                                            ir.age, ir.genotype, status, count,
                                            ir.image_quality if ir.analyzed else "—"),
                                    tags=(tag,))

    # ─── Batch analysis ───────────────────────────────────────────────

    def _get_client(self) -> Optional[anthropic.Anthropic]:
        key = self.api_key_var.get().strip()
        if not key:
            messagebox.showerror("API Key Missing",
                                  "Please enter your Anthropic API key.")
            return None
        return anthropic.Anthropic(api_key=key)

    def _start_batch(self):
        if not self.project:
            messagebox.showwarning("No Project", "Scan a folder first.")
            return
        self.client = self._get_client()
        if not self.client:
            return
        if self.is_analyzing:
            return
        self.is_analyzing = True
        self._stop_flag = False
        pending = [ir for ir in self.project.image_results if not ir.analyzed]
        if not pending:
            messagebox.showinfo("All Done", "All images already analyzed.")
            self.is_analyzing = False
            return

        self._log(f"Starting batch analysis of {len(pending)} images...")
        self.progress_bar["maximum"] = len(pending)
        self.progress_bar["value"] = 0

        thread = threading.Thread(target=self._batch_worker, args=(pending,), daemon=True)
        thread.start()

    def _start_local_batch(self):
        """Run local detection only — no API calls, very fast."""
        if not self.project:
            messagebox.showwarning("No Project", "Scan a folder first.")
            return
        if self.is_analyzing:
            return
        self.is_analyzing = True
        self._stop_flag = False
        pending = [ir for ir in self.project.image_results if not ir.analyzed]
        if not pending:
            messagebox.showinfo("All Done", "All images already analyzed.")
            self.is_analyzing = False
            return
        self._log(f"Starting LOCAL-ONLY analysis of {len(pending)} images (no API)...")
        self.progress_bar["maximum"] = len(pending)
        self.progress_bar["value"] = 0
        thread = threading.Thread(target=self._local_batch_worker, args=(pending,), daemon=True)
        thread.start()

    def _local_batch_worker(self, pending):
        """Fast batch: local detection only, no API calls."""
        from .local_detector import detect_ribbons as local_detect, candidates_to_ribbon_data
        scale_px = self.project.scale_px
        scale_nm = self.project.scale_nm

        for i, ir in enumerate(pending):
            if getattr(self, "_stop_flag", False):
                self.analysis_queue.put(("stopped", i, len(pending)))
                break
            self.analysis_queue.put(("start", i, len(pending), ir.image_filename))
            try:
                candidates = local_detect(Path(ir.image_path), scale_px, scale_nm)
                ribbon_data = candidates_to_ribbon_data(candidates)

                ir.image_quality = "good"
                ir.overall_notes = f"Local detection: {len(candidates)} candidates"
                ir.analyzed = True

                for r_data in ribbon_data:
                    bbox = r_data.get("bbox", [50, 50, 5, 5])
                    ra = RibbonAnnotation(
                        id=r_data.get("id", 1),
                        image_path=ir.image_path, image_filename=ir.image_filename,
                        folder_name=ir.folder_name, age=ir.age, genotype=ir.genotype,
                        bbox_x=bbox[0], bbox_y=bbox[1], bbox_w=bbox[2], bbox_h=bbox[3],
                        length_nm=r_data.get("length_relative", 0) * scale_nm / scale_px * 10,
                        width_nm=r_data.get("width_relative", 0) * scale_nm / scale_px * 10,
                        morphology=r_data.get("morphology", "normal"),
                        confidence=r_data.get("confidence", "medium"),
                        vesicle_halo=r_data.get("vesicle_halo", False),
                        anchored_to_az=True,
                        notes=r_data.get("notes", ""),
                        scale_px=scale_px, scale_nm=scale_nm,
                    )
                    line = r_data.get("line")
                    if line and len(line) == 4:
                        ra.line_coords = line
                    # Use local detector's nm values directly
                    for c in candidates:
                        if c.id == r_data["id"]:
                            ra.length_nm = c.length_nm
                            ra.width_nm = c.width_nm
                            break
                    ir.ribbons.append(ra)

                self.analysis_queue.put(("done", i, len(pending), ir))
            except Exception as e:
                ir.error = str(e)
                ir.analyzed = True  # Mark as analyzed even on error so review works
                self.analysis_queue.put(("error", i, len(pending), ir, str(e)))

        self.analysis_queue.put(("finished", len(pending)))

    def _stop_batch(self):
        self._stop_flag = True
        self._log("Stop requested — will stop after current image.")

    def _batch_worker(self, pending):
        scale_px = self.project.scale_px
        scale_nm = self.project.scale_nm
        scale_unit = self.project.scale_unit

        # Load knowledge context once for the entire batch
        kb_context = get_knowledge_context(self._kb)
        # Local detection now runs inside analyze_image (no double-run)
        if kb_context:
            self.analysis_queue.put(("log", f"Using knowledge base context ({len(kb_context)} chars) for all analyses."))
        else:
            self.analysis_queue.put(("log", "⚠ No knowledge base context available — running without literature background."))

        for i, ir in enumerate(pending):
            if getattr(self, "_stop_flag", False):
                self.analysis_queue.put(("stopped", i, len(pending)))
                break

            self.analysis_queue.put(("start", i, len(pending), ir.image_filename))

            try:
                result = analyze_image(
                    Path(ir.image_path),
                    self.client,
                    scale_px, scale_nm, scale_unit,
                    additional_context=f"Age: {ir.age}, Genotype: {ir.genotype}",
                    knowledge_context=kb_context,
                )

                # Map result to ImageResult
                ir.image_quality = result.get("image_quality", "good")
                ir.developmental_stage_hint = result.get("developmental_stage_hint", "")
                ir.genotype_hint = result.get("genotype_hint", "unclear")
                ir.overall_notes = result.get("overall_notes", "")
                ir.magnification_estimate = result.get("magnification_estimate", "")
                ir.analyzed = True

                for r_data in result.get("ribbons", []):
                    bbox = r_data.get("bbox", [50, 50, 5, 5])
                    ra = RibbonAnnotation(
                        id=r_data.get("id", 1),
                        image_path=ir.image_path,
                        image_filename=ir.image_filename,
                        folder_name=ir.folder_name,
                        age=ir.age,
                        genotype=ir.genotype,
                        bbox_x=bbox[0] if len(bbox) > 0 else 50,
                        bbox_y=bbox[1] if len(bbox) > 1 else 50,
                        bbox_w=bbox[2] if len(bbox) > 2 else 5,
                        bbox_h=bbox[3] if len(bbox) > 3 else 5,
                        length_nm=r_data.get("length_nm", 0),
                        width_nm=r_data.get("width_nm", 0),
                        length_relative=r_data.get("length_relative", 0),
                        width_relative=r_data.get("width_relative", 0),
                        angle_deg=r_data.get("angle_deg", 0),
                        morphology=r_data.get("morphology", "normal"),
                        confidence=r_data.get("confidence", "medium"),
                        vesicle_halo=r_data.get("vesicle_halo", False),
                        anchored_to_az=r_data.get("anchored_to_az", True),
                        notes=r_data.get("notes", ""),
                        scale_px=scale_px,
                        scale_nm=scale_nm,
                        scale_unit=scale_unit,
                        image_width_px=r_data.get("image_width_px", 0),
                        image_height_px=r_data.get("image_height_px", 0),
                    )
                    # Store line coords for better visualization
                    line = r_data.get("line")
                    if line and len(line) == 4:
                        ra.line_coords = line
                    ir.ribbons.append(ra)

                self.analysis_queue.put(("done", i, len(pending), ir))
                time.sleep(0.5)  # Rate limiting courtesy

            except Exception as e:
                ir.error = str(e)
                self.analysis_queue.put(("error", i, len(pending), ir, str(e)))

        self.analysis_queue.put(("finished", len(pending)))

    def _poll_queue(self):
        try:
            while True:
                msg = self.analysis_queue.get_nowait()
                self._handle_queue_msg(msg)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _handle_queue_msg(self, msg):
        kind = msg[0]

        if kind == "log":
            self._log(msg[1])
            return

        if kind == "kb_progress":
            self._log(f"  KB: {msg[1]}")
            self.status_var.set(f"Knowledge base: {msg[1][:80]}")
            return

        if kind == "kb_done":
            self._kb = msg[1]
            self._kb_ready = True
            summary = get_kb_summary(self._kb)
            self._log(f"✓ {summary}")
            self.status_var.set(f"Ready · {summary}")
            self._show_kb_in_literature_tab()
            if hasattr(self, '_kb_status_lbl'):
                self._kb_status_lbl.config(text=f"✓ {summary}")
            return

        if kind == "kb_error":
            self._log(f"⚠ Knowledge base error: {msg[1]}")
            self.status_var.set("KB update failed — analysis will proceed without literature context")
            return

        if kind == "start":
            _, i, total, fname = msg
            self.progress_label.config(text=f"Analyzing: {fname}")
            self.progress_count.config(text=f"{i+1} / {total}")
            self.status_var.set(f"Analyzing {i+1}/{total}: {fname}")
            self._update_queue_row(i, "analyzing", "...")
            self._log(f"[{i+1}/{total}] Analyzing: {fname}")

        elif kind == "done":
            _, i, total, ir = msg
            self.progress_bar["value"] = i + 1
            count = len(ir.ribbons)
            self._update_queue_row(i, "done", str(count), ir.image_quality)
            self._log(f"  ✓ {ir.image_filename} → {count} ribbon(s) detected  [{ir.image_quality}]")
            self._update_dashboard()

        elif kind == "error":
            _, i, total, ir, err = msg
            self._update_queue_row(i, "error", "ERR")
            self._log(f"  ✗ {ir.image_filename}: {err}")

        elif kind == "finished":
            self.is_analyzing = False
            total = msg[1]
            analyzed_count = len([ir for ir in self.project.image_results if ir.analyzed]) if self.project else 0
            ribbon_count = sum(len(ir.ribbons) for ir in self.project.image_results if ir.analyzed) if self.project else 0
            self.progress_label.config(text=f"Complete — {analyzed_count} images, {ribbon_count} ribbons")
            self.status_var.set(f"Batch complete. {analyzed_count} analyzed, {ribbon_count} ribbons found.")
            self._log("=" * 50)
            self._log(f"Batch complete. {analyzed_count} analyzed, {ribbon_count} ribbons detected.")
            self._populate_queue_from_project()
            self._update_dashboard()
            messagebox.showinfo("Done", f"Analysis complete!\n{analyzed_count} images, {ribbon_count} ribbons.\nClick Review to verify.")

        elif kind == "stopped":
            self.is_analyzing = False
            self._log("Analysis stopped by user.")

    def _update_queue_row(self, idx, status, ribbons, quality="—"):
        items = self.queue_tree.get_children()
        if idx < len(items):
            item = items[idx]
            vals = list(self.queue_tree.item(item, "values"))
            vals[4] = status
            vals[5] = ribbons
            vals[6] = quality
            self.queue_tree.item(item, values=vals, tags=(status,))

    # ─── Review ───────────────────────────────────────────────────────

    def _add_manual_load_btn(self, parent):
        """Add a 'Load Images' button at the bottom of manual panel for direct image loading."""
        btn_frame = tk.Frame(parent, bg="#10171d", pady=4)
        btn_frame.pack(fill="x", side="bottom")
        ttk.Button(btn_frame, text="Load image folder",
                   command=self._manual_load_folder,
                   style="App.BigBlue.TButton").pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Export CSV / Excel",
                   command=self._manual_export,
                   style="App.Purple.TButton").pack(side="left", padx=4)

    def _manual_load_folder(self):
        """Load a folder of images directly into the manual annotation panel."""
        folder = filedialog.askdirectory(title="Select Image Folder")
        if not folder:
            return
        if not self.manual_panel.confirm_replace():
            return
        from .config import IMAGE_EXTENSIONS
        root = Path(folder)
        try:
            images = sorted(f for f in root.rglob("*") if f.is_file()
                            and f.suffix.lower() in IMAGE_EXTENSIONS)
        except OSError as error:
            messagebox.showerror("Could not read image folder", str(error))
            return
        if not images:
            messagebox.showinfo("No Images", f"No supported images found in {folder}")
            return

        scale = self._read_scale()
        if not scale:
            return
        scale_px, scale_nm, scale_unit = scale

        meta = parse_folder_name(root.name)
        project = Project(
            name=f"manual_{root.name}",
            root_folder=str(root),
            scale_px=scale_px, scale_nm=scale_nm, scale_unit=scale_unit,
        )
        for img_path in images:
            relative_parent = img_path.parent.relative_to(root)
            meta = parse_folder_name("_".join((root.name, *relative_parent.parts)))
            ir = ImageResult(
                image_path=str(img_path), image_filename=img_path.name,
                folder_name=img_path.parent.name, age=meta["age"], genotype=meta["genotype"],
                analyzed=True,  # Mark as analyzed so review panel shows them
                scale_px=scale_px, scale_nm=scale_nm, scale_unit=scale_unit,
            )
            project.image_results.append(ir)

        self.manual_panel.load_project(project)
        self.folder_var.set(folder)
        # Switch to Manual tab
        for i in range(self.notebook.index("end")):
            if "Manual" in self.notebook.tab(i, "text"):
                self.notebook.select(i)
                break
        self._log(f"Manual mode: loaded {len(images)} images from {root.name}")

    def _manual_export(self):
        """Export manual annotations to Excel."""
        if not hasattr(self.manual_panel, 'project') or not self.manual_panel.project:
            messagebox.showwarning("No Data", "Load images and annotate first.")
            return
        if not self.manual_panel._save_current():
            return
        output_dir = Path(self.output_var.get())
        try:
            results = export_all(self.manual_panel.project, output_dir)
            self._log(f"Manual annotations exported to {output_dir}")
            errors = [f"{k}: {v}" for k, v in results.items() if "error" in k]
            if errors:
                messagebox.showwarning("Export incomplete", "\n".join(errors))
            else:
                messagebox.showinfo("Export complete", f"Exported CSV, Excel, report and plots to {output_dir}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def _open_review(self):
        if not self.project:
            messagebox.showwarning("No Project", "Scan a folder and run analysis first.")
            return
        total = len(self.project.image_results)
        analyzed = [ir for ir in self.project.image_results if ir.analyzed]
        with_ribbons = [ir for ir in analyzed if len(ir.ribbons) > 0]
        self._log(f"Review check: {total} total, {len(analyzed)} analyzed, {len(with_ribbons)} with ribbons")

        if not analyzed:
            # Double check — maybe ir.analyzed was not set but ribbons exist
            has_ribbons = [ir for ir in self.project.image_results if len(ir.ribbons) > 0]
            if has_ribbons:
                self._log(f"Found {len(has_ribbons)} images with ribbons despite analyzed=False. Fixing...")
                for ir in has_ribbons:
                    ir.analyzed = True
                analyzed = has_ribbons
            else:
                messagebox.showinfo("Nothing to Review",
                    f"No analyzed images found ({total} total images). "
                    f"Run 'Run Batch' or 'Local Only' first.")
                return

        # Switch to Review tab and load project
        if self.review_panel.project is not self.project:
            if not self.review_panel.confirm_replace():
                return
            self.review_panel.load_project(self.project, project_path=self._project_path)
        for i in range(self.notebook.index("end")):
            if "Review" in self.notebook.tab(i, "text"):
                self.notebook.select(i)
                break

    def _open_review_at(self, idx):
        pass  # legacy, no longer used

    def _on_tree_double_click(self, event):
        pass

    def _on_queue_double_click(self, event):
        sel = self.queue_tree.selection()
        if sel:
            idx = self.queue_tree.index(sel[0])
            analyzed = [ir for ir in self.project.image_results if ir.analyzed]
            if idx < len(analyzed):
                self._review_index = idx
                self._open_review_at(idx)

    # ─── Dashboard ────────────────────────────────────────────────────

    def _update_dashboard(self):
        for w in self.dash_frame.winfo_children():
            w.destroy()

        if not self.project:
            tk.Label(self.dash_frame, text="Open a folder to start.",
                     bg=UI_BG, fg=UI_TEXT_DIM, font=("Helvetica", 12)).pack(pady=40)
            return

        total = len(self.project.image_results)
        analyzed = len([ir for ir in self.project.image_results if ir.analyzed])
        all_ribbons = sum(len(ir.ribbons) for ir in self.project.image_results)
        accepted = sum(len(ir.accepted_ribbons()) for ir in self.project.image_results)

        # Metric cards
        metrics = tk.Frame(self.dash_frame, bg=UI_BG)
        metrics.pack(fill="x", pady=8)
        for label, val, col in [
            ("Total images", total, UI_TEXT),
            ("Analyzed", analyzed, UI_ACCENT2),
            ("Total ribbons", all_ribbons, UI_ACCENT),
            ("Accepted", accepted, "#9F77DD"),
        ]:
            card = tk.Frame(metrics, bg=UI_PANEL, padx=16, pady=12,
                             relief="flat", bd=0)
            card.pack(side="left", padx=6, pady=4)
            tk.Label(card, text=str(val), bg=UI_PANEL, fg=col,
                     font=("Helvetica", 22, "bold")).pack()
            tk.Label(card, text=label, bg=UI_PANEL, fg=UI_TEXT_DIM,
                     font=("Helvetica", 10)).pack()

        # Stats table if we have data
        if self.project:
            df = self.project.to_dataframe()
            if not df.empty:
                summary = self.project.summary_stats()
                if not summary.empty:
                    tk.Label(self.dash_frame, text="Summary by group",
                             bg=UI_BG, fg=UI_TEXT_DIM,
                             font=("Helvetica", 10, "bold")).pack(anchor="w", padx=8, pady=(12, 4))

                    cols = list(summary.columns)
                    tbl = ttk.Treeview(self.dash_frame, columns=cols, show="headings",
                                        style="Custom.Treeview", height=min(len(summary)+1, 10))
                    for col in cols:
                        tbl.heading(col, text=col.replace("_", " "))
                        tbl.column(col, width=max(80, len(col) * 9))

                    for _, row in summary.iterrows():
                        tbl.insert("", "end", values=list(row))
                    tbl.pack(fill="x", padx=8, pady=4)

    # ─── Export ───────────────────────────────────────────────────────

    def _show_kb_in_literature_tab(self):
        """Display KB content in the literature tab."""
        if not self._kb:
            return
        self.lit_text.config(state="normal")
        self.lit_text.delete("1.0", "end")
        self.lit_text.insert("end", f"Knowledge Base — {get_kb_summary(self._kb)}\n")
        self.lit_text.insert("end", "=" * 60 + "\n\n")

        for topic_id, topic_data in self._kb.get("topics", {}).items():
            title = topic_data.get("title", topic_id)
            content = topic_data.get("content", "")
            updated = topic_data.get("updated", "")[:10]
            self.lit_text.insert("end", f"▶ {title.upper()}  (updated {updated})\n")
            self.lit_text.insert("end", "-" * 50 + "\n")
            self.lit_text.insert("end", content + "\n\n")

        self.lit_text.config(state="disabled")

    def _export_all(self):
        if not self.project:
            return
        output_dir = Path(self.output_var.get())
        self._log(f"Exporting to {output_dir}...")
        try:
            results = export_all(self.project, output_dir)
            msgs = []
            for k, v in results.items():
                if "error" not in k:
                    if isinstance(v, list):
                        msgs.append(f"{k}: {len(v)} files")
                    else:
                        msgs.append(f"{k}: {v}")
                else:
                    msgs.append(f"⚠ {k}: {v}")
            messagebox.showinfo("Export Complete",
                                 "Export complete!\n\n" + "\n".join(msgs))
            self._log("Export complete.")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def _show_plots(self):
        if not self.project:
            return
        df = self.project.to_dataframe()
        if df.empty:
            messagebox.showinfo("No Data", "No ribbon data to plot yet.")
            return
        from .plots import plot_length_distributions, plot_morphology_breakdown, plot_developmental_trajectory
        import matplotlib.pyplot as plt
        for func in [plot_length_distributions, plot_morphology_breakdown, plot_developmental_trajectory]:
            try:
                fig = func(df)
                if fig:
                    plt.show(block=False)
            except Exception as e:
                self._log(f"Plot error: {e}")

    # ─── Literature ───────────────────────────────────────────────────

    def _fetch_literature(self):
        self._rebuild_kb_quick()

    def _rebuild_kb_full(self):
        self.client = self._get_client()
        if not self.client:
            return
        self._log("Starting FULL knowledge base rebuild (all 6 topics)...")
        if hasattr(self, '_kb_status_lbl'):
            self._kb_status_lbl.config(text="Full rebuild running...")
        def worker():
            def cb(msg):
                self.analysis_queue.put(("kb_progress", msg))
            try:
                from .knowledge_base import build_or_update_knowledge_base, KB_PATH
                kb = build_or_update_knowledge_base(self.client, force_full_rebuild=True, progress_callback=cb)
                self.analysis_queue.put(("kb_done", kb))
            except Exception as e:
                self.analysis_queue.put(("kb_error", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_kb_quick(self):
        self.client = self._get_client()
        if not self.client:
            return
        self._log("Starting quick KB update (recent papers)...")
        if hasattr(self, '_kb_status_lbl'):
            self._kb_status_lbl.config(text="Quick update running...")
        def worker():
            def cb(msg):
                self.analysis_queue.put(("kb_progress", msg))
            try:
                from .knowledge_base import build_or_update_knowledge_base
                kb = build_or_update_knowledge_base(self.client, force_full_rebuild=False, progress_callback=cb)
                self.analysis_queue.put(("kb_done", kb))
            except Exception as e:
                self.analysis_queue.put(("kb_error", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    # ─── Logging ─────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        print(msg)  # also to console
