"""
COI Classifier
==============

A desktop tool for rapidly scoring close-up photos and collecting pixel-level
liana / not-liana training samples.

Workflow (like a "Label box", but for a continuous COI value):
  1. Open a folder of photos (File > Open Folder).
  2. A random un-scored photo is shown. Zoom in to inspect detail.
  3. Drag the slider at the bottom (0-100 %) to set the COI.
  4. Optionally label individual pixels as liana / not-liana.
  5. Click Submit (or press Enter) -> the next random photo appears.

Saving & exporting:
  * Save / Save As       -> store ALL progress (scores + pixel labels) in a
                            .coiproj project file so you can close and resume.
  * Export COI CSV       -> filename, coi, timestamp
  * Export Pixel CSV     -> filename, x, y, r, g, b, label

Zoom / pan:
  * Mouse wheel  -> zoom in / out (centred on the cursor)
  * Click + drag -> pan around when zoomed in
  * Double-click -> reset to fit

Pixel labelling:
  * Tick "Label pixels", choose Liana / Not-liana (or press 1 / 2)
  * Left-click a pixel to drop a labelled point (samples its RGB)
  * Right-click a point to remove it

Requirements: Python 3.8+, Pillow  (pip install pillow)
"""

import csv
import json
import os
import random
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
CSV_HEADER = ["filename", "coi", "timestamp"]
PIXEL_CSV_HEADER = ["filename", "x", "y", "r", "g", "b", "label"]
PROJECT_EXT = ".coiproj"

MAX_ZOOM = 12.0     # how far past "fit" the user can zoom in
ZOOM_STEP = 1.25    # multiplier per wheel notch / button press
CLICK_SLOP = 3      # px of movement below which a drag counts as a click
MARKER_R = 5        # radius of a pixel-label marker, in screen px

CLASS_LABELS = {"liana": "Liana", "no_liana": "Not-liana"}
CLASS_COLORS = {"liana": "#ff4d4d", "no_liana": "#4dd2ff"}


class COIClassifier(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("COI Classifier")
        self.geometry("1040x860")
        self.minsize(720, 600)
        self.configure(bg="#1e1e1e")

        # ---- data state -------------------------------------------------
        self.folder = None
        self.project_path = None             # current .coiproj file (if saved)
        self.all_images = []                 # every image file in the folder
        self.order = []                      # navigation order (shuffled once)
        self.idx = -1                        # position within self.order
        self.current = None                  # current image filename
        self._nav_guard = False              # suppress nav-slider feedback loop
        self.results = {}                    # filename -> {"coi", "timestamp"}
        self.annotations = {}                # filename -> [ {x,y,r,g,b,label} ]
        self.dirty = False                   # unsaved changes?

        # ---- image / view state ----------------------------------------
        self._raw_image = None
        self._photo = None                   # keep a ref so it isn't GC'd
        self.zoom = 1.0
        self.pan_x = self.pan_y = 0.0
        self._scale = 1.0                    # last render scale (canvas->img)
        self._tlx = self._tly = 0.0          # last render image top-left (px)
        self._drag = None                    # (x, y, pan_x, pan_y, moved)

        self._build_menu()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Return>", lambda e: self._submit())
        self.bind("<Control-s>", lambda e: self.save_quick())
        self.bind("<Control-S>", lambda e: self.save_as())
        self.bind("<Configure>", self._on_resize)
        self.bind("<Left>", lambda e: self._nudge(-1))
        self.bind("<Right>", lambda e: self._nudge(1))
        self.bind("<Shift-Left>", lambda e: self._nudge(-5))
        self.bind("<Shift-Right>", lambda e: self._nudge(5))
        self.bind("<Key-1>", lambda e: self.pixel_class.set("liana"))
        self.bind("<Key-2>", lambda e: self.pixel_class.set("no_liana"))
        self.bind("<Prior>", lambda e: self._prev())   # PageUp  -> previous image
        self.bind("<Next>", lambda e: self._next())    # PageDown -> next image

        # A folder OR a project file may be passed on the command line.
        arg = sys.argv[1] if len(sys.argv) > 1 else None
        if arg and os.path.isfile(arg):
            self.after(100, lambda: self.open_project(arg))
        elif arg and os.path.isdir(arg):
            self.after(100, lambda: self.load_folder(arg))
        else:
            self.after(100, self.choose_folder)

    # ============================================================= menu ===
    def _build_menu(self):
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open Folder…", command=self.choose_folder)
        filem.add_command(label="Open Project…", command=lambda: self.open_project())
        filem.add_separator()
        filem.add_command(label="Save Project", command=self.save_quick,
                          accelerator="Ctrl+S")
        filem.add_command(label="Save Project As…", command=self.save_as,
                          accelerator="Ctrl+Shift+S")
        filem.add_separator()
        filem.add_command(label="Export COI CSV…", command=self.export_csv)
        filem.add_command(label="Export Pixel Labels CSV…",
                          command=self.export_pixel_csv)
        filem.add_separator()
        filem.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=filem)
        self.config(menu=menubar)

    # =============================================================== UI ===
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=8, font=("Segoe UI", 11))
        style.configure("Zoom.TButton", padding=(8, 4), font=("Segoe UI", 12, "bold"))
        style.configure("Big.Horizontal.TScale", troughcolor="#3a3a3a")

        # ---- Top bar: folder + save + zoom ------------------------------
        top = tk.Frame(self, bg="#2a2a2a")
        top.pack(side="top", fill="x")

        self.folder_label = tk.Label(
            top, text="No folder selected", bg="#2a2a2a", fg="#cccccc",
            font=("Segoe UI", 9), anchor="w",
        )
        self.folder_label.pack(side="left", padx=12, pady=6, fill="x", expand=True)

        ttk.Button(top, text="📂 Open Project…",
                   command=lambda: self.open_project()).pack(
            side="left", padx=(0, 10), pady=6)
        ttk.Button(top, text="💾 Save", command=self.save_quick).pack(
            side="left", padx=(0, 4), pady=6)
        ttk.Button(top, text="Save As…", command=self.save_as).pack(
            side="left", padx=(0, 10), pady=6)

        zoom_box = tk.Frame(top, bg="#2a2a2a")
        zoom_box.pack(side="left", padx=8)
        ttk.Button(zoom_box, text="–", width=3, style="Zoom.TButton",
                   command=lambda: self._zoom_by(1 / ZOOM_STEP)).pack(side="left", padx=2)
        self.zoom_label = tk.Label(zoom_box, text="100%", bg="#2a2a2a", fg="#cccccc",
                                   font=("Segoe UI", 9), width=6)
        self.zoom_label.pack(side="left")
        ttk.Button(zoom_box, text="+", width=3, style="Zoom.TButton",
                   command=lambda: self._zoom_by(ZOOM_STEP)).pack(side="left", padx=2)
        ttk.Button(zoom_box, text="Reset", style="Zoom.TButton",
                   command=self._reset_view).pack(side="left", padx=(6, 2))

        ttk.Button(top, text="Change folder…", command=self.choose_folder).pack(
            side="right", padx=8, pady=6)
        self.progress_label = tk.Label(
            top, text="", bg="#2a2a2a", fg="#9ad29a", font=("Segoe UI", 10, "bold"))
        self.progress_label.pack(side="right", padx=12)

        # ---- Navigation bar: move across images -------------------------
        nav = tk.Frame(self, bg="#262626")
        nav.pack(side="top", fill="x")
        ttk.Button(nav, text="◀ Prev", command=self._prev).pack(
            side="left", padx=(12, 4), pady=6)
        self.nav_var = tk.DoubleVar(value=1)
        self.nav_slider = ttk.Scale(nav, from_=1, to=1, orient="horizontal",
                                    variable=self.nav_var,
                                    command=self._on_nav_slide)
        self.nav_slider.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(nav, text="Next ▶", command=self._next).pack(
            side="left", padx=4, pady=6)
        self.nav_label = tk.Label(nav, text="—", bg="#262626", fg="#cccccc",
                                  font=("Segoe UI", 9), width=22, anchor="w")
        self.nav_label.pack(side="left", padx=(8, 12))

        # ---- Pixel-labelling toolbar ------------------------------------
        annot = tk.Frame(self, bg="#232323")
        annot.pack(side="top", fill="x")

        tk.Label(annot, text="Pixel labels:", bg="#232323", fg="#dddddd",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(12, 8), pady=6)

        self.annotate_mode = tk.BooleanVar(value=False)
        self.annotate_mode.trace_add("write", lambda *_: self._update_cursor())
        ttk.Checkbutton(annot, text="Label pixels (click to mark)",
                        variable=self.annotate_mode).pack(side="left", padx=4)

        self.pixel_class = tk.StringVar(value="liana")
        tk.Radiobutton(annot, text="🔴 Liana (1)", variable=self.pixel_class,
                       value="liana", bg="#232323", fg="#ff8a8a",
                       selectcolor="#232323", activebackground="#232323",
                       font=("Segoe UI", 9)).pack(side="left", padx=(12, 2))
        tk.Radiobutton(annot, text="🔵 Not-liana (2)", variable=self.pixel_class,
                       value="no_liana", bg="#232323", fg="#8ad6ff",
                       selectcolor="#232323", activebackground="#232323",
                       font=("Segoe UI", 9)).pack(side="left", padx=2)

        ttk.Button(annot, text="Undo point", command=self._undo_point).pack(
            side="left", padx=(14, 2), pady=4)
        ttk.Button(annot, text="Clear this photo", command=self._clear_points).pack(
            side="left", padx=2, pady=4)

        self.count_label = tk.Label(annot, text="", bg="#232323", fg="#999999",
                                    font=("Segoe UI", 9))
        self.count_label.pack(side="right", padx=12)

        # ---- Image canvas (packed LAST so the bars keep their space) ----
        self.canvas = tk.Canvas(self, bg="#1e1e1e", highlightthickness=0,
                                width=400, height=300, cursor="fleur")
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._on_wheel(e, force=1))
        self.canvas.bind("<Button-5>", lambda e: self._on_wheel(e, force=-1))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: self._reset_view())
        self.canvas.bind("<ButtonPress-3>", self._on_right_click)

        self.name_label = tk.Label(self, text="", bg="#1e1e1e", fg="#888888",
                                   font=("Consolas", 9))

        # ---- Bottom bar: COI slider + submit ----------------------------
        bottom = tk.Frame(self, bg="#2a2a2a")
        bottom.pack(side="bottom", fill="x")

        self.value_var = tk.DoubleVar(value=50.0)
        self.value_readout = tk.Label(
            bottom, text="COI: 50 %", bg="#2a2a2a", fg="#ffffff",
            font=("Segoe UI", 16, "bold"), width=12)
        self.value_readout.grid(row=0, column=0, rowspan=2, padx=16, pady=12)

        tk.Label(bottom, text="0", bg="#2a2a2a", fg="#888888",
                 font=("Segoe UI", 9)).grid(row=0, column=1, sticky="s")
        self.slider = ttk.Scale(bottom, from_=0, to=100, orient="horizontal",
                                variable=self.value_var, command=self._on_slide,
                                style="Big.Horizontal.TScale")
        self.slider.grid(row=0, column=2, sticky="ew", padx=8, pady=(14, 0))
        tk.Label(bottom, text="100", bg="#2a2a2a", fg="#888888",
                 font=("Segoe UI", 9)).grid(row=0, column=3, sticky="s")

        self.submit_btn = ttk.Button(bottom, text="Submit  (Enter)  ▶",
                                      command=self._submit)
        self.submit_btn.grid(row=0, column=4, rowspan=2, padx=16, pady=12)

        hint = tk.Label(
            bottom,
            text="Slider sets COI, then Submit.  PageUp/PageDown or the top slider move across photos.  Wheel=zoom · drag=pan.  ←/→ nudge COI.",
            bg="#2a2a2a", fg="#777777", font=("Segoe UI", 8))
        hint.grid(row=1, column=1, columnspan=3, sticky="w", padx=8, pady=(0, 8))
        bottom.grid_columnconfigure(2, weight=1)

        # Pack caption + canvas last so the fixed bars are reserved first and
        # the canvas (expand) is what shrinks when the window is small.
        self.name_label.pack(side="bottom", pady=(2, 4))
        self.canvas.pack(side="top", fill="both", expand=True, padx=12, pady=(10, 4))

    # ============================================================ folder ===
    def choose_folder(self):
        if not self._confirm_discard():
            return
        folder = filedialog.askdirectory(title="Select the folder of close-up photos")
        if not folder:
            if self.folder is None and self.project_path is None:
                self.destroy()
            return
        self.load_folder(folder)

    def load_folder(self, folder, results=None, annotations=None,
                     project_path=None):
        images = [f for f in sorted(os.listdir(folder))
                  if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
        if not images:
            messagebox.showwarning(
                "No images",
                f"No image files found in:\n{folder}\n\n"
                f"Supported types: {', '.join(sorted(IMAGE_EXTS))}")
            return

        self.folder = folder
        self.all_images = images
        self.results = results or {}
        self.annotations = annotations or {}
        self.project_path = project_path
        self.dirty = False

        self.order = list(images)
        random.shuffle(self.order)
        self.nav_slider.config(to=max(1, len(self.order)))
        # Start at the first not-yet-scored photo (handy when resuming).
        start = next((i for i, f in enumerate(self.order)
                      if f not in self.results), 0)

        self.folder_label.config(text=f"📁 {folder}")
        self._update_title()
        self._go_to(start)

    # ===================================================== project files ===
    def _project_state(self):
        return {
            "version": 1,
            "folder": self.folder,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "results": self.results,
            "annotations": self.annotations,
        }

    def save_quick(self):
        """Save to the current project file, or fall back to Save As."""
        if self.folder is None:
            return False
        if not self.project_path:
            return self.save_as()
        return self._write_project(self.project_path)

    def save_as(self):
        if self.folder is None:
            messagebox.showinfo("Nothing to save", "Open a photo folder first.")
            return False
        default = os.path.basename(self.folder.rstrip("/\\")) or "session"
        path = filedialog.asksaveasfilename(
            title="Save project as",
            defaultextension=PROJECT_EXT,
            initialfile=f"{default}{PROJECT_EXT}",
            initialdir=self.folder,
            filetypes=[("COI project", f"*{PROJECT_EXT}"), ("JSON", "*.json")])
        if not path:
            return False
        return self._write_project(path)

    def _write_project(self, path):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._project_state(), fh, indent=2)
        except Exception as exc:
            messagebox.showerror("Could not save", f"Failed to write project:\n{exc}")
            return False
        self.project_path = path
        self.dirty = False
        self._update_title()
        return True

    def open_project(self, path=None):
        if not self._confirm_discard():
            return
        if path is None:
            path = filedialog.askopenfilename(
                title="Open project",
                filetypes=[("COI project", f"*{PROJECT_EXT}"),
                           ("JSON", "*.json"), ("All files", "*.*")])
            if not path:
                return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            messagebox.showerror("Could not open", f"Failed to read project:\n{exc}")
            return

        folder = data.get("folder")
        if not folder or not os.path.isdir(folder):
            folder = filedialog.askdirectory(
                title="Photo folder for this project could not be found — locate it")
            if not folder:
                return
        self.load_folder(folder,
                         results=data.get("results", {}),
                         annotations=data.get("annotations", {}),
                         project_path=path)

    # ============================================================ export ===
    def export_csv(self):
        if not self.results:
            messagebox.showinfo("Nothing to export", "No photos have been scored yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export COI scores to CSV", defaultextension=".csv",
            initialfile="coi_labels.csv",
            initialdir=self.folder or os.getcwd(),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(CSV_HEADER)
                for fname in sorted(self.results):
                    r = self.results[fname]
                    w.writerow([fname, r["coi"], r.get("timestamp", "")])
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        messagebox.showinfo("Exported",
                            f"{len(self.results)} COI score(s) written to:\n{path}")

    def export_pixel_csv(self):
        total = sum(len(v) for v in self.annotations.values())
        if total == 0:
            messagebox.showinfo("Nothing to export", "No pixel labels collected yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export pixel labels to CSV", defaultextension=".csv",
            initialfile="pixel_labels.csv",
            initialdir=self.folder or os.getcwd(),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(PIXEL_CSV_HEADER)
                for fname in sorted(self.annotations):
                    for p in self.annotations[fname]:
                        w.writerow([fname, p["x"], p["y"],
                                    p["r"], p["g"], p["b"], p["label"]])
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        messagebox.showinfo("Exported",
                            f"{total} pixel label(s) written to:\n{path}")

    # ======================================================== navigation ===
    def _go_to(self, idx):
        """Show the image at position `idx` in the navigation order."""
        if not self.order:
            return
        self.idx = max(0, min(len(self.order) - 1, idx))
        self.current = self.order[self.idx]

        path = os.path.join(self.folder, self.current)
        try:
            self._raw_image = Image.open(path)
            self._raw_image.load()
            if self._raw_image.mode not in ("RGB", "RGBA", "L"):
                self._raw_image = self._raw_image.convert("RGB")
        except Exception as exc:
            self._raw_image = None
            self._show_message("⚠ could not open image")
            messagebox.showerror("Cannot open image", f"{self.current}\n\n{exc}")
            self._update_nav()
            return

        self.slider.state(["!disabled"])
        self.submit_btn.state(["!disabled"])
        # Restore a previous score if this photo was already scored.
        prev = self.results.get(self.current)
        self.value_var.set(prev["coi"] if prev else 50.0)
        self._on_slide(self.value_var.get())
        self._update_nav()
        self._update_counts()
        self._reset_view()

    def _next(self):
        if self.order and self.idx < len(self.order) - 1:
            self._go_to(self.idx + 1)

    def _prev(self):
        if self.order and self.idx > 0:
            self._go_to(self.idx - 1)

    def _on_nav_slide(self, _value):
        if self._nav_guard or not self.order:
            return
        target = int(round(self.nav_var.get())) - 1
        if target != self.idx:
            self._go_to(target)

    def _update_nav(self):
        total = len(self.order)
        self.progress_label.config(text=f"{len(self.results)} / {total} scored")
        # Move the slider thumb without retriggering its callback.
        self._nav_guard = True
        self.nav_var.set(self.idx + 1)
        self._nav_guard = False
        scored = "✓ scored" if self.current in self.results else "○ unscored"
        self.nav_label.config(text=f"{self.idx + 1} / {total}   {scored}")
        self.name_label.config(text=self.current or "")

    # ====================================================== view / zoom ===
    def _fit_scale(self):
        if self._raw_image is None:
            return 1.0
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        iw, ih = self._raw_image.size
        return min(cw / iw, ch / ih)

    def _reset_view(self):
        self.zoom = 1.0
        self.pan_x = self.pan_y = 0.0
        self._render_image()

    def _zoom_by(self, factor, focus=None):
        if self._raw_image is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        fx, fy = focus or (cw / 2, ch / 2)
        new_zoom = max(1.0, min(MAX_ZOOM, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        ratio = new_zoom / self.zoom
        self.pan_x = fx - cw / 2 - (fx - cw / 2 - self.pan_x) * ratio
        self.pan_y = fy - ch / 2 - (fy - ch / 2 - self.pan_y) * ratio
        self.zoom = new_zoom
        self._render_image()

    def _on_wheel(self, event, force=0):
        if self._raw_image is None:
            return
        direction = force or (1 if event.delta > 0 else -1)
        self._zoom_by(ZOOM_STEP if direction > 0 else 1 / ZOOM_STEP,
                      focus=(event.x, event.y))

    def _clamp_pan(self, disp_w, disp_h, cw, ch):
        max_x = max(0.0, (disp_w - cw) / 2)
        max_y = max(0.0, (disp_h - ch) / 2)
        self.pan_x = max(-max_x, min(max_x, self.pan_x))
        self.pan_y = max(-max_y, min(max_y, self.pan_y))

    def _render_image(self):
        if self._raw_image is None:
            return
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        iw, ih = self._raw_image.size

        scale = self._fit_scale() * self.zoom
        disp_w, disp_h = iw * scale, ih * scale
        self._clamp_pan(disp_w, disp_h, cw, ch)

        tlx = cw / 2 + self.pan_x - disp_w / 2
        tly = ch / 2 + self.pan_y - disp_h / 2
        self._scale, self._tlx, self._tly = scale, tlx, tly

        # Only resample the visible part of the source -> fast at high zoom.
        sx0 = max(0, int((0 - tlx) / scale))
        sy0 = max(0, int((0 - tly) / scale))
        sx1 = min(iw, int((cw - tlx) / scale) + 1)
        sy1 = min(ih, int((ch - tly) / scale) + 1)
        if sx1 <= sx0 or sy1 <= sy0:
            return

        crop = self._raw_image.crop((sx0, sy0, sx1, sy1))
        out_w = max(1, int((sx1 - sx0) * scale))
        out_h = max(1, int((sy1 - sy0) * scale))
        resample = (Image.LANCZOS if scale < 1
                    else Image.NEAREST if self.zoom > 4 else Image.BILINEAR)
        crop = crop.resize((out_w, out_h), resample)

        self._photo = ImageTk.PhotoImage(crop)
        self.canvas.delete("all")
        self.canvas.create_image(tlx + sx0 * scale, tly + sy0 * scale,
                                 anchor="nw", image=self._photo)
        self.zoom_label.config(text=f"{int(self.zoom * 100)}%")
        self._draw_annotations()

    def _show_message(self, text):
        self._photo = None
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        self.canvas.create_text(cw / 2, ch / 2, text=text, fill="#9ad29a",
                                font=("Segoe UI", 22, "bold"))

    def _on_resize(self, event):
        if event.widget is self:
            if getattr(self, "_resize_job", None):
                self.after_cancel(self._resize_job)
            self._resize_job = self.after(80, self._render_image)

    # ================================================ mouse: pan & label ===
    def _on_press(self, event):
        self._drag = [event.x, event.y, self.pan_x, self.pan_y, False]

    def _on_motion(self, event):
        if self._drag is None:
            return
        ox, oy, px, py, moved = self._drag
        if abs(event.x - ox) > CLICK_SLOP or abs(event.y - oy) > CLICK_SLOP:
            self._drag[4] = True
            self.pan_x = px + (event.x - ox)
            self.pan_y = py + (event.y - oy)
            self._render_image()

    def _on_release(self, event):
        drag, self._drag = self._drag, None
        if drag is None or drag[4]:        # a real drag (pan) -> not a click
            return
        if self.annotate_mode.get():
            self._add_point(event.x, event.y)

    def _canvas_to_image(self, cx, cy):
        if self._raw_image is None or self._scale <= 0:
            return None
        u = int((cx - self._tlx) / self._scale)
        v = int((cy - self._tly) / self._scale)
        iw, ih = self._raw_image.size
        if 0 <= u < iw and 0 <= v < ih:
            return u, v
        return None

    def _rgb_at(self, u, v):
        px = self._raw_image.getpixel((u, v))
        if isinstance(px, int):              # mode "L"
            return px, px, px
        return int(px[0]), int(px[1]), int(px[2])

    def _add_point(self, cx, cy):
        uv = self._canvas_to_image(cx, cy)
        if uv is None or self.current is None:
            return
        u, v = uv
        r, g, b = self._rgb_at(u, v)
        self.annotations.setdefault(self.current, []).append(
            {"x": u, "y": v, "r": r, "g": g, "b": b, "label": self.pixel_class.get()})
        self._mark_dirty()
        self._update_counts()
        self._draw_annotations()

    def _on_right_click(self, event):
        """Remove the nearest label point within a small screen radius."""
        if not self.current:
            return
        pts = self.annotations.get(self.current, [])
        if not pts:
            return
        best_i, best_d = None, (MARKER_R + 6) ** 2
        for i, p in enumerate(pts):
            px = self._tlx + (p["x"] + 0.5) * self._scale
            py = self._tly + (p["y"] + 0.5) * self._scale
            d = (px - event.x) ** 2 + (py - event.y) ** 2
            if d < best_d:
                best_i, best_d = i, d
        if best_i is not None:
            pts.pop(best_i)
            self._mark_dirty()
            self._update_counts()
            self._render_image()

    def _draw_annotations(self):
        if self.current is None:
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        for p in self.annotations.get(self.current, []):
            px = self._tlx + (p["x"] + 0.5) * self._scale
            py = self._tly + (p["y"] + 0.5) * self._scale
            if -MARKER_R <= px <= cw + MARKER_R and -MARKER_R <= py <= ch + MARKER_R:
                color = CLASS_COLORS.get(p["label"], "#ffffff")
                self.canvas.create_oval(px - MARKER_R, py - MARKER_R,
                                        px + MARKER_R, py + MARKER_R,
                                        outline="#ffffff", width=1, fill=color,
                                        tags="anno")

    def _undo_point(self):
        pts = self.annotations.get(self.current or "", [])
        if pts:
            pts.pop()
            self._mark_dirty()
            self._update_counts()
            self._render_image()

    def _clear_points(self):
        if self.current and self.annotations.get(self.current):
            if messagebox.askyesno("Clear points",
                                   f"Remove all pixel labels on {self.current}?"):
                self.annotations[self.current] = []
                self._mark_dirty()
                self._update_counts()
                self._render_image()

    def _update_counts(self):
        pts = self.annotations.get(self.current or "", [])
        liana = sum(1 for p in pts if p["label"] == "liana")
        noli = sum(1 for p in pts if p["label"] == "no_liana")
        grand = sum(len(v) for v in self.annotations.values())
        self.count_label.config(
            text=f"this photo — 🔴 {liana}  🔵 {noli}    |    total points: {grand}")

    def _update_cursor(self):
        self.canvas.config(cursor="crosshair" if self.annotate_mode.get() else "fleur")

    # ============================================================ slider ===
    def _on_slide(self, _value):
        self.value_readout.config(text=f"COI: {round(self.value_var.get())} %")

    def _nudge(self, delta):
        v = min(100, max(0, round(self.value_var.get()) + delta))
        self.value_var.set(v)
        self._on_slide(v)

    # ============================================================ submit ===
    def _submit(self):
        if self.current is None:
            return
        self.results[self.current] = {
            "coi": round(self.value_var.get()),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        self._mark_dirty()
        # Quietly persist to the project file if we already have one.
        if self.project_path:
            self._write_project(self.project_path)
        # Advance to the next photo, or stay on the last one.
        if self.idx < len(self.order) - 1:
            self._go_to(self.idx + 1)
        else:
            self._update_nav()
            if len(self.results) == len(self.order):
                messagebox.showinfo("Done", f"All {len(self.order)} photos scored.")

    # ====================================================== housekeeping ===
    def _mark_dirty(self):
        if not self.dirty:
            self.dirty = True
            self._update_title()

    def _update_title(self):
        name = os.path.basename(self.project_path) if self.project_path else "(unsaved)"
        star = "•" if self.dirty else ""
        self.title(f"COI Classifier — {name} {star}".strip())

    def _confirm_discard(self):
        """Return True if it's OK to drop current progress (saved or declined)."""
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel(
            "Unsaved changes",
            "You have unsaved progress. Save it first?")
        if ans is None:        # Cancel
            return False
        if ans:                # Yes -> save
            return self.save_quick()
        return True            # No -> discard

    def _on_close(self):
        if self._confirm_discard():
            self.destroy()


if __name__ == "__main__":
    COIClassifier().mainloop()
