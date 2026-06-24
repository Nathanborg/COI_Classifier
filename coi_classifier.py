"""
COI Classifier
==============

A tiny desktop tool for rapidly scoring close-up photos.

Workflow (like a "Label box", but for a continuous COI value):
  1. On launch, pick a folder of photos.
  2. A random un-scored photo is shown. Zoom in to inspect detail.
  3. Drag the slider at the bottom (0-100 %), then click Submit (or press Enter).
  4. The score is appended to a CSV and the next random photo appears.

Zoom / pan:
  * Mouse wheel       -> zoom in / out (centred on the cursor)
  * Click + drag      -> pan around when zoomed in
  * + / - / Reset      -> zoom buttons in the top bar
  * Double-click      -> reset to fit

Output CSV (saved inside the chosen photo folder as `coi_labels.csv`):
  filename, coi, timestamp

Requirements: Python 3.8+, Pillow  (pip install pillow)
"""

import csv
import os
import random
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
CSV_NAME = "coi_labels.csv"
CSV_HEADER = ["filename", "coi", "timestamp"]

MAX_ZOOM = 12.0     # how far past "fit" the user can zoom in
ZOOM_STEP = 1.25    # multiplier per wheel notch / button press


class COIClassifier(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("COI Classifier")
        self.geometry("980x820")
        self.minsize(640, 560)
        self.configure(bg="#1e1e1e")

        # State
        self.folder = None
        self.csv_path = None
        self.all_images = []        # every image file in the folder
        self.remaining = []         # not-yet-scored images (shuffled queue)
        self.current = None         # current image filename
        self._photo = None          # keep a reference so it isn't GC'd
        self._raw_image = None      # the loaded PIL image

        # Zoom / pan state
        self.zoom = 1.0             # user zoom on top of the fit-to-window scale
        self.pan_x = 0.0            # image-centre offset from canvas centre (px)
        self.pan_y = 0.0
        self._drag_anchor = None    # (mouse, pan) snapshot while dragging

        self._build_ui()
        self.bind("<Return>", lambda e: self._submit())
        self.bind("<Configure>", self._on_resize)

        # Kick things off. A folder may be passed on the command line
        # (handy for shortcuts / testing); otherwise prompt for one.
        start_folder = sys.argv[1] if len(sys.argv) > 1 else None
        if start_folder and os.path.isdir(start_folder):
            self.after(100, lambda: self.load_folder(start_folder))
        else:
            self.after(100, self.choose_folder)

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=8, font=("Segoe UI", 11))
        style.configure("Zoom.TButton", padding=(8, 4), font=("Segoe UI", 12, "bold"))
        style.configure("Big.Horizontal.TScale", troughcolor="#3a3a3a")

        # Top bar -----------------------------------------------------------
        top = tk.Frame(self, bg="#2a2a2a")
        top.pack(side="top", fill="x")

        self.folder_label = tk.Label(
            top, text="No folder selected", bg="#2a2a2a", fg="#cccccc",
            font=("Segoe UI", 9), anchor="w",
        )
        self.folder_label.pack(side="left", padx=12, pady=6, fill="x", expand=True)

        # Zoom controls
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
            side="right", padx=8, pady=6
        )

        self.progress_label = tk.Label(
            top, text="", bg="#2a2a2a", fg="#9ad29a", font=("Segoe UI", 10, "bold")
        )
        self.progress_label.pack(side="right", padx=12)

        # Image area (Canvas so we can zoom & pan). Packed LAST (see end of
        # this method) so the fixed top/bottom bars always keep their space and
        # the canvas just absorbs whatever is left over. width/height are tiny
        # on purpose so the canvas never forces the window to grow.
        self.canvas = tk.Canvas(self, bg="#1e1e1e", highlightthickness=0,
                                width=400, height=300, cursor="fleur")
        self._img_id = None
        self._text_id = None

        # Zoom: mouse wheel (Windows/macOS use <MouseWheel>; X11 uses Button-4/5)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._on_wheel(e, force=1))
        self.canvas.bind("<Button-5>", lambda e: self._on_wheel(e, force=-1))
        # Pan: drag with the left button
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        # Double-click resets the view
        self.canvas.bind("<Double-Button-1>", lambda e: self._reset_view())

        self.name_label = tk.Label(
            self, text="", bg="#1e1e1e", fg="#888888", font=("Consolas", 9)
        )

        # Bottom control bar ------------------------------------------------
        bottom = tk.Frame(self, bg="#2a2a2a")
        bottom.pack(side="bottom", fill="x")

        # COI value readout
        self.value_var = tk.DoubleVar(value=50.0)
        self.value_readout = tk.Label(
            bottom, text="COI: 50 %", bg="#2a2a2a", fg="#ffffff",
            font=("Segoe UI", 16, "bold"), width=12,
        )
        self.value_readout.grid(row=0, column=0, rowspan=2, padx=16, pady=12)

        tk.Label(bottom, text="0", bg="#2a2a2a", fg="#888888",
                 font=("Segoe UI", 9)).grid(row=0, column=1, sticky="s")

        self.slider = ttk.Scale(
            bottom, from_=0, to=100, orient="horizontal",
            variable=self.value_var, command=self._on_slide,
            style="Big.Horizontal.TScale",
        )
        self.slider.grid(row=0, column=2, sticky="ew", padx=8, pady=(14, 0))

        tk.Label(bottom, text="100", bg="#2a2a2a", fg="#888888",
                 font=("Segoe UI", 9)).grid(row=0, column=3, sticky="s")

        self.submit_btn = ttk.Button(bottom, text="Submit  (Enter)  ▶",
                                      command=self._submit)
        self.submit_btn.grid(row=0, column=4, rowspan=2, padx=16, pady=12)

        hint = tk.Label(
            bottom,
            text="Slider sets COI, then Submit.  Wheel = zoom · drag = pan · double-click = reset.  ←/→ nudge 1, Shift+←/→ nudge 5.",
            bg="#2a2a2a", fg="#777777", font=("Segoe UI", 8),
        )
        hint.grid(row=1, column=1, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        bottom.grid_columnconfigure(2, weight=1)

        # Pack the filename caption and the image canvas LAST, so the fixed
        # top/bottom bars get their space first. The canvas (expand=True) then
        # fills the remaining area and is the thing that shrinks when the
        # window is small — the slider stays put.
        self.name_label.pack(side="bottom", pady=(2, 4))
        self.canvas.pack(side="top", fill="both", expand=True, padx=12, pady=(12, 4))

        # Keyboard nudges
        self.bind("<Left>", lambda e: self._nudge(-1))
        self.bind("<Right>", lambda e: self._nudge(1))
        self.bind("<Shift-Left>", lambda e: self._nudge(-5))
        self.bind("<Shift-Right>", lambda e: self._nudge(5))

    # ------------------------------------------------------------- folder ---
    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select the folder of close-up photos")
        if not folder:
            if self.folder is None:
                # Nothing selected and nothing loaded yet -> exit cleanly.
                self.destroy()
            return
        self.load_folder(folder)

    def load_folder(self, folder):
        images = [
            f for f in sorted(os.listdir(folder))
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS
        ]
        if not images:
            messagebox.showwarning(
                "No images",
                f"No image files found in:\n{folder}\n\n"
                f"Supported types: {', '.join(sorted(IMAGE_EXTS))}",
            )
            return

        self.folder = folder
        self.all_images = images
        self.csv_path = os.path.join(folder, CSV_NAME)
        done = self._load_done_set()

        self.remaining = [f for f in images if f not in done]
        random.shuffle(self.remaining)

        self.folder_label.config(text=f"📁 {folder}")
        self._next_image()

    def _load_done_set(self):
        """Read already-scored filenames so a session can resume safely."""
        done = set()
        if os.path.exists(self.csv_path):
            try:
                with open(self.csv_path, "r", newline="", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        if row.get("filename"):
                            done.add(row["filename"])
            except Exception:
                pass
        return done

    # -------------------------------------------------------------- images ---
    def _next_image(self):
        total = len(self.all_images)
        done = total - len(self.remaining)
        self.progress_label.config(text=f"{done} / {total} scored")

        if not self.remaining:
            self.current = None
            self._raw_image = None
            self._show_message("🎉  All photos scored!")
            self.name_label.config(text=f"Results saved to {self.csv_path}")
            self.slider.state(["disabled"])
            self.submit_btn.state(["disabled"])
            return

        self.slider.state(["!disabled"])
        self.submit_btn.state(["!disabled"])
        self.current = self.remaining[-1]   # peek; popped on submit
        self.name_label.config(text=self.current)

        path = os.path.join(self.folder, self.current)
        try:
            self._raw_image = Image.open(path)
            self._raw_image.load()
            if self._raw_image.mode not in ("RGB", "RGBA", "L"):
                self._raw_image = self._raw_image.convert("RGB")
        except Exception as exc:
            messagebox.showerror("Cannot open image", f"{self.current}\n\n{exc}")
            self.remaining.pop()
            self._next_image()
            return

        # Reset slider to midpoint and view to fit for each new photo.
        self.value_var.set(50.0)
        self._on_slide(50.0)
        self._reset_view()

    # ---------------------------------------------------------- view / zoom ---
    def _fit_scale(self):
        """Scale that makes the raw image fit fully inside the canvas."""
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
        """Multiply the zoom, keeping the point `focus` (canvas px) fixed."""
        if self._raw_image is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if focus is None:
            focus = (cw / 2, ch / 2)
        fx, fy = focus

        old_scale = self._fit_scale() * self.zoom
        new_zoom = max(1.0, min(MAX_ZOOM, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        ratio = new_zoom / self.zoom

        # Keep the source pixel under the focus point stationary.
        self.pan_x = fx - cw / 2 - (fx - cw / 2 - self.pan_x) * ratio
        self.pan_y = fy - ch / 2 - (fy - ch / 2 - self.pan_y) * ratio
        self.zoom = new_zoom
        self._render_image()

    def _on_wheel(self, event, force=0):
        if self._raw_image is None:
            return
        direction = force or (1 if event.delta > 0 else -1)
        factor = ZOOM_STEP if direction > 0 else 1 / ZOOM_STEP
        self._zoom_by(factor, focus=(event.x, event.y))

    def _on_drag_start(self, event):
        self._drag_anchor = (event.x, event.y, self.pan_x, self.pan_y)

    def _on_drag_move(self, event):
        if self._drag_anchor is None:
            return
        ox, oy, px, py = self._drag_anchor
        self.pan_x = px + (event.x - ox)
        self.pan_y = py + (event.y - oy)
        self._render_image()

    def _on_drag_end(self, _event):
        self._drag_anchor = None

    def _clamp_pan(self, disp_w, disp_h, cw, ch):
        """Keep the image from drifting entirely off-screen."""
        # If the image is larger than the canvas, allow panning up to its edges;
        # otherwise keep it centred.
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

        # Top-left of the (virtual) full-size displayed image, in canvas px.
        tlx = cw / 2 + self.pan_x - disp_w / 2
        tly = ch / 2 + self.pan_y - disp_h / 2

        # Only resize the part of the source that's actually visible — keeps
        # things fast even at high zoom on large photos.
        sx0 = max(0, int((0 - tlx) / scale))
        sy0 = max(0, int((0 - tly) / scale))
        sx1 = min(iw, int((cw - tlx) / scale) + 1)
        sy1 = min(ih, int((ch - tly) / scale) + 1)
        if sx1 <= sx0 or sy1 <= sy0:
            return

        crop = self._raw_image.crop((sx0, sy0, sx1, sy1))
        out_w = max(1, int((sx1 - sx0) * scale))
        out_h = max(1, int((sy1 - sy0) * scale))
        resample = Image.LANCZOS if scale < 1 else Image.NEAREST if self.zoom > 4 else Image.BILINEAR
        crop = crop.resize((out_w, out_h), resample)

        self._photo = ImageTk.PhotoImage(crop)
        place_x = tlx + sx0 * scale
        place_y = tly + sy0 * scale

        self.canvas.delete("all")
        self._img_id = self.canvas.create_image(place_x, place_y, anchor="nw",
                                                 image=self._photo)
        self.zoom_label.config(text=f"{int(self.zoom * 100)}%")

    def _show_message(self, text):
        """Clear the canvas and show a centred message (e.g. all-done)."""
        self._photo = None
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        self.canvas.create_text(cw / 2, ch / 2, text=text, fill="#9ad29a",
                                font=("Segoe UI", 22, "bold"))

    def _on_resize(self, event):
        # Only react to the main window resizing, and debounce a touch.
        if event.widget is self:
            if getattr(self, "_resize_job", None):
                self.after_cancel(self._resize_job)
            self._resize_job = self.after(80, self._render_image)

    # -------------------------------------------------------------- slider ---
    def _on_slide(self, _value):
        v = round(self.value_var.get())
        self.value_readout.config(text=f"COI: {v} %")

    def _nudge(self, delta):
        v = min(100, max(0, round(self.value_var.get()) + delta))
        self.value_var.set(v)
        self._on_slide(v)

    # -------------------------------------------------------------- submit ---
    def _submit(self):
        if self.current is None:
            return
        value = round(self.value_var.get())
        self._append_csv(self.current, value)
        self.remaining.pop()    # remove the photo we just scored
        self._next_image()

    def _append_csv(self, filename, value):
        new_file = not os.path.exists(self.csv_path)
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                if new_file:
                    writer.writerow(CSV_HEADER)
                writer.writerow([filename, value,
                                 datetime.now().isoformat(timespec="seconds")])
        except Exception as exc:
            messagebox.showerror("Could not save", f"Failed to write to CSV:\n{exc}")


if __name__ == "__main__":
    COIClassifier().mainloop()
