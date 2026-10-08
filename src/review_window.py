"""
Review Window — completely rebuilt
===================================
- Zoomable canvas (scroll wheel)
- Pan (middle mouse / right-click drag / Space+drag)
- Draw mode: click two points to define ribbon axis
- Select ribbons by clicking near them
- Accept / Reject with keyboard shortcuts (A / R)
- Auto-saves training examples on confirm
"""

import tkinter as tk
from tkinter import ttk
import math
import copy
from PIL import Image, ImageTk, ImageEnhance

from .models import RibbonAnnotation, ImageResult
from .config import MORPHOLOGY_CLASSES, MORPHOLOGY_COLORS, UI_BG, UI_PANEL, UI_TEXT, UI_TEXT_DIM


class ReviewWindow(tk.Toplevel):

    def __init__(self, parent, image_result: ImageResult, on_save_callback,
                 scale_px, scale_nm, scale_unit, image_index=0, total_images=1):
        super().__init__(parent)
        self.parent       = parent
        self.ir           = image_result
        self.on_save      = on_save_callback
        self.scale_px     = scale_px
        self.scale_nm     = scale_nm
        self.scale_unit   = scale_unit
        self.image_index  = image_index
        self.total_images = total_images

        self.title(f"Review [{image_index+1}/{total_images}] — {image_result.image_filename} · Nils Hampel FAU")
        self.geometry("1500x950")
        self.configure(bg=UI_BG)

        self.ribbons      = copy.deepcopy(image_result.ribbons)
        self.selected_idx = None
        self._pil_raw     = None
        self._pil_adj     = None
        self._photo       = None

        self._zoom        = 1.0
        self._pan_x       = 0.0
        self._pan_y       = 0.0
        self._pan_start   = None
        self._is_panning  = False
        self._space_held  = False

        self._draw_mode   = False
        self._draw_p1     = None
        self._draw_temp   = None

        self._build_ui()
        self._load_image()
        self._populate_list()

        self.bind("<a>",               lambda e: self._accept_ribbon())
        self.bind("<r>",               lambda e: self._reject_ribbon())
        self.bind("<Delete>",          lambda e: self._delete_selected())
        self.bind("<Escape>",          lambda e: self._cancel_draw())
        self.bind("<Right>",           lambda e: self._save_and_next())
        self.bind("<Left>",            lambda e: self._prev_image())
        self.bind("<KeyPress-space>",  lambda e: self._set_pan(True))
        self.bind("<KeyRelease-space>",lambda e: self._set_pan(False))
        self.focus_set()

    # ─── UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        top = tk.Frame(self, bg="#0f0f1e", pady=5)
        top.pack(fill="x")
        tk.Label(top, text=f"  {self.ir.image_filename}",
                 bg="#0f0f1e", fg=UI_TEXT,
                 font=("Helvetica", 12, "bold")).pack(side="left")
        tk.Label(top, text=f"  {self.ir.age} · {self.ir.genotype} · {self.ir.image_quality}",
                 bg="#0f0f1e", fg=UI_TEXT_DIM, font=("Helvetica", 10)).pack(side="left")
        tk.Label(top, text="  A=Accept  R=Reject  Del=Delete  ←/→=Navigate  Scroll=Zoom  Space+Drag=Pan",
                 bg="#0f0f1e", fg="#444455", font=("Helvetica", 9)).pack(side="left", padx=20)

        nav = tk.Frame(top, bg="#0f0f1e")
        nav.pack(side="right", padx=8)
        tk.Button(nav, text="← Prev",     command=self._prev_image,
                  bg="#16213e", fg="#e0e0e0", relief="flat", padx=8).pack(side="left", padx=2)
        tk.Button(nav, text="Save & Next →", command=self._save_and_next,
                  bg="#1D9E75", fg="white", relief="flat", padx=12,
                  font=("Helvetica", 11, "bold")).pack(side="left", padx=2)
        tk.Button(nav, text="Skip",        command=self._skip,
                  bg="#16213e", fg="#888888", relief="flat", padx=8).pack(side="left", padx=2)

        main = tk.Frame(self, bg=UI_BG)
        main.pack(fill="both", expand=True)

        # Left list
        left = tk.Frame(main, bg=UI_PANEL, width=260)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Ribbons", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 10), pady=6).pack()
        self.listbox = tk.Listbox(left, bg="#0f0f1e", fg=UI_TEXT,
                                   selectbackground="#1D9E75", selectforeground="white",
                                   font=("Helvetica", 11), relief="flat",
                                   borderwidth=0, activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=4)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        bf = tk.Frame(left, bg=UI_PANEL, pady=4)
        bf.pack(fill="x", padx=4)
        tk.Button(bf, text="+ Draw Ribbon (2 clicks)", command=self._start_draw,
                  bg="#378ADD", fg="white", relief="flat",
                  font=("Helvetica", 10)).pack(fill="x", pady=2)
        tk.Button(bf, text="Delete selected", command=self._delete_selected,
                  bg="#993C1D", fg="white", relief="flat",
                  font=("Helvetica", 10)).pack(fill="x", pady=2)

        # Canvas
        cf = tk.Frame(main, bg="#0a0a14")
        cf.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(cf, bg="#0a0a14", cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>",   self._on_click)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>",   self._start_pan)
        self.canvas.bind("<B2-Motion>",       self._do_pan)
        self.canvas.bind("<ButtonRelease-2>", self._end_pan)
        self.canvas.bind("<ButtonPress-3>",   self._start_pan)
        self.canvas.bind("<B3-Motion>",       self._do_pan)
        self.canvas.bind("<ButtonRelease-3>", self._end_pan)
        self.canvas.bind("<MouseWheel>",      self._on_scroll)
        self.canvas.bind("<Button-4>",        self._on_scroll)
        self.canvas.bind("<Button-5>",        self._on_scroll)
        self.canvas.bind("<Configure>",       lambda e: self._redraw())

        # Image adjustments
        ic = tk.Frame(main, bg=UI_PANEL, width=100)
        ic.pack(side="left", fill="y")
        ic.pack_propagate(False)
        for label, attr, default in [("Bright", "_bvar", 1.0), ("Contrast", "_cvar", 1.0)]:
            tk.Label(ic, text=label, bg=UI_PANEL, fg=UI_TEXT_DIM,
                     font=("Helvetica", 8), pady=3).pack()
            v = tk.DoubleVar(value=default)
            setattr(self, attr, v)
            tk.Scale(ic, from_=0.3, to=3.0, resolution=0.05, orient="vertical",
                     variable=v, bg=UI_PANEL, fg=UI_TEXT,
                     troughcolor="#0f0f1e", highlightthickness=0,
                     command=lambda _: self._apply_adj()).pack()
        tk.Button(ic, text="Reset", command=self._reset_adj,
                  bg=UI_PANEL, fg="#e0e0e0", relief="flat",
                  font=("Helvetica", 9)).pack(pady=3)
        tk.Button(ic, text="Fit", command=self._fit_image,
                  bg=UI_PANEL, fg="#e0e0e0", relief="flat",
                  font=("Helvetica", 9)).pack(pady=2)

        # Right editor
        right = tk.Frame(main, bg=UI_PANEL, width=270)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self._build_editor(right)

        self.status_var = tk.StringVar(value="Click ribbon to select · Scroll=Zoom · Space+Drag=Pan · A=Accept R=Reject")
        tk.Label(self, textvariable=self.status_var, bg="#0a0a14", fg="#555555",
                 font=("Helvetica", 9), anchor="w", padx=10).pack(fill="x", side="bottom")

    def _build_editor(self, parent):
        tk.Label(parent, text="Ribbon Editor", bg=UI_PANEL, fg=UI_TEXT_DIM,
                 font=("Helvetica", 10), pady=6).pack()

        ar = tk.Frame(parent, bg=UI_PANEL)
        ar.pack(fill="x", padx=8, pady=4)
        tk.Button(ar, text="✓ Accept (A)", command=self._accept_ribbon,
                  bg="#1D9E75", fg="white", relief="flat",
                  font=("Helvetica", 10, "bold"), width=12).pack(side="left", padx=2)
        tk.Button(ar, text="✗ Reject (R)", command=self._reject_ribbon,
                  bg="#993C1D", fg="white", relief="flat",
                  font=("Helvetica", 10, "bold"), width=12).pack(side="left", padx=2)

        tk.Frame(parent, bg="#2a2a4a", height=1).pack(fill="x", padx=8, pady=4)

        tk.Label(parent, text="Morphology", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 10, "bold")).pack(anchor="w", padx=10)
        self.morph_var = tk.StringVar(value="normal")
        mf = tk.Frame(parent, bg=UI_PANEL)
        mf.pack(anchor="w", padx=14)
        for i, m in enumerate(MORPHOLOGY_CLASSES):
            col = MORPHOLOGY_COLORS.get(m, "#888")
            tk.Radiobutton(mf, text=m, variable=self.morph_var, value=m,
                           bg=UI_PANEL, fg=col, selectcolor="#0f0f1e",
                           activebackground=UI_PANEL, font=("Helvetica", 10),
                           command=self._update_from_editor).grid(
                               row=i//2, column=i%2, sticky="w", padx=4, pady=1)

        tk.Frame(parent, bg="#2a2a4a", height=1).pack(fill="x", padx=8, pady=4)

        tk.Label(parent, text="Measurements", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 10, "bold")).pack(anchor="w", padx=10)
        mf2 = tk.Frame(parent, bg=UI_PANEL)
        mf2.pack(fill="x", padx=12, pady=2)
        self.length_var = tk.StringVar()
        self.width_var  = tk.StringVar()
        for row, (lbl, var) in enumerate([("Length (nm)", self.length_var),
                                           ("Width (nm)",  self.width_var)]):
            tk.Label(mf2, text=lbl, bg=UI_PANEL, fg=UI_TEXT_DIM,
                     font=("Helvetica", 9), width=12, anchor="w").grid(row=row, column=0)
            tk.Entry(mf2, textvariable=var, bg="#0f0f1e", fg=UI_TEXT,
                     insertbackground="white", font=("Helvetica", 10),
                     width=8, relief="flat").grid(row=row, column=1, padx=4, pady=2)

        tk.Frame(parent, bg="#2a2a4a", height=1).pack(fill="x", padx=8, pady=4)

        self.halo_var   = tk.BooleanVar()
        self.az_var     = tk.BooleanVar(value=True)
        self.inside_var = tk.BooleanVar(value=True)
        for text, var in [("Vesicle halo visible", self.halo_var),
                           ("Anchored to active zone", self.az_var),
                           ("Inside rod spherule", self.inside_var)]:
            tk.Checkbutton(parent, text=text, variable=var,
                           bg=UI_PANEL, fg=UI_TEXT, selectcolor="#0f0f1e",
                           activebackground=UI_PANEL, font=("Helvetica", 9),
                           command=self._update_from_editor).pack(anchor="w", padx=12)

        tk.Frame(parent, bg="#2a2a4a", height=1).pack(fill="x", padx=8, pady=4)

        self.conf_var = tk.StringVar(value="medium")
        tk.Label(parent, text="Confidence", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 10, "bold")).pack(anchor="w", padx=10)
        cf = tk.Frame(parent, bg=UI_PANEL)
        cf.pack(anchor="w", padx=14)
        for c in ["high", "medium", "low"]:
            tk.Radiobutton(cf, text=c, variable=self.conf_var, value=c,
                           bg=UI_PANEL, fg=UI_TEXT, selectcolor="#0f0f1e",
                           activebackground=UI_PANEL, font=("Helvetica", 9),
                           command=self._update_from_editor).pack(side="left", padx=4)

        tk.Frame(parent, bg="#2a2a4a", height=1).pack(fill="x", padx=8, pady=4)

        tk.Label(parent, text="Notes / Rejection reason", bg=UI_PANEL, fg="#aaaaaa",
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=10)
        self.notes_text = tk.Text(parent, height=4, bg="#0f0f1e", fg=UI_TEXT,
                                   insertbackground="white", font=("Helvetica", 9),
                                   wrap="word", relief="flat", padx=4, pady=4)
        self.notes_text.pack(fill="x", padx=10)
        self.notes_text.bind("<FocusOut>", lambda e: self._update_from_editor())

        tk.Button(parent, text="Apply", command=self._update_from_editor,
                  bg="#378ADD", fg="white", relief="flat",
                  font=("Helvetica", 10)).pack(pady=6, padx=10, fill="x")

        self.ai_label = tk.Label(parent, text="", bg=UI_PANEL, fg="#555555",
                                  font=("Helvetica", 8), wraplength=240,
                                  justify="left", padx=10, pady=2)
        self.ai_label.pack(anchor="w")

    # ─── Image loading ────────────────────────────────────────────

    def _load_image(self):
        try:
            self._pil_raw = Image.open(self.ir.image_path)
            if self._pil_raw.mode not in ("RGB", "L", "RGBA"):
                self._pil_raw = self._pil_raw.convert("RGB")
            self._apply_adj()
            self.after(100, self._fit_image)
        except Exception as e:
            self.status_var.set(f"Could not load: {e}")

    def _apply_adj(self):
        if not self._pil_raw:
            return
        img = self._pil_raw.convert("RGB")
        img = ImageEnhance.Brightness(img).enhance(self._bvar.get())
        img = ImageEnhance.Contrast(img).enhance(self._cvar.get())
        self._pil_adj = img
        self._redraw()

    def _reset_adj(self):
        self._bvar.set(1.0)
        self._cvar.set(1.0)
        self._apply_adj()

    def _fit_image(self):
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

    # ─── Coordinate helpers ───────────────────────────────────────

    def _img_to_canvas(self, xp, yp):
        if not self._pil_adj:
            return 0, 0
        iw, ih = self._pil_adj.size
        return (self._pan_x + xp / 100 * iw * self._zoom,
                self._pan_y + yp / 100 * ih * self._zoom)

    def _canvas_to_img(self, cx, cy):
        if not self._pil_adj:
            return 50, 50
        iw, ih = self._pil_adj.size
        return ((cx - self._pan_x) / (iw * self._zoom) * 100,
                (cy - self._pan_y) / (ih * self._zoom) * 100)

    # ─── Zoom / Pan ───────────────────────────────────────────────

    def _on_scroll(self, event):
        if not self._pil_adj:
            return
        factor = 1.15 if (event.num == 4 or event.delta > 0) else 1/1.15
        nz = max(0.1, min(10.0, self._zoom * factor))
        self._pan_x = event.x - (event.x - self._pan_x) * (nz / self._zoom)
        self._pan_y = event.y - (event.y - self._pan_y) * (nz / self._zoom)
        self._zoom = nz
        self._redraw()

    def _start_pan(self, event):
        self._pan_start  = (event.x, event.y, self._pan_x, self._pan_y)
        self._is_panning = True

    def _do_pan(self, event):
        if self._pan_start and self._is_panning:
            sx, sy, ox, oy = self._pan_start
            self._pan_x = ox + event.x - sx
            self._pan_y = oy + event.y - sy
            self._redraw()

    def _end_pan(self, event):
        self._is_panning = False

    def _set_pan(self, active):
        self._space_held = active
        self.canvas.config(cursor="fleur" if active else "crosshair")

    # ─── Canvas events ────────────────────────────────────────────

    def _on_click(self, event):
        if self._space_held:
            self._start_pan(event)
            return
        if self._draw_mode:
            xp, yp = self._canvas_to_img(event.x, event.y)
            if self._draw_p1 is None:
                self._draw_p1 = (xp, yp)
                self.status_var.set(f"Point 1 set. Click the OTHER END of the ribbon.")
            else:
                self._finish_draw(xp, yp)

    def _on_drag(self, event):
        if self._space_held:
            self._do_pan(event)
            return
        if self._draw_mode and self._draw_p1:
            if self._draw_temp:
                self.canvas.delete(self._draw_temp)
            x1c, y1c = self._img_to_canvas(*self._draw_p1)
            self._draw_temp = self.canvas.create_line(
                x1c, y1c, event.x, event.y,
                fill="#ffffff", width=3, dash=(4, 3), capstyle="round")

    def _on_release(self, event):
        if self._space_held:
            self._end_pan(event)

    # ─── Draw mode ────────────────────────────────────────────────

    def _start_draw(self):
        self._draw_mode = True
        self._draw_p1   = None
        self.canvas.config(cursor="plus")
        self.status_var.set("DRAW MODE: Click on one END of the ribbon axis, then click the OTHER END.")

    def _cancel_draw(self):
        self._draw_mode = False
        self._draw_p1   = None
        if self._draw_temp:
            self.canvas.delete(self._draw_temp)
            self._draw_temp = None
        self.canvas.config(cursor="crosshair")
        self.status_var.set("Draw cancelled.")

    def _finish_draw(self, x2p, y2p):
        x1p, y1p = self._draw_p1
        if self._pil_adj:
            iw, _ = self._pil_adj.size
            px_len = math.sqrt(((x2p-x1p)/100*iw)**2 + ((y2p-y1p)/100*iw)**2)
            length_nm = round(px_len * self.scale_nm / self.scale_px, 1)
        else:
            length_nm = 0.0

        cx = (x1p + x2p) / 2
        cy = (y1p + y2p) / 2
        bw = max(abs(x2p - x1p) + 1, 0.5)
        bh = max(abs(y2p - y1p) + 1, 0.5)

        if self._draw_temp:
            self.canvas.delete(self._draw_temp)
            self._draw_temp = None
        self._draw_mode = False
        self._draw_p1   = None
        self.canvas.config(cursor="crosshair")

        new_id = max((r.id for r in self.ribbons), default=0) + 1
        r = RibbonAnnotation(
            id=new_id,
            image_path=self.ir.image_path, image_filename=self.ir.image_filename,
            folder_name=self.ir.folder_name, age=self.ir.age, genotype=self.ir.genotype,
            bbox_x=cx, bbox_y=cy, bbox_w=bw, bbox_h=bh,
            length_nm=length_nm, width_nm=0.0,
            length_relative=bh, width_relative=bw,
            morphology="normal", confidence="high",
            vesicle_halo=True, anchored_to_az=True,
            notes="manually drawn", reviewed=True, accepted=True, user_edited=True,
            scale_px=self.scale_px, scale_nm=self.scale_nm, scale_unit=self.scale_unit,
        )
        r.line_coords = [x1p, y1p, x2p, y2p]
        self.ribbons.append(r)
        self._select_ribbon(len(self.ribbons) - 1)
        self._populate_list()
        self._redraw()
        self.status_var.set(f"Ribbon R{new_id} drawn — {length_nm:.0f} nm.")

    # ─── Draw ribbons on canvas ───────────────────────────────────

    def _redraw(self):
        self.canvas.delete("all")
        if not self._pil_adj:
            return
        iw, ih = self._pil_adj.size
        dw = max(1, int(iw * self._zoom))
        dh = max(1, int(ih * self._zoom))
        disp = self._pil_adj.resize((dw, dh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        self.canvas.create_image(self._pan_x, self._pan_y, anchor="nw", image=self._photo)
        for i, r in enumerate(self.ribbons):
            self._draw_one(i, r)

    def _draw_one(self, i, r):
        sel = (i == self.selected_idx)
        col = MORPHOLOGY_COLORS.get(r.morphology, "#888888")
        if r.rejected:
            col = "#444444"
        elif sel:
            col = "#ffffff"
        lw   = 3.0 if sel else 2.0
        dash = (5, 4) if r.rejected else None
        tag  = f"r{i}"

        lc = getattr(r, "line_coords", None)
        if lc and len(lc) == 4:
            x1c, y1c = self._img_to_canvas(lc[0], lc[1])
            x2c, y2c = self._img_to_canvas(lc[2], lc[3])
            self.canvas.create_line(x1c, y1c, x2c, y2c,
                                     fill=col, width=lw*2, dash=dash,
                                     tags=tag, capstyle="round")
            dx, dy = x2c-x1c, y2c-y1c
            ln = max(1, math.sqrt(dx*dx+dy*dy))
            nx, ny = -dy/ln*7, dx/ln*7
            for px, py in [(x1c, y1c), (x2c, y2c)]:
                self.canvas.create_line(px-nx, py-ny, px+nx, py+ny,
                                         fill=col, width=1.5)
        else:
            x1c, y1c = self._img_to_canvas(r.bbox_x - r.bbox_w/2, r.bbox_y - r.bbox_h/2)
            x2c, y2c = self._img_to_canvas(r.bbox_x + r.bbox_w/2, r.bbox_y + r.bbox_h/2)
            self.canvas.create_oval(x1c, y1c, x2c, y2c,
                                     outline=col, width=lw, dash=dash, tags=tag)

        lx, ly = self._img_to_canvas(r.bbox_x, r.bbox_y - r.bbox_h/2)
        s = "✓" if r.accepted else ("✗" if r.rejected else "")
        lbl = f"R{r.id}{s}"
        if r.length_nm > 0:
            lbl += f" {r.length_nm:.0f}nm"
        self.canvas.create_text(lx, ly-8, text=lbl, fill=col,
                                 font=("Helvetica", 9, "bold"), tags=f"{tag}_lbl")
        self.canvas.tag_bind(tag,       "<Button-1>", lambda e, idx=i: self._select_ribbon(idx))
        self.canvas.tag_bind(f"{tag}_lbl", "<Button-1>", lambda e, idx=i: self._select_ribbon(idx))

    # ─── List ─────────────────────────────────────────────────────

    def _populate_list(self):
        self.listbox.delete(0, "end")
        for r in self.ribbons:
            s = "✓" if r.accepted else ("✗" if r.rejected else "·")
            self.listbox.insert("end",
                f" {s} R{r.id}  {r.morphology:<12} {r.length_nm:.0f}nm")
        if self.selected_idx is not None and self.selected_idx < len(self.ribbons):
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(self.selected_idx)
            self.listbox.see(self.selected_idx)

    def _on_list_select(self, event):
        sel = self.listbox.curselection()
        if sel:
            self._select_ribbon(sel[0])

    def _select_ribbon(self, idx):
        if not (0 <= idx < len(self.ribbons)):
            return
        self.selected_idx = idx
        r = self.ribbons[idx]
        self.morph_var.set(r.morphology)
        self.conf_var.set(r.confidence)
        self.length_var.set(f"{r.length_nm:.1f}")
        self.width_var.set(f"{r.width_nm:.1f}")
        self.halo_var.set(r.vesicle_halo)
        self.az_var.set(r.anchored_to_az)
        self.inside_var.set(getattr(r, "inside_spherule", True))
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", r.notes)
        self.ai_label.config(text=(r.notes[:120] if not r.user_edited else "(user-edited)"))
        self.status_var.set(f"R{r.id} · {r.morphology} · {r.confidence} · {r.length_nm:.0f}nm")
        self._populate_list()
        self._redraw()

    # ─── Editor ───────────────────────────────────────────────────

    def _update_from_editor(self):
        if self.selected_idx is None or not self.ribbons:
            return
        r = self.ribbons[self.selected_idx]
        r.morphology       = self.morph_var.get()
        r.confidence       = self.conf_var.get()
        r.vesicle_halo     = self.halo_var.get()
        r.anchored_to_az   = self.az_var.get()
        r.inside_spherule  = self.inside_var.get()
        r.notes            = self.notes_text.get("1.0", "end").strip()
        r.user_edited      = True
        try: r.length_nm   = float(self.length_var.get())
        except ValueError: pass
        try: r.width_nm    = float(self.width_var.get())
        except ValueError: pass
        self._populate_list()
        self._redraw()

    def _accept_ribbon(self):
        if self.selected_idx is not None and self.ribbons:
            r = self.ribbons[self.selected_idx]
            r.accepted = True; r.rejected = False; r.reviewed = True
            self._populate_list(); self._redraw()
            nxt = self.selected_idx + 1
            if nxt < len(self.ribbons):
                self._select_ribbon(nxt)
            else:
                self.status_var.set("All ribbons reviewed. Save & Next →")

    def _reject_ribbon(self):
        if self.selected_idx is not None and self.ribbons:
            r = self.ribbons[self.selected_idx]
            r.rejected = True; r.accepted = False; r.reviewed = True
            r.rejection_reason = (self.notes_text.get("1.0","end").strip()
                                  or "false positive - membrane/non-ribbon")
            self._populate_list(); self._redraw()
            nxt = self.selected_idx + 1
            if nxt < len(self.ribbons):
                self._select_ribbon(nxt)

    def _delete_selected(self):
        if self.selected_idx is not None and self.ribbons:
            self.ribbons.pop(self.selected_idx)
            self.selected_idx = (min(self.selected_idx, len(self.ribbons)-1)
                                 if self.ribbons else None)
            self._populate_list(); self._redraw()

    # ─── Navigation ───────────────────────────────────────────────

    def _save_and_next(self):
        self.ir.ribbons = self.ribbons
        self.ir.analyzed = True
        reviewed = [r for r in self.ribbons if r.reviewed]
        if reviewed:
            try:
                from .engine import save_training_example, log_improvement
                accepted = [{"morphology": r.morphology, "notes": r.notes,
                              "vesicle_halo": r.vesicle_halo,
                              "anchored_to_az": r.anchored_to_az}
                             for r in self.ribbons if r.accepted and not r.rejected]
                rejected = [{"rejection_reason": getattr(r, "rejection_reason",
                              r.notes or "false positive")}
                             for r in self.ribbons if r.rejected]
                save_training_example(self.ir.image_path, accepted, rejected)
                if rejected:
                    log_improvement(
                        f"Image: {self.ir.image_filename}\n"
                        f"Rejected {len(rejected)} false positives. Reasons: "
                        + "; ".join(r["rejection_reason"] for r in rejected[:3])
                    )
            except Exception:
                pass
        self.on_save(self.ir, action="next")
        self.destroy()

    def _prev_image(self):
        self.ir.ribbons = self.ribbons
        self.on_save(self.ir, action="prev")
        self.destroy()

    def _skip(self):
        self.on_save(self.ir, action="skip")
        self.destroy()
