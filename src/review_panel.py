"""
Review Panel — embedded in main app, no window flicker
=======================================================
- Stays open, navigates in-place
- 2-click mode: draw ribbon axis
- 3-click mode: axis + width
- Overview sidebar showing all images with status
- Project save/load
- Fixed button colors
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import math, copy, json
from dataclasses import asdict
from pathlib import Path
from PIL import Image, ImageTk, ImageEnhance
import numpy as np

from .models import RibbonAnnotation, ImageResult, Project
from .config import MORPHOLOGY_CLASSES, MORPHOLOGY_COLORS, UI_BG, UI_PANEL, UI_TEXT, UI_TEXT_DIM

BTN  = dict(relief="flat", padx=8, pady=4, font=("Helvetica", 10))
BTN2 = dict(relief="flat", padx=6, pady=3, font=("Helvetica", 9))


def _btn(parent, text, command, bg="#2a3a5a", fg="#e0e0e0", font=None, **kw):
    """Button helper that always sets correct macOS-safe colors."""
    f = font or ("Helvetica", 10)
    return tk.Button(parent, text=text, command=command,
                     bg=bg, fg=fg, font=f,
                     activebackground=bg, activeforeground=fg,
                     highlightbackground=bg,
                     relief="flat", **kw)


class ReviewPanel(tk.Frame):
    """
    Full-screen review panel embedded in the main notebook.
    Call load_project(project) to populate, then it handles everything.
    """

    def __init__(self, master, **kw):
        super().__init__(master, bg=UI_BG, **kw)
        self.project: Project | None = None
        self._img_results: list[ImageResult] = []
        self._cur_idx     = 0
        self._ribbons     = []
        self._selected    = None

        # Image state
        self._pil_raw = None
        self._pil_adj = None
        self._photo   = None
        self._zoom    = 1.0
        self._pan_x   = 0.0
        self._pan_y   = 0.0
        self._pan_start = None
        self._space   = False
        self._project_path = None
        self._saved_state = None
        self._image_error = ""
        self._link_first = None

        # Draw state
        self._draw_mode = None   # None | "axis" | "full"
        self._draw_pts  = []
        self._draw_tmps = []

        self._build()

    # ── Build UI ────────────────────────────────────────────────

    def _build(self):
        # ── macOS button fix: use ttk.Button with custom styles ──
        style = ttk.Style()
        style.theme_use("clam")
        # Define button styles with explicit colors
        for name, bg, fg, abg in [
            ("Green.TButton",  "#22a879", "white",   "#138564"),
            ("Blue.TButton",   "#2267b5", "white",   "#174f96"),
            ("Purple.TButton", "#6a49c8", "white",   "#5237ab"),
            ("Orange.TButton", "#c47c22", "white",   "#a36318"),
            ("Active.TButton", "#ff8800", "white",   "#cc6600"),
            ("Red.TButton",    "#6B1A0A", "white",   "#4a1008"),
            ("Dark.TButton",   "#2e324d", "#eef4ff", "#232742"),
            ("Gray.TButton",   "#354550", "#aaaaaa", "#1a1a3a"),
            ("Nav.TButton",    "#1c2832", "#e0e0e0", "#1a2a4a"),
            ("Save.TButton",   "#3d86db", "white",   "#2d6eb5"),
        ]:
            style.configure(name, background=bg, foreground=fg, borderwidth=0,
                            font=("Helvetica", 10, "bold"), padding=(12, 7))
            style.map(name,
                      background=[("active", abg), ("pressed", abg)],
                      foreground=[("active", fg), ("pressed", fg)])
        # Bigger bold version
        style.configure("BigGreen.TButton", background="#22a879", foreground="white",
                        borderwidth=0, font=("Helvetica", 11, "bold"), padding=(14, 8))
        style.map("BigGreen.TButton",
                  background=[("active", "#0f6e56")], foreground=[("active", "white")])

        # Top toolbar
        tb = tk.Frame(self, bg="#10171d", pady=5)
        tb.pack(fill="x")

        self._title_lbl = tk.Label(tb, text="No project loaded",
                                    bg="#10171d", fg=UI_TEXT,
                                    font=("Helvetica", 12, "bold"))
        self._title_lbl.pack(side="left", padx=8)
        self._info_lbl = tk.Label(tb, text="", bg="#10171d", fg=UI_TEXT_DIM,
                                   font=("Helvetica", 10))
        self._info_lbl.pack(side="left")
        # Nav buttons (right side of toolbar)
        nav = tk.Frame(self, bg="#10171d", pady=5)
        nav.pack(fill="x", padx=0)
        ttk.Button(nav, text="◀ Prev", command=self._prev, style="Nav.TButton").pack(side="left", padx=2)
        ttk.Button(nav, text="Save & Next ▶", command=self._save_next,
                  style="BigGreen.TButton").pack(side="left", padx=2)
        ttk.Button(nav, text="Skip edits", command=self._skip, style="Gray.TButton").pack(side="left", padx=2)
        # Main layout — uses PanedWindow for resizable panels
        body = tk.Frame(self, bg=UI_BG)
        body.pack(fill="both", expand=True)

        # ── Toggle buttons strip (far left) ─────────────────────
        toggles = tk.Frame(body, bg="#172129", width=22)
        toggles.pack(side="left", fill="y")
        toggles.pack_propagate(False)

        # ── Left: overview list (collapsible) ───────────────────
        self._left_panel = tk.Frame(body, bg=UI_PANEL, width=195)
        self._left_panel.pack(side="left", fill="y")
        self._left_panel.pack_propagate(False)
        self._left_visible = True

        tk.Label(self._left_panel, text="Images", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 10), pady=5).pack()
        self._overview_lb = tk.Listbox(
            self._left_panel, bg="#10171d", fg=UI_TEXT,
            selectbackground="#1D9E75", selectforeground="white",
            font=("Helvetica", 9), relief="flat", borderwidth=0, activestyle="none", exportselection=False)
        self._overview_lb.pack(fill="both", expand=True, padx=2)
        self._overview_lb.bind("<<ListboxSelect>>", self._on_overview_select)
        for sym, lbl in [("✓", "reviewed"), ("·", "analyzed"), ("–", "pending")]:
            tk.Label(self._left_panel, text=f" {sym} {lbl}", bg=UI_PANEL,
                     fg="#a9b9c6", font=("Helvetica", 8)).pack(anchor="w", padx=4)

        # ── Ribbon list (collapsible) ────────────────────────────
        self._ribbon_panel = tk.Frame(body, bg=UI_PANEL, width=210)
        self._ribbon_panel.pack(side="left", fill="y")
        self._ribbon_panel.pack_propagate(False)
        self._ribbon_visible = True

        tk.Label(self._ribbon_panel, text="Ribbons", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 10), pady=5).pack()
        self._ribbon_lb = tk.Listbox(
            self._ribbon_panel, bg="#10171d", fg=UI_TEXT,
            selectbackground="#1D9E75", selectforeground="white",
            font=("Helvetica", 10), relief="flat", borderwidth=0, activestyle="none", exportselection=False)
        self._ribbon_lb.pack(fill="both", expand=True, padx=3)
        self._ribbon_lb.bind("<<ListboxSelect>>", self._on_ribbon_select)
        bf = tk.Frame(self._ribbon_panel, bg=UI_PANEL, pady=3)
        bf.pack(fill="x", padx=3)
        for txt, cmd, sty in [
            ("Straight axis · 2 clicks",   lambda: self._start_draw("axis"),       "Blue.TButton"),
            ("Curved axis", lambda: self._start_draw("curve"), "Purple.TButton"),
            ("Sphere · centre + radius", lambda: self._start_draw("spherical"), "Orange.TButton"),
            ("Delete selected",      self._delete_selected,                  "Red.TButton"),
        ]:
            ttk.Button(bf, text=txt, command=cmd, style=sty).pack(fill="x", pady=1)
        ttk.Button(bf, text="Link selected fragments", command=self._link_fragments,
                  style="Dark.TButton").pack(fill="x", pady=1)
        ttk.Button(bf, text="Merge with next ribbon", command=self._merge_ribbons,
                  style="Dark.TButton").pack(fill="x", pady=1)

        # ── Canvas ─────────────────────────────────────────────
        cf = tk.Frame(body, bg="#0c1217")
        cf.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(cf, bg="#0c1217", cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>",    self._on_click)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<Control-ButtonPress-1>", self._on_right_click)  # macOS trackpad
        self.canvas.bind("<B1-Motion>",        self._on_drag)
        self.canvas.bind("<ButtonRelease-1>",  self._on_release)
        self.canvas.bind("<ButtonPress-2>",    self._pan_start_ev)
        self.canvas.bind("<B2-Motion>",        self._pan_move_ev)
        self.canvas.bind("<ButtonRelease-2>",  self._pan_end_ev)
        self.canvas.bind("<ButtonPress-3>",    self._on_right_click)
        self.canvas.bind("<B3-Motion>",        self._pan_move_ev)
        self.canvas.bind("<ButtonRelease-3>",  self._pan_end_ev)
        self.canvas.bind("<MouseWheel>",       self._scroll)
        self.canvas.bind("<Button-4>",         self._scroll)
        self.canvas.bind("<Button-5>",         self._scroll)
        self.canvas.bind("<Configure>",        lambda e: self._redraw())
        self.canvas.bind("<Motion>",           self._on_motion)  # preview while moving

        # ── Image controls (collapsible) ─────────────────────────
        self._imgctrl_panel = tk.Frame(body, bg=UI_PANEL, width=90)
        self._imgctrl_panel.pack(side="right", fill="y")
        self._imgctrl_panel.pack_propagate(False)
        self._imgctrl_visible = True
        for lbl, attr in [("Bright", "_bvar"), ("Contrast", "_cvar")]:
            tk.Label(self._imgctrl_panel, text=lbl, bg=UI_PANEL, fg=UI_TEXT_DIM,
                     font=("Helvetica", 8)).pack(pady=(5,0))
            v = tk.DoubleVar(value=1.0)
            setattr(self, attr, v)
            tk.Scale(self._imgctrl_panel, from_=0.3, to=3.0, resolution=0.05,
                     orient="vertical", variable=v, bg=UI_PANEL, fg=UI_TEXT,
                     troughcolor="#10171d", highlightthickness=0,
                     command=lambda _: self._apply_adj()).pack()
        for txt, cmd in [("Reset", self._reset_adj), ("Fit", self._fit)]:
            ttk.Button(self._imgctrl_panel, text=txt, command=cmd,
                      style="Dark.TButton").pack(pady=2, padx=3, fill="x")
        # Zoom buttons
        tk.Label(self._imgctrl_panel, text="Zoom", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 8)).pack(pady=(8,0))
        zf = tk.Frame(self._imgctrl_panel, bg=UI_PANEL)
        zf.pack(padx=3, fill="x")
        ttk.Button(zf, text="+", command=lambda: self._zoom_btn(1.3),
                  style="Dark.TButton", width=3).pack(side="left", expand=True, fill="x")
        ttk.Button(zf, text="–", command=lambda: self._zoom_btn(1/1.3),
                  style="Dark.TButton", width=3).pack(side="left", expand=True, fill="x")

        # ── Right editor (collapsible) ───────────────────────────
        self._editor_panel = tk.Frame(body, bg=UI_PANEL, width=260)
        self._editor_panel.pack(side="right", fill="y")
        self._editor_panel.pack_propagate(False)
        self._editor_visible = True
        self._build_editor(self._editor_panel)

        # ── Now add toggle buttons ───────────────────────────────
        def _tooltip(widget, text):
            """Add hover tooltip to any widget."""
            tip = [None]
            def show(e):
                x, y = widget.winfo_rootx() + 25, widget.winfo_rooty() + 20
                tip[0] = tk.Toplevel(widget)
                tip[0].wm_overrideredirect(True)
                tip[0].wm_geometry(f"+{x}+{y}")
                lbl = tk.Label(tip[0], text=text, bg="#222233", fg="#ccccdd",
                               font=("Helvetica", 10), padx=6, pady=3, relief="solid", borderwidth=1)
                lbl.pack()
            def hide(e):
                if tip[0]:
                    tip[0].destroy(); tip[0] = None
            widget.bind("<Enter>", show)
            widget.bind("<Leave>", hide)
        self._tooltip = _tooltip

        def make_toggle(frame, panel, open_sym, close_sym, side, tooltip_text=""):
            visible = [True]
            btn = tk.Button(frame, text=open_sym, width=2,
                            bg="#172129", fg="#778899",
                            activebackground="#172129", activeforeground="#aabbcc",
                            highlightbackground="#172129",
                            relief="flat", font=("Helvetica", 13), cursor="hand2")
            def toggle():
                if visible[0]:
                    panel.pack_forget()
                    btn.config(text=close_sym, fg="#aabbcc")
                    visible[0] = False
                else:
                    if side == "left":
                        panel.pack(side="left", fill="y", before=cf)
                    else:
                        panel.pack(side="right", fill="y", before=self._imgctrl_panel if panel is not self._imgctrl_panel else cf)
                    btn.config(text=open_sym, fg="#778899")
                    visible[0] = True
            btn.config(command=toggle)
            if tooltip_text:
                _tooltip(btn, tooltip_text)
            return btn

        # Left toggles (stacked vertically)
        make_toggle(toggles, self._left_panel,   "◀", "▶", "left", "Image overview").pack(pady=8)
        make_toggle(toggles, self._ribbon_panel, "◀", "▶", "left", "Ribbon list").pack(pady=8)
        # Right toggle (in image controls panel header area)
        right_toggle_frame = tk.Frame(cf, bg="#0c1217")
        right_toggle_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=2)
        make_toggle(right_toggle_frame, self._editor_panel, "▶", "◀", "right", "Ribbon editor").pack()

        # Bottom project actions stay visible even if the top toolbar is tight.
        project_bar = tk.Frame(self, bg="#10171d", pady=4)
        project_bar.pack(fill="x", side="bottom")
        tk.Label(self, text="A / R: accept / reject · ← / →: navigate · Scroll: zoom · Space + drag: pan · Esc: cancel drawing",
                 bg=UI_BG, fg=UI_TEXT_DIM, font=("Helvetica", 9), anchor="w", padx=10).pack(fill="x", side="bottom")
        ttk.Button(project_bar, text="Open project", command=self._load_project_dialog,
                  style="Dark.TButton").pack(side="left", padx=6)
        ttk.Button(project_bar, text="Save annotations", command=self._save_project,
                  style="Save.TButton").pack(side="left", padx=6)
        ttk.Button(project_bar, text="Save as…", command=lambda: self._save_project(save_as=True),
                   style="Dark.TButton").pack(side="left", padx=6)
        self._save_status = tk.StringVar(value="No saved project")
        tk.Label(project_bar, textvariable=self._save_status, bg="#10171d", fg=UI_TEXT_DIM,
                 font=("Helvetica", 9)).pack(side="left", padx=12)

        # Status bar
        self._status = tk.StringVar(value="Load a project to start reviewing")
        tk.Label(self, textvariable=self._status, bg="#0c1217", fg=UI_TEXT_DIM,
                 font=("Helvetica", 9), anchor="w", padx=10).pack(fill="x", side="bottom")

        shortcut_tag = f"RibbonShortcuts:{id(self)}"
        actions = {
            "<a>": self._accept, "<r>": self._reject,
            "<Delete>": self._delete_selected, "<Escape>": self._cancel_draw,
            "<Right>": self._save_next, "<Left>": self._prev,
            "<KeyPress-space>": lambda: self._set_space(True),
            "<KeyRelease-space>": lambda: self._set_space(False),
        }
        for sequence, action in actions.items():
            def dispatch(event, action=action):
                if self.winfo_viewable():
                    action()
                    return "break"
            self.bind_class(shortcut_tag, sequence, dispatch)
        for widget in (self.canvas, self._overview_lb, self._ribbon_lb):
            tags = widget.bindtags()
            widget.bindtags((tags[0], shortcut_tag, *tags[1:]))
        self.canvas.bind("<FocusOut>", lambda e: self._set_space(False))

    def _build_editor(self, parent):
        # Keep every field reachable even at the minimum window height.
        self._editor_canvas = tk.Canvas(parent, bg=UI_PANEL, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical",
                                  command=self._editor_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self._editor_canvas.configure(yscrollcommand=scrollbar.set)
        self._editor_canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(self._editor_canvas, bg=UI_PANEL)
        window = self._editor_canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda e: self._editor_canvas.configure(
            scrollregion=self._editor_canvas.bbox("all")))
        self._editor_canvas.bind("<Configure>", lambda e:
            self._editor_canvas.itemconfigure(window, width=e.width))
        parent = content
        tk.Label(parent, text="Ribbon Editor", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 10), pady=6).pack()

        ar = tk.Frame(parent, bg=UI_PANEL)
        ar.pack(fill="x", padx=8, pady=4)
        ttk.Button(ar, text="✓ Accept (A)", command=self._accept,
                  style="Green.TButton").pack(side="left", padx=2, fill="x", expand=True)
        ttk.Button(ar, text="✗ Reject (R)", command=self._reject,
                  style="Red.TButton").pack(side="left", padx=2, fill="x", expand=True)

        tk.Frame(parent, bg="#354550", height=1).pack(fill="x", padx=8, pady=3)

        tk.Label(parent, text="Morphology", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=10)
        self.morph_var = tk.StringVar(value="normal")
        mf = tk.Frame(parent, bg=UI_PANEL)
        mf.pack(anchor="w", padx=12)
        for i, m in enumerate(MORPHOLOGY_CLASSES):
            col = MORPHOLOGY_COLORS.get(m, "#888")
            tk.Radiobutton(mf, text=m, variable=self.morph_var, value=m,
                           bg=UI_PANEL, fg=col, selectcolor="#10171d",
                           activebackground=UI_PANEL, font=("Helvetica", 9),
                           command=self._apply_edit).grid(
                               row=i//2, column=i%2, sticky="w", padx=3, pady=1)

        tk.Frame(parent, bg="#354550", height=1).pack(fill="x", padx=8, pady=3)
        tk.Label(parent, text="Image Data", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=10)
        imgf = tk.Frame(parent, bg=UI_PANEL)
        imgf.pack(fill="x", padx=10, pady=2)
        self.empty_terminals_var = tk.StringVar(value="0")
        tk.Label(imgf, text="Empty terminals", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9), width=11, anchor="w").grid(row=0, column=0)
        tk.Entry(imgf, textvariable=self.empty_terminals_var, bg="#10171d", fg="#e0e0e0",
                 insertbackground="white", font=("Helvetica", 10),
                 width=7, relief="flat").grid(row=0, column=1, padx=3, pady=2)
        ttk.Button(imgf, text="Apply image", command=self._apply_image_fields,
                  style="Dark.TButton").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        tk.Frame(parent, bg="#354550", height=1).pack(fill="x", padx=8, pady=3)
        tk.Label(parent, text="Measurements", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=10)
        mf2 = tk.Frame(parent, bg=UI_PANEL)
        mf2.pack(fill="x", padx=10, pady=2)
        self.length_var = tk.StringVar()
        self.width_var  = tk.StringVar()
        self.length_not_measured_var = tk.BooleanVar(value=False)

        # Length row with entry + disable-state checkbox
        tk.Label(mf2, text="Length (nm)", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9), width=11, anchor="w").grid(row=0, column=0)
        self._length_entry = tk.Entry(mf2, textvariable=self.length_var, bg="#10171d",
                 fg="#e0e0e0", insertbackground="white", font=("Helvetica", 10),
                 width=7, relief="flat")
        self._length_entry.grid(row=0, column=1, padx=3, pady=2)

        # "Höhe nicht gemessen" checkbox — sits directly below Length
        tk.Checkbutton(mf2, text="Height not measured", variable=self.length_not_measured_var,
                       bg=UI_PANEL, fg="#ffaa44", selectcolor="#10171d",
                       activebackground=UI_PANEL, font=("Helvetica", 8),
                       command=self._on_length_not_measured).grid(
                           row=1, column=0, columnspan=2, sticky="w", padx=2, pady=(0, 3))

        # Width row
        tk.Label(mf2, text="Width  (nm)", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 9), width=11, anchor="w").grid(row=2, column=0)
        tk.Entry(mf2, textvariable=self.width_var, bg="#10171d", fg="#e0e0e0",
                 insertbackground="white", font=("Helvetica", 10),
                 width=7, relief="flat").grid(row=2, column=1, padx=3, pady=2)

        self.vesicle_count_var = tk.StringVar(value="0")
        self.vesicle_shell_var = tk.StringVar(value="50")
        for row, (lbl, var) in enumerate([("Vesicles", self.vesicle_count_var),
                                           ("Shell (nm)", self.vesicle_shell_var)], start=3):
            tk.Label(mf2, text=lbl, bg=UI_PANEL, fg=UI_TEXT_DIM,
                     font=("Helvetica", 9), width=11, anchor="w").grid(row=row, column=0)
            tk.Entry(mf2, textvariable=var, bg="#10171d", fg="#e0e0e0",
                     insertbackground="white", font=("Helvetica", 10),
                     width=7, relief="flat").grid(row=row, column=1, padx=3, pady=2)
        ttk.Button(mf2, text="Estimate vesicles · experimental", command=self._estimate_vesicles,
                  style="Dark.TButton").grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        tk.Frame(parent, bg="#354550", height=1).pack(fill="x", padx=8, pady=3)
        self.halo_var   = tk.BooleanVar()
        self.az_var     = tk.BooleanVar(value=True)
        self.inside_var = tk.BooleanVar(value=True)
        for txt, var in [("Vesicle halo", self.halo_var),
                          ("At active zone", self.az_var),
                          ("In rod spherule", self.inside_var)]:
            tk.Checkbutton(parent, text=txt, variable=var,
                           bg=UI_PANEL, fg="#e0e0e0", selectcolor="#10171d",
                           activebackground=UI_PANEL, font=("Helvetica", 9),
                           command=self._apply_edit).pack(anchor="w", padx=12)

        tk.Frame(parent, bg="#354550", height=1).pack(fill="x", padx=8, pady=3)
        self.conf_var = tk.StringVar(value="medium")
        cf = tk.Frame(parent, bg=UI_PANEL)
        cf.pack(anchor="w", padx=12)
        for c in ["high", "medium", "low"]:
            tk.Radiobutton(cf, text=c, variable=self.conf_var, value=c,
                           bg=UI_PANEL, fg="#e0e0e0", selectcolor="#10171d",
                           activebackground=UI_PANEL, font=("Helvetica", 9),
                           command=self._apply_edit).pack(side="left", padx=3)

        tk.Frame(parent, bg="#354550", height=1).pack(fill="x", padx=8, pady=3)
        tk.Label(parent, text="Notes / Rejection reason", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=10)
        self.notes_text = tk.Text(parent, height=3, bg="#10171d", fg="#e0e0e0",
                                   insertbackground="white", font=("Helvetica", 9),
                                   wrap="word", relief="flat", padx=4, pady=4)
        self.notes_text.pack(fill="x", padx=10)
        self.notes_text.bind("<FocusOut>", lambda e: self._apply_edit())

        self._apply_button = ttk.Button(parent, text="Apply", command=self._apply_edit,
                                       style="Save.TButton")
        self._apply_button.pack(pady=5, padx=10, fill="x")

        self._ai_lbl = tk.Label(parent, text="", bg=UI_PANEL, fg="#a9b9c6",
                                 font=("Helvetica", 8), wraplength=240,
                                 justify="left", padx=10, pady=2)
        self._ai_lbl.pack(anchor="w")


    def _load_project_dialog(self):
        """Open file dialog to load a saved project JSON."""
        path = filedialog.askopenfilename(
            filetypes=[("Ribbon Project", "*.json"), ("All files", "*.*")],
            title="Load Saved Project")
        if not path:
            return
        if not self.confirm_replace():
            return
        try:
            project = Project.load(Path(path))
            # Check whether image paths are accessible; remap if not (e.g. Mac→Windows)
            missing = [ir for ir in project.image_results
                       if not Path(ir.image_path).exists()]
            if missing:
                answer = messagebox.askyesno(
                    "Image folder not found",
                    f"{len(missing)} of {len(project.image_results)} image files are missing. "
                    f"The folder may have moved or the project came from another computer.\n\n"
                    f"Locate the image folder now?")
                if answer:
                    new_root = filedialog.askdirectory(
                        title="Select image root folder (including its subfolders)")
                    if new_root:
                        remapped, not_found = self._remap_project_paths(project, Path(new_root))
                        msg = f"Located {remapped} image files"
                        if not_found:
                            msg += f"; {not_found} missing or ambiguous (annotations retained)"
                        self._status.set(msg)
            self.load_project(project, project_path=Path(path))
            # Relocated paths are an unsaved change, even though the annotations remain intact.
            self._saved_state = asdict(Project.load(Path(path)))
            self._update_save_status()
            self._status.set(f"Project loaded: {Path(path).name}" +
                             (f" · {not_found} images unresolved" if missing and answer and new_root else ""))
        except Exception as e:
            self._status.set(f"Load error: {e}")
            messagebox.showerror("Could not open project", str(e), parent=self)

    @staticmethod
    def _remap_project_paths(project, new_root: Path) -> tuple[int, int]:
        """Compatibility wrapper for the shared project relocation routine."""
        return project.relocate_images(new_root)

    def _merge_ribbons(self):
        """Merge the selected ribbon with the next one into a single fragment."""
        if not self._apply_edit():
            return
        if self._selected is None or len(self._ribbons) < 2:
            self._status.set("Select the first of two ribbons to merge.")
            return
        if self._selected >= len(self._ribbons) - 1:
            self._status.set("Select the first ribbon (merge with the one below it in the list).")
            return
        r1 = self._ribbons[self._selected]
        r2 = self._ribbons[self._selected + 1]

        # Merge: keep r1, extend it to cover r2
        import math
        lc1 = getattr(r1, "line_coords", None)
        lc2 = getattr(r2, "line_coords", None)
        if lc1 and lc2:
            # Find the two most distant endpoints among the 4
            pts = [(lc1[0], lc1[1]), (lc1[2], lc1[3]),
                   (lc2[0], lc2[1]), (lc2[2], lc2[3])]
            max_d = 0; best = (0, 1)
            for i in range(4):
                for j in range(i+1, 4):
                    d = math.sqrt((pts[i][0]-pts[j][0])**2 + (pts[i][1]-pts[j][1])**2)
                    if d > max_d:
                        max_d = d; best = (i, j)
            r1.line_coords = [pts[best[0]][0], pts[best[0]][1],
                              pts[best[1]][0], pts[best[1]][1]]
        # Update measurements
        r1.bbox_x = (r1.bbox_x + r2.bbox_x) / 2
        r1.bbox_y = (r1.bbox_y + r2.bbox_y) / 2
        l1, l2 = r1.length_nm or 0.0, r2.length_nm or 0.0
        r1.length_nm = round(l1 + l2, 1) if (l1 or l2) else None
        r1.morphology = "fragmented"
        r1.notes = f"merged from R{r1.id}+R{r2.id}: {r1.notes}"
        r1.user_edited = True

        # Remove r2
        self._ribbons.pop(self._selected + 1)
        self._select_ribbon(self._selected)
        self._refresh_ribbon_list()
        self._redraw()
        self._status.set(f"Merged R{r1.id} + R{r2.id} into one fragmented ribbon.")

    # ── Project loading ─────────────────────────────────────────

    def load_project(self, project: Project, project_path: Path | None = None):
        self.project = project
        self._project_path = project_path
        self._saved_state = asdict(project) if project_path else None
        self._ribbons = []
        self._selected = None
        self._pil_raw = self._pil_adj = self._photo = None
        self._image_error = ""
        self._link_first = None
        self._img_results = [ir for ir in project.image_results if ir.analyzed]
        self._cur_idx = 0
        self._refresh_overview()
        if self._img_results:
            self._load_image_at(0)
        else:
            self._refresh_ribbon_list()
            self._redraw()
        self._update_save_status()

    def _cur_image(self) -> ImageResult | None:
        if not self._img_results or self._cur_idx >= len(self._img_results):
            return None
        return self._img_results[self._cur_idx]

    # ── Overview ────────────────────────────────────────────────

    def _refresh_overview(self):
        self._overview_lb.delete(0, "end")
        for i, ir in enumerate(self._img_results):
            reviewed = ir.reviewed or any(r.reviewed for r in ir.ribbons)
            sym = "✓" if reviewed else ("·" if ir.analyzed else "–")
            n = len([r for r in ir.ribbons if not r.rejected])
            label = f"{sym} {ir.image_filename[:20]:<20} {n}r"
            self._overview_lb.insert("end", label)
        if 0 <= self._cur_idx < len(self._img_results):
            self._overview_lb.selection_clear(0, "end")
            self._overview_lb.selection_set(self._cur_idx)
            self._overview_lb.see(self._cur_idx)

    def _on_overview_select(self, event):
        sel = self._overview_lb.curselection()
        if sel and sel[0] != self._cur_idx:
            if self._save_current():
                self._load_image_at(sel[0])

    # ── Image loading ───────────────────────────────────────────

    def _load_image_at(self, idx):
        self._cur_idx = idx
        ir = self._cur_image()
        if not ir:
            return
        self._pil_raw = self._pil_adj = self._photo = None
        self._image_error = ""
        self._link_first = None
        self._ribbons   = copy.deepcopy(ir.ribbons)
        self._selected  = None
        self._draw_mode = None
        self._draw_pts  = []
        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []

        self._title_lbl.config(text=f"  [{idx+1}/{len(self._img_results)}]  {ir.image_filename}")
        self._info_lbl.config(
            text=f"  {ir.age} · {ir.genotype} · scale: {ir.scale_px:g} px = {ir.scale_nm:g} {ir.scale_unit} · empty: {ir.empty_terminal_count}"
        )
        self.empty_terminals_var.set(str(getattr(ir, "empty_terminal_count", 0)))

        try:
            with Image.open(ir.image_path) as source:
                img = source.copy()
            if img.mode not in ("RGB", "L", "RGBA"):
                img = img.convert("RGB")
            self._pil_raw = img
            self._apply_adj()
            self.after(80, self._fit)
        except Exception as e:
            self._image_error = f"Image unavailable: {ir.image_filename}\nOpen the saved project again to locate its image folder."
            self._status.set(f"Could not load image: {e}")
            self._redraw()

        self._refresh_ribbon_list()
        self._refresh_overview()
        self.canvas.focus_set()

    def _apply_adj(self):
        if not self._pil_raw:
            return
        img = self._pil_raw.convert("RGB")
        img = ImageEnhance.Brightness(img).enhance(self._bvar.get())
        img = ImageEnhance.Contrast(img).enhance(self._cvar.get())
        self._pil_adj = img
        self._redraw()

    def _reset_adj(self):
        self._bvar.set(1.0); self._cvar.set(1.0)
        self._apply_adj()

    def _fit(self):
        self.update_idletasks()
        if not self._pil_adj:
            return
        cw = self.canvas.winfo_width()  or 900
        ch = self.canvas.winfo_height() or 700
        iw, ih = self._pil_adj.size
        self._zoom  = min(cw / iw, ch / ih, 1.0)
        self._pan_x = (cw - iw * self._zoom) / 2
        self._pan_y = (ch - ih * self._zoom) / 2
        self._redraw()

    # ── Coord helpers ───────────────────────────────────────────

    def _i2c(self, xp, yp):
        if not self._pil_adj:
            return 0, 0
        iw, ih = self._pil_adj.size
        return (self._pan_x + xp/100 * iw * self._zoom,
                self._pan_y + yp/100 * ih * self._zoom)

    def _c2i(self, cx, cy):
        if not self._pil_adj:
            return 50, 50
        iw, ih = self._pil_adj.size
        return ((cx - self._pan_x) / (iw * self._zoom) * 100,
                (cy - self._pan_y) / (ih * self._zoom) * 100)

    def _nm_per_px(self):
        ir = self._cur_image()
        if ir is None:
            return 0.0
        factor = 1000.0 if ir.scale_unit in ("µm", "um", "μm") else 1.0
        return ir.scale_nm * factor / ir.scale_px

    def _px_dist_to_nm(self, pct_dist):
        if not self._pil_adj:
            return 0.0
        return round(pct_dist / 100 * self._pil_adj.width * self._nm_per_px(), 1)

    def _point_distance(self, a, b):
        """Distance as a percentage of image width, with aspect ratio preserved."""
        return math.hypot(b[0] - a[0],
                          (b[1] - a[1]) * self._pil_adj.height / self._pil_adj.width)

    def _curve_width_pct(self, xp, yp):
        """Retain the existing midpoint estimate, using the actual pointer position."""
        midpoints = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                     for a, b in zip(self._draw_pts, self._draw_pts[1:])]
        if not midpoints:
            return 0.0
        centre = (sum(p[0] for p in midpoints) / len(midpoints),
                  sum(p[1] for p in midpoints) / len(midpoints))
        return self._point_distance(centre, (xp, yp)) * 2

    def _zoom_btn(self, factor):
        """Zoom from button click (centered on canvas)."""
        if not self._pil_adj:
            return
        cw = self.canvas.winfo_width() / 2
        ch = self.canvas.winfo_height() / 2
        nz = max(0.1, min(10.0, self._zoom * factor))
        self._pan_x = cw - (cw - self._pan_x) * (nz / self._zoom)
        self._pan_y = ch - (ch - self._pan_y) * (nz / self._zoom)
        self._zoom = nz
        self._redraw()

    # ── Zoom / Pan ──────────────────────────────────────────────

    def _scroll(self, event):
        if not self._pil_adj:
            return
        f = 1.15 if (event.num == 4 or event.delta > 0) else 1/1.15
        nz = max(0.1, min(10.0, self._zoom * f))
        self._pan_x = event.x - (event.x - self._pan_x) * (nz/self._zoom)
        self._pan_y = event.y - (event.y - self._pan_y) * (nz/self._zoom)
        self._zoom = nz
        self._redraw()

    def _on_right_click(self, event):
        if self._draw_mode == "curve" and self._draw_pts and not getattr(self, '_draw_width_mode', False):
            # Right click = finish axis, enter width mode
            self._draw_width_mode = True
            self._status.set("Width mode: move mouse to preview width. Right-click again to confirm.")
            self._redraw_draw_preview()
        elif self._draw_mode == "curve" and getattr(self, '_draw_width_mode', False):
            # Second right-click = confirm width
            xp, yp = self._c2i(event.x, event.y)
            self._finish_curve_draw(xp, yp)
        else:
            self._pan_start_ev(event)

    def _pan_start_ev(self, e): self._pan_start = (e.x, e.y, self._pan_x, self._pan_y)
    def _pan_move_ev(self, e):
        if self._pan_start:
            sx,sy,ox,oy = self._pan_start
            self._pan_x = ox + e.x - sx
            self._pan_y = oy + e.y - sy
            self._redraw()
    def _pan_end_ev(self, e): self._pan_start = None
    def _set_space(self, v):
        self._space = v
        self.canvas.config(cursor="fleur" if v else ("plus" if self._draw_mode else "crosshair"))

    # ── Canvas events ───────────────────────────────────────────

    def _on_click(self, event):
        if self._space:
            self._pan_start_ev(event); return
        if not self._pil_adj:
            return
        self.canvas.focus_set()
        if not self._draw_mode:
            self._pan_start_ev(event)
            return

        xp, yp = self._c2i(event.x, event.y)
        if not (0 <= xp <= 100 and 0 <= yp <= 100):
            self._status.set("Place annotation points inside the image.")
            return

        if self._draw_mode == "curve":
            if getattr(self, '_draw_width_mode', False):
                # Width click — finish
                self._finish_curve_draw(xp, yp)
            else:
                # Add axis point
                self._draw_pts.append((xp, yp))
                self._status.set(f"Curve: {len(self._draw_pts)} point(s). Left=add more, Right=finish axis and set width.")
                self._redraw_draw_preview()
        elif self._draw_mode == "spherical":
            self._draw_pts.append((xp, yp))
            if len(self._draw_pts) == 2:
                self._finish_spherical_draw()
            else:
                self._status.set("SPHERICAL: Click to set radius.")
        elif self._draw_mode == "axis":
            self._draw_pts.append((xp, yp))
            if len(self._draw_pts) == 2:
                self._finish_draw()
            else:
                self._status.set("Click END of ribbon.")
        elif self._draw_mode == "full":
            self._draw_pts.append((xp, yp))
            needed = 3
            if len(self._draw_pts) == needed:
                self._finish_draw()
            else:
                n = len(self._draw_pts)
                self._status.set(f"Point {n}/{needed}. {'Click end.' if n==1 else 'Click to set width.'}")

    def _on_motion(self, event):
        """Mouse move (no button held) — show draw preview."""
        if self._draw_mode and self._draw_pts:
            self._show_draw_preview(event.x, event.y)

    def _on_drag(self, event):
        if self._space:
            self._pan_move_ev(event); return
        if not self._draw_mode:
            self._pan_move_ev(event); return
        # Show live preview
        self._show_draw_preview(event.x, event.y)

    def _on_release(self, event):
        if self._space or not self._draw_mode:
            self._pan_end_ev(event)

    # ── Draw mode ───────────────────────────────────────────────

    def _start_draw(self, mode):
        if self._pil_adj is None or self._cur_image() is None:
            self._status.set("Load an image folder or open a saved project first.")
            return
        if not self._apply_edit():
            return
        self.canvas.focus_set()
        # Toggle off if same mode clicked again
        if self._draw_mode == mode:
            self._cancel_draw()
            return
        self._draw_mode = mode
        self._draw_pts  = []
        self._draw_width_mode = False
        self._draw_width_val = 0
        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []
        self.canvas.config(cursor="plus")
        if mode == "axis":
            self._status.set("DRAW: Click START, then click END of ribbon.")
        elif mode == "curve":
            self._status.set("DRAW CURVE: Left-click to add points along ribbon. Right-click to finish axis (then set width).")
        elif mode == "spherical":
            self._status.set("DRAW SPHERICAL: Click CENTER of ribbon, then click to set RADIUS.")
        else:
            self._status.set("DRAW: Click START, then END, then click to set WIDTH.")

    def _cancel_draw(self):
        self._draw_mode = None
        self._draw_pts  = []
        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []
        self.canvas.config(cursor="crosshair")
        self._status.set("Draw cancelled.")

    def _redraw_draw_preview(self):
        """Redraw the polyline preview from stored points."""
        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []
        if not self._draw_pts:
            return
        # Draw existing segments
        for i in range(len(self._draw_pts) - 1):
            x1c, y1c = self._i2c(*self._draw_pts[i])
            x2c, y2c = self._i2c(*self._draw_pts[i + 1])
            col = "#00ff88" if not getattr(self, '_draw_width_mode', False) else "#88ffaa"
            t = self.canvas.create_line(x1c, y1c, x2c, y2c,
                                         fill=col, width=3, capstyle="round")
            self._draw_tmps.append(t)
            # Dot at each point
            t2 = self.canvas.create_oval(x1c-3, y1c-3, x1c+3, y1c+3, fill=col, outline="")
            self._draw_tmps.append(t2)
        # Last point dot
        lx, ly = self._i2c(*self._draw_pts[-1])
        t3 = self.canvas.create_oval(lx-3, ly-3, lx+3, ly+3, fill="#00ff88", outline="")
        self._draw_tmps.append(t3)

    def _show_draw_preview(self, mouse_x, mouse_y):
        """Show live preview line from last point to mouse."""
        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []
        if not self._draw_pts:
            return

        # Draw existing segments
        for i in range(len(self._draw_pts) - 1):
            x1c, y1c = self._i2c(*self._draw_pts[i])
            x2c, y2c = self._i2c(*self._draw_pts[i + 1])
            t = self.canvas.create_line(x1c, y1c, x2c, y2c,
                                         fill="#00ff88", width=3, capstyle="round")
            self._draw_tmps.append(t)
            t2 = self.canvas.create_oval(x1c-3, y1c-3, x1c+3, y1c+3, fill="#00ff88", outline="")
            self._draw_tmps.append(t2)

        # Spherical preview: center dot + live circle
        if self._draw_mode == "spherical" and len(self._draw_pts) == 1:
            cx, cy = self._i2c(*self._draw_pts[0])
            r_px = math.sqrt((mouse_x - cx)**2 + (mouse_y - cy)**2)
            t_c = self.canvas.create_oval(cx-4, cy-4, cx+4, cy+4,
                                           fill="#ff9944", outline="", tags="sph_prev")
            self._draw_tmps.append(t_c)
            t_circ = self.canvas.create_oval(cx - r_px, cy - r_px, cx + r_px, cy + r_px,
                                              outline="#ff9944", width=2, dash=(4, 3),
                                              tags="sph_prev")
            self._draw_tmps.append(t_circ)
            if self._pil_adj and self.project:
                mouse_pct = self._c2i(mouse_x, mouse_y)
                cp = self._draw_pts[0]
                radius_pct = self._point_distance(cp, mouse_pct)
                diam_nm = self._px_dist_to_nm(radius_pct * 2)
                t_txt = self.canvas.create_text(mouse_x + 12, mouse_y,
                                                 text=f"⌀ {diam_nm:.0f}nm",
                                                 fill="#ff9944", font=("Helvetica", 10),
                                                 anchor="w")
                self._draw_tmps.append(t_txt)
            return

        # Preview line from last point to mouse
        lx, ly = self._i2c(*self._draw_pts[-1])
        if getattr(self, '_draw_width_mode', False):
            # Width preview: show the polyline with thickness
            # Calculate perpendicular distance from mouse to nearest segment midpoint
            mid_pts = []
            for i in range(len(self._draw_pts) - 1):
                mx = (self._draw_pts[i][0] + self._draw_pts[i+1][0]) / 2
                my = (self._draw_pts[i][1] + self._draw_pts[i+1][1]) / 2
                mid_pts.append((mx, my))
            if mid_pts:
                mouse_pct = self._c2i(mouse_x, mouse_y)
                # Use perpendicular distance from mouse to the polyline center
                width_pct = self._curve_width_pct(*mouse_pct)
                self._draw_width_val = width_pct
                # Redraw polyline with width
                for i in range(len(self._draw_pts) - 1):
                    x1c, y1c = self._i2c(*self._draw_pts[i])
                    x2c, y2c = self._i2c(*self._draw_pts[i + 1])
                    # Convert width_pct to canvas pixels
                    if self._pil_adj:
                        w_canvas = width_pct / 100 * self._pil_adj.size[0] * self._zoom
                    else:
                        w_canvas = 10
                    t = self.canvas.create_line(x1c, y1c, x2c, y2c,
                                                 fill="#88aaff", width=max(2, w_canvas),
                                                 capstyle="round")
                    self._draw_tmps.append(t)
                # Width indicator text
                if self._pil_adj and self.project:
                    w_nm = self._px_dist_to_nm(width_pct)
                    t_txt = self.canvas.create_text(mouse_x + 15, mouse_y,
                                                     text=f"width: {w_nm:.0f}nm",
                                                     fill="#88aaff", font=("Helvetica", 10),
                                                     anchor="w")
                    self._draw_tmps.append(t_txt)
        else:
            # Normal: show line from last point to mouse
            t = self.canvas.create_line(lx, ly, mouse_x, mouse_y,
                                         fill="#ffffff", width=2, dash=(4, 3), capstyle="round")
            self._draw_tmps.append(t)

    def _finish_spherical_draw(self):
        """Finish spherical ribbon: center + radius point → circle with diameter as width."""
        if len(self._draw_pts) < 2:
            self._cancel_draw()
            return

        cx_pct, cy_pct = self._draw_pts[0]
        rx_pct, ry_pct = self._draw_pts[1]
        radius_pct = self._point_distance((cx_pct, cy_pct), (rx_pct, ry_pct))
        diameter_pct = radius_pct * 2
        diameter_nm = self._px_dist_to_nm(diameter_pct) or None

        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []
        self._draw_mode = None
        self._draw_pts = []
        self.canvas.config(cursor="crosshair")

        ir = self._cur_image()
        new_id = max((r.id for r in self._ribbons), default=0) + 1
        r = RibbonAnnotation(
            id=new_id,
            image_path=ir.image_path, image_filename=ir.image_filename,
            folder_name=ir.folder_name, age=ir.age, genotype=ir.genotype,
            bbox_x=cx_pct, bbox_y=cy_pct,
            bbox_w=diameter_pct, bbox_h=diameter_pct * self._pil_adj.width / self._pil_adj.height,
            length_nm=None, width_nm=diameter_nm,
            morphology="spherical", confidence="high",
            vesicle_halo=True, anchored_to_az=True,
            notes="manually drawn (spherical)", reviewed=True, accepted=True, user_edited=True,
            scale_px=ir.scale_px,
            scale_nm=ir.scale_nm,
            scale_unit=ir.scale_unit,
            image_width_px=self._pil_adj.width, image_height_px=self._pil_adj.height,
            length_not_measured=True,
        )
        # Store as circle via bbox (no line_coords, no polyline_pts → oval branch in _draw_ribbon)

        self._ribbons.append(r)
        self._select_ribbon(len(self._ribbons) - 1)
        self._refresh_ribbon_list()
        self._redraw()
        d_str = f"{diameter_nm:.0f}nm" if diameter_nm is not None else "--"
        self._status.set(f"Spherical R{new_id} — diameter {d_str}. Height not measured.")

    def _finish_curve_draw(self, xp, yp):
        """Finish curved ribbon: compute total length from segments, set width."""
        if len(self._draw_pts) < 2:
            self._cancel_draw()
            return

        pts = self._draw_pts

        # Total length = sum of segment lengths
        total_length_pct = 0
        for i in range(len(pts) - 1):
            total_length_pct += self._point_distance(pts[i], pts[i+1])

        length_nm = self._px_dist_to_nm(total_length_pct) or None
        width_nm = self._px_dist_to_nm(self._curve_width_pct(xp, yp)) or None

        # Center and bounding box
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bw = max(max(xs) - min(xs) + 0.5, 0.5)
        bh = max(max(ys) - min(ys) + 0.5, 0.5)

        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []

        ir = self._cur_image()
        new_id = max((r.id for r in self._ribbons), default=0) + 1
        r = RibbonAnnotation(
            id=new_id,
            image_path=ir.image_path, image_filename=ir.image_filename,
            folder_name=ir.folder_name, age=ir.age, genotype=ir.genotype,
            bbox_x=cx, bbox_y=cy, bbox_w=bw, bbox_h=bh,
            length_nm=length_nm, width_nm=width_nm,
            morphology="normal", confidence="high",
            vesicle_halo=True, anchored_to_az=True,
            notes="manually drawn (curved)", reviewed=True, accepted=True, user_edited=True,
            scale_px=ir.scale_px,
            scale_nm=ir.scale_nm,
            scale_unit=ir.scale_unit,
            image_width_px=self._pil_adj.width, image_height_px=self._pil_adj.height,
        )
        # Store all polyline points
        r.line_coords = [coord for pt in pts for coord in pt]  # flat list
        r.polyline_pts = pts  # keep original

        self._draw_mode = None
        self._draw_pts = []
        self._draw_width_mode = False
        self._draw_width_val = 0
        self.canvas.config(cursor="crosshair")

        self._ribbons.append(r)
        self._select_ribbon(len(self._ribbons) - 1)
        self._refresh_ribbon_list()
        self._redraw()
        ln_str = f"{length_nm:.0f}nm" if length_nm is not None else "--"
        wn_str = f", width {width_nm:.0f}nm" if width_nm is not None else ""
        self._status.set(f"Curved ribbon R{new_id} — length {ln_str}{wn_str}")

    def _finish_draw(self):
        pts = self._draw_pts
        x1p, y1p = pts[0]
        x2p, y2p = pts[1]

        length_nm = self._px_dist_to_nm(self._point_distance(pts[0], pts[1]))

        # Width from 3rd point (perpendicular distance)
        width_nm = None
        if self._draw_mode == "full" and len(pts) >= 3:
            x3p, y3p = pts[2]
            # perpendicular distance from point 3 to line 1-2
            aspect = self._pil_adj.height / self._pil_adj.width
            y1, y2, y3 = y1p * aspect, y2p * aspect, y3p * aspect
            dx, dy = x2p-x1p, y2-y1
            ln = math.hypot(dx, dy) or 1
            dist = abs(dy*x3p - dx*y3 + x2p*y1 - y2*x1p) / ln
            width_nm = self._px_dist_to_nm(dist * 2) or None  # full width = 2× half-width

        cx, cy = (x1p+x2p)/2, (y1p+y2p)/2
        bw = max(abs(x2p-x1p)+0.5, 0.5)
        bh = max(abs(y2p-y1p)+0.5, 0.5)

        for t in self._draw_tmps:
            self.canvas.delete(t)
        self._draw_tmps = []
        self._draw_mode = None
        self._draw_pts  = []
        self.canvas.config(cursor="crosshair")

        ir = self._cur_image()
        new_id = max((r.id for r in self._ribbons), default=0) + 1
        r = RibbonAnnotation(
            id=new_id,
            image_path=ir.image_path, image_filename=ir.image_filename,
            folder_name=ir.folder_name, age=ir.age, genotype=ir.genotype,
            bbox_x=cx, bbox_y=cy, bbox_w=bw, bbox_h=bh,
            length_nm=length_nm, width_nm=width_nm,
            length_relative=bh, width_relative=bw,
            morphology="normal", confidence="high",
            vesicle_halo=True, anchored_to_az=True,
            notes="manually drawn", reviewed=True, accepted=True, user_edited=True,
            scale_px=ir.scale_px,
            scale_nm=ir.scale_nm,
            scale_unit=ir.scale_unit,
            image_width_px=self._pil_adj.width, image_height_px=self._pil_adj.height,
        )
        r.line_coords = [x1p, y1p, x2p, y2p]

        self._ribbons.append(r)
        self._select_ribbon(len(self._ribbons)-1)
        self._refresh_ribbon_list()
        self._redraw()
        ln_str = f"{length_nm:.0f} nm" if length_nm is not None else "--"
        wn_str = f", width {width_nm:.0f} nm" if width_nm is not None else ""
        self._status.set(f"R{new_id} drawn — length {ln_str}{wn_str}. Edit in right panel, then Accept.")

    # ── Redraw ──────────────────────────────────────────────────

    def _redraw(self):
        self.canvas.delete("all")
        if not hasattr(self, "_pil_adj") or self._pil_adj is None:
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            self.canvas.create_text(cw/2, ch/2, text=self._image_error or
                "Annotate ribbons by hand\n\nLoad an image folder or open a saved project to begin.\nStraight axes · curved axes · spherical profiles\n\nImages and annotations stay on this computer.",
                fill=UI_TEXT_DIM, font=("Helvetica", 12), justify="center",
                width=max(180, cw-48))
            return
        iw, ih = self._pil_adj.size
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        x0 = max(0, int(-self._pan_x / self._zoom))
        y0 = max(0, int(-self._pan_y / self._zoom))
        x1 = min(iw, math.ceil((cw-self._pan_x) / self._zoom))
        y1 = min(ih, math.ceil((ch-self._pan_y) / self._zoom))
        if x1 > x0 and y1 > y0:
            crop = self._pil_adj.crop((x0, y0, x1, y1))
            disp = crop.resize((max(1, round(crop.width*self._zoom)),
                                max(1, round(crop.height*self._zoom))), Image.Resampling.LANCZOS)
            self._photo = ImageTk.PhotoImage(disp, master=self.canvas)
            self.canvas.create_image(self._pan_x+x0*self._zoom, self._pan_y+y0*self._zoom,
                                     anchor="nw", image=self._photo)
        for i, r in enumerate(self._ribbons):
            self._draw_ribbon(i, r)

    def _draw_ribbon(self, i, r):
        sel  = (i == self._selected)
        col  = MORPHOLOGY_COLORS.get(r.morphology, "#a9b9c6")
        if r.rejected:
            col = "#444444"
        elif sel:
            col = "#ffffff"
        lw   = 3.5 if sel else 2.0
        dash = (5, 4) if r.rejected else None
        tag  = f"r{i}"

        poly_pts = getattr(r, "polyline_pts", None)
        lc = getattr(r, "line_coords", None)

        if poly_pts and len(poly_pts) >= 2:
            # Draw polyline (curved ribbon)
            canvas_pts = [self._i2c(p[0], p[1]) for p in poly_pts]
            # Draw line width if set
            w_canvas = max(lw * 2, 4)
            if (r.width_nm or 0) > 0 and self._pil_adj and self.project:
                w_px = r.width_nm / self._nm_per_px()
                if self._pil_adj:
                    w_canvas = max(4, w_px / self._pil_adj.size[0] * 100 / 100 * self._pil_adj.size[0] * self._zoom)
            for seg in range(len(canvas_pts) - 1):
                x1c, y1c = canvas_pts[seg]
                x2c, y2c = canvas_pts[seg + 1]
                self.canvas.create_line(x1c, y1c, x2c, y2c, fill=col,
                                         width=w_canvas, dash=dash, tags=tag, capstyle="round")
            # End ticks
            if len(canvas_pts) >= 2:
                for px, py in [canvas_pts[0], canvas_pts[-1]]:
                    self.canvas.create_oval(px-4, py-4, px+4, py+4,
                                             fill=col, outline="", tags=tag)
        elif lc and len(lc) == 4:
            x1c, y1c = self._i2c(lc[0], lc[1])
            x2c, y2c = self._i2c(lc[2], lc[3])
            self.canvas.create_line(x1c, y1c, x2c, y2c, fill=col, width=lw*2,
                                     dash=dash, tags=tag, capstyle="round")
            dx, dy = x2c-x1c, y2c-y1c
            ln = max(1, math.sqrt(dx*dx+dy*dy))
            nx, ny = -dy/ln*8, dx/ln*8
            for px, py in [(x1c, y1c), (x2c, y2c)]:
                self.canvas.create_line(px-nx, py-ny, px+nx, py+ny,
                                         fill=col, width=1.5)
            # Width indicator
            if (r.width_nm or 0) > 0 and self.project:
                w_pct = r.width_nm / self._nm_per_px()
                if self._pil_adj:
                    w_pct = w_pct / self._pil_adj.size[0] * 100
                mx, my = (x1c+x2c)/2, (y1c+y2c)/2
                ux, uy = -dy/ln * w_pct/100*self._pil_adj.size[0]*self._zoom/2, \
                          dx/ln * w_pct/100*self._pil_adj.size[0]*self._zoom/2
                self.canvas.create_line(mx-ux, my-uy, mx+ux, my+uy,
                                         fill=col, width=1, dash=(2, 3))
        else:
            x1c, y1c = self._i2c(r.bbox_x - r.bbox_w/2, r.bbox_y - r.bbox_h/2)
            x2c, y2c = self._i2c(r.bbox_x + r.bbox_w/2, r.bbox_y + r.bbox_h/2)
            self.canvas.create_oval(x1c, y1c, x2c, y2c,
                                     outline=col, width=lw, dash=dash, tags=tag)

        lx, ly = self._i2c(r.bbox_x, r.bbox_y - r.bbox_h/2)
        sym = "✓" if r.accepted else ("✗" if r.rejected else "")
        ln_str = f"{r.length_nm:.0f}nm" if r.length_nm is not None else "--"
        lbl = f"R{r.id}{sym} {ln_str}"
        self.canvas.create_text(lx, ly-9, text=lbl, fill=col,
                                 font=("Helvetica", 9, "bold"), tags=f"{tag}l")
        for t in (tag, f"{tag}l"):
            self.canvas.tag_bind(t, "<Button-1>", lambda e, idx=i: self._request_selection(idx))

    # ── Ribbon list ─────────────────────────────────────────────

    def _refresh_ribbon_list(self):
        self._update_save_status()
        self._ribbon_lb.delete(0, "end")
        for r in self._ribbons:
            s = "✓" if r.accepted else ("✗" if r.rejected else "·")
            ln = "?nm" if getattr(r, "length_not_measured", False) else (f"{r.length_nm:.0f}nm" if r.length_nm is not None else "--")
            self._ribbon_lb.insert("end",
                f" {s} R{r.id} {r.morphology[:9]:<9} {ln}")
        if self._selected is not None and self._selected < len(self._ribbons):
            self._ribbon_lb.selection_clear(0, "end")
            self._ribbon_lb.selection_set(self._selected)
            self._ribbon_lb.see(self._selected)

    def _on_ribbon_select(self, event):
        sel = self._ribbon_lb.curselection()
        if sel:
            self._request_selection(sel[0])

    def _request_selection(self, idx):
        """Apply pending edits before a user selects another profile."""
        if not self._apply_edit():
            self._refresh_ribbon_list()
            return
        self._select_ribbon(idx)

    def _select_ribbon(self, idx):
        if not (0 <= idx < len(self._ribbons)):
            return
        self._selected = idx
        r = self._ribbons[idx]
        self.morph_var.set(r.morphology)
        self.conf_var.set(r.confidence)
        lnm = getattr(r, "length_not_measured", False)
        self.length_not_measured_var.set(lnm)
        self._length_entry.config(state="disabled" if lnm else "normal")
        self.length_var.set("" if lnm else (f"{r.length_nm:.1f}" if r.length_nm is not None else ""))
        self.width_var.set(f"{r.width_nm:.1f}" if r.width_nm is not None else "")
        self.vesicle_count_var.set(str(getattr(r, "vesicle_count", 0)))
        self.vesicle_shell_var.set(f"{getattr(r, 'vesicle_shell_nm', 50.0):.0f}")
        self.halo_var.set(r.vesicle_halo)
        self.az_var.set(r.anchored_to_az)
        self.inside_var.set(getattr(r, "inside_spherule", True))
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", r.notes)
        self._ai_lbl.config(text=r.notes[:100] if not r.user_edited else "(user-edited)")
        ln_str = f"{r.length_nm:.0f}nm" if r.length_nm is not None else "--"
        self._status.set(f"R{r.id} · {r.morphology} · {r.confidence} · {ln_str}")
        self._refresh_ribbon_list()
        self._redraw()

    def _link_fragments(self):
        """Link two selected ribbons as fragments of one ribbon.
        Merges the second into the first, combining their measurements."""
        if len(self._ribbons) < 2:
            self._status.set("Need at least 2 ribbons to link fragments.")
            return
        if self._selected is None:
            self._status.set("Select the FIRST fragment, then click Link, then select the SECOND.")
            return
        # Store first selection, ask for second
        if not hasattr(self, '_link_first') or self._link_first is None:
            self._link_first = self._selected
            self._status.set(f"Fragment 1 = R{self._ribbons[self._selected].id}. Now click the SECOND fragment and press Link again.")
        else:
            idx2 = self._selected
            if idx2 == self._link_first:
                self._status.set("Same ribbon selected twice. Select a different one.")
                return
            r1 = self._ribbons[self._link_first]
            r2 = self._ribbons[idx2]
            # Combine: keep r1, merge r2 length, mark as fragmented
            l1, l2 = r1.length_nm or 0.0, r2.length_nm or 0.0
            r1.length_nm = round(l1 + l2, 1) if (l1 or l2) else None
            r1.morphology = "fragmented"
            r1.notes = f"Linked from R{r1.id}+R{r2.id}. {r1.notes}"
            r1.user_edited = True
            r1.reviewed = True
            # Remove r2
            self._ribbons.pop(idx2)
            self._link_first = None
            self._selected = self._ribbons.index(r1)
            self._select_ribbon(self._selected)
            self._refresh_ribbon_list()
            self._redraw()
            self._status.set(f"Fragments linked into R{r1.id} — marked as fragmented.")

    # ── Editor ──────────────────────────────────────────────────

    def _on_length_not_measured(self):
        """Toggle the length entry field based on the checkbox state."""
        if self.length_not_measured_var.get():
            self._length_entry.config(state="disabled", disabledforeground="#666666")
            self.length_var.set("")
        else:
            self._length_entry.config(state="normal")
        self._apply_edit()

    def _apply_edit(self):
        if self._selected is None or not self._ribbons:
            return True
        r = self._ribbons[self._selected]
        def number(value, optional=False):
            if optional and not value.strip():
                return None
            result = float(value)
            if not math.isfinite(result) or result < 0:
                raise ValueError
            return result
        try:
            length = None if self.length_not_measured_var.get() else number(self.length_var.get(), True)
            width = number(self.width_var.get(), True)
            count = number(self.vesicle_count_var.get() or "0")
            if not count.is_integer():
                raise ValueError
            shell = number(self.vesicle_shell_var.get() or "0")
        except (ValueError, OverflowError):
            self._status.set("Use finite, non-negative measurements and a whole vesicle count. Clear a measurement to leave it unmeasured.")
            return False
        before = asdict(r)
        r.morphology = self.morph_var.get()
        r.confidence = self.conf_var.get()
        r.vesicle_halo = self.halo_var.get()
        r.anchored_to_az = self.az_var.get()
        r.inside_spherule = self.inside_var.get()
        r.notes = self.notes_text.get("1.0", "end").strip()
        r.length_not_measured = self.length_not_measured_var.get()
        r.length_nm, r.width_nm = length, width
        r.vesicle_count, r.vesicle_shell_nm = int(count), shell
        if asdict(r) != before:
            r.user_edited = True
        self._refresh_ribbon_list()
        self._redraw()
        self._update_save_status()
        return True

    def _apply_image_fields(self):
        ir = self._cur_image()
        if not ir:
            return True
        try:
            count = float(self.empty_terminals_var.get() or "0")
            if not math.isfinite(count) or count < 0 or not count.is_integer():
                raise ValueError
            ir.empty_terminal_count = int(count)
            self.empty_terminals_var.set(str(ir.empty_terminal_count))
        except (ValueError, OverflowError):
            self._status.set("Empty terminals must be a non-negative whole number.")
            return False
        self._info_lbl.config(
            text=f"  {ir.age} · {ir.genotype} · {ir.image_quality} · empty terminals: {ir.empty_terminal_count}"
        )
        return True

    def _estimate_vesicles(self):
        if self._selected is None or not self._ribbons or self._pil_raw is None or self.project is None:
            return
        r = self._ribbons[self._selected]
        try:
            shell_nm = max(0.0, float(self.vesicle_shell_var.get() or "50"))
        except ValueError:
            shell_nm = 50.0
        try:
            from scipy.ndimage import gaussian_laplace, label, binary_opening
        except Exception:
            self._status.set("Vesicle estimate needs scipy.")
            return

        img = self._pil_raw.convert("L")
        arr = np.array(img, dtype=np.float64)
        h, w = arr.shape
        nm_per_px = self._nm_per_px()
        shell_px = shell_nm / max(nm_per_px, 1e-6)
        ves_d_px = max(40.0 / nm_per_px, 3.5)
        ves_r_px = ves_d_px / 2.0

        yy, xx = np.indices(arr.shape)
        cx = r.bbox_x / 100.0 * w
        cy = r.bbox_y / 100.0 * h
        bw = max(r.bbox_w / 100.0 * w, 4.0)
        bh = max(r.bbox_h / 100.0 * h, 4.0)

        a = math.radians(getattr(r, "angle_deg", 0.0))
        xr = (xx - cx) * math.cos(a) + (yy - cy) * math.sin(a)
        yr = -(xx - cx) * math.sin(a) + (yy - cy) * math.cos(a)
        core = (np.abs(xr) <= bw * 0.65) & (np.abs(yr) <= bh * 0.85)
        ring = (np.abs(xr) <= bw * 0.65 + shell_px) & (np.abs(yr) <= bh * 0.85 + shell_px) & ~core
        if ring.sum() < 25:
            self._status.set("Vesicle estimate: ring too small.")
            return

        sigma = max(ves_r_px * 0.45, 0.9)
        resp = -gaussian_laplace(arr, sigma=sigma)
        resp = np.clip(resp, 0, None)
        ring_vals = resp[ring]
        thresh = np.percentile(ring_vals, 82) if ring_vals.size else 0
        blob_mask = (resp >= thresh) & ring
        blob_mask = binary_opening(blob_mask, iterations=1)
        labeled, nlab = label(blob_mask)
        count = 0
        min_area = max(int((ves_r_px * 0.5) ** 2), 3)
        max_area = max(int((ves_r_px * 2.2) ** 2), 10)
        for lab in range(1, nlab + 1):
            area = int((labeled == lab).sum())
            if min_area <= area <= max_area:
                count += 1
        r.vesicle_count = count
        r.vesicle_shell_nm = shell_nm
        self.vesicle_count_var.set(str(count))
        self.vesicle_shell_var.set(f"{shell_nm:.0f}")
        self._status.set(f"Vesicle estimate for R{r.id}: ~{count} in {shell_nm:.0f} nm shell.")

    def _accept(self):
        if not self._apply_edit():
            return
        if self._selected is not None and self._ribbons:
            r = self._ribbons[self._selected]
            r.accepted = True; r.rejected = False; r.reviewed = True
            self._refresh_ribbon_list(); self._redraw()
            nxt = self._selected + 1
            if nxt < len(self._ribbons):
                self._select_ribbon(nxt)
            else:
                self._status.set("All ribbons reviewed. Press → to go to next image.")

    def _reject(self):
        if not self._apply_edit():
            return
        if self._selected is not None and self._ribbons:
            r = self._ribbons[self._selected]
            r.rejected = True; r.accepted = False; r.reviewed = True
            r.rejection_reason = (self.notes_text.get("1.0","end").strip()
                                   or "false positive")
            self._refresh_ribbon_list(); self._redraw()
            nxt = self._selected + 1
            if nxt < len(self._ribbons):
                self._select_ribbon(nxt)

    def _delete_selected(self):
        if self._selected is not None and self._ribbons:
            self._ribbons.pop(self._selected)
            self._selected = (min(self._selected, len(self._ribbons)-1)
                               if self._ribbons else None)
            self._link_first = None
            if self._selected is not None:
                self._select_ribbon(self._selected)
            else:
                self.length_var.set("")
                self.width_var.set("")
                self.notes_text.delete("1.0", "end")
            self._refresh_ribbon_list(); self._redraw()

    # ── Navigation ──────────────────────────────────────────────

    def _save_current(self, mark_reviewed=True, save_training=True):
        ir = self._cur_image()
        if ir:
            if not self._apply_edit() or not self._apply_image_fields():
                return False
            ir.ribbons = copy.deepcopy(self._ribbons)
            ir.analyzed = True
            if mark_reviewed:
                ir.reviewed = True
            if save_training:
                self._try_save_training(ir)
        return True

    def _save_next(self):
        if not self._save_project():
            return
        if self._cur_idx + 1 < len(self._img_results):
            self._load_image_at(self._cur_idx + 1)
        else:
            self._status.set("All images reviewed. Annotations saved to disk.")
            self._refresh_overview()

    def _prev(self):
        if self._save_current() and self._cur_idx > 0:
            self._load_image_at(self._cur_idx - 1)

    def _skip(self):
        if self._cur_idx + 1 < len(self._img_results):
            self._load_image_at(self._cur_idx + 1)
        else:
            self._status.set("Last image — no next image to skip to.")

    def _try_save_training(self, ir: ImageResult):
        reviewed = [r for r in ir.ribbons if r.reviewed]
        if not reviewed:
            return
        try:
            from .engine import save_training_example, log_improvement
            accepted = [{"morphology": r.morphology, "notes": r.notes,
                          "vesicle_halo": r.vesicle_halo,
                          "anchored_to_az": r.anchored_to_az}
                         for r in ir.ribbons if r.accepted and not r.rejected]
            rejected = [{"rejection_reason": getattr(r, "rejection_reason",
                          r.notes or "false positive")}
                         for r in ir.ribbons if r.rejected]
            save_training_example(ir.image_path, accepted, rejected)
            if rejected:
                log_improvement(
                    f"Image: {ir.image_filename}\n"
                    "Rejected: " + "; ".join(r["rejection_reason"] for r in rejected[:3])
                )
        except Exception:
            pass

    # ── Project save ────────────────────────────────────────────

    def _load_project_file(self):
        self._load_project_dialog()

    def _update_save_status(self):
        if not hasattr(self, "_save_status"):
            return
        if self.project is None:
            self._save_status.set("No saved project")
            return
        if self._project_path:
            dirty = self._saved_state != asdict(self.project)
            ir = self._cur_image()
            if ir and [asdict(r) for r in self._ribbons] != [asdict(r) for r in ir.ribbons]:
                dirty = True
            self._save_status.set(f"{'Unsaved changes' if dirty else 'Saved'} · {self._project_path.name}")
        elif self.project:
            self._save_status.set("Not saved to disk · use Save annotations")
        else:
            self._save_status.set("No saved project")

    def has_unsaved_changes(self):
        if self.project is None:
            return False
        if not self._apply_edit():
            return True
        state = asdict(self.project)
        ir = self._cur_image()
        if ir:
            try:
                count = float(self.empty_terminals_var.get() or "0")
                if not math.isfinite(count) or count < 0 or not count.is_integer():
                    return True
            except ValueError:
                return True
            index = next(i for i, result in enumerate(self.project.image_results) if result is ir)
            state["image_results"][index]["ribbons"] = [asdict(r) for r in self._ribbons]
            state["image_results"][index]["empty_terminal_count"] = int(count)
        return self._saved_state != state

    def confirm_replace(self):
        if not self.has_unsaved_changes():
            return True
        choice = messagebox.askyesnocancel("Unsaved annotations",
            "Save your current annotations before continuing?\nYes: save. No: discard unsaved changes. Cancel: keep working.", parent=self)
        if choice is None:
            return False
        return self._save_project() if choice else True

    def _save_project(self, save_as=False):
        if not self.project or not self._save_current():
            return False
        path = self._project_path
        if path is None or save_as:
            selected = filedialog.asksaveasfilename(
                defaultextension=".json", filetypes=[("Ribbon Project", "*.json")],
                initialfile=f"{self.project.name}_review.json", title="Save annotations")
            if not selected:
                return False
            path = Path(selected)
        try:
            self.project.save(path)
        except (OSError, ValueError) as error:
            self._status.set(f"Save failed: {error}. Your annotations remain in memory.")
            messagebox.showerror("Could not save annotations", str(error), parent=self)
            return False
        self._project_path = path
        self._saved_state = asdict(self.project)
        self._update_save_status()
        self._status.set(f"Annotations saved: {path.name}")
        return True
