# COI Classifier

A desktop tool for rapidly scoring close-up photos with a single continuous
**COI** value (0–100 %), plus collecting pixel-level **liana / not-liana**
training samples. Same idea as a "Label box", but instead of drawing a box you
drag a slider — and you can also click individual pixels to label them.

## How it works

1. **Launch** — double-click `run.bat`, or run `python coi_classifier.py`.
2. **Open a folder** of close-up photos (File ▸ Open Folder, or the prompt on
   launch).
3. A **random un-scored photo** appears.
4. **Zoom in** to inspect detail, optionally **label pixels** (see below), then
   **drag the slider** (0–100 %) to set the COI.
5. Click **Submit** (or press **Enter**) — the score is recorded and the next
   random photo loads.

### Moving across images
- **Top slider** — drag to scrub to any photo in the set.
- **◀ Prev / Next ▶** buttons, or **PageUp / PageDown**.
- The bar shows `position / total` and whether the current photo is
  `✓ scored` or `○ unscored`. Revisiting a scored photo restores its COI value
  and pixel labels. (Submit is still what records a score — just navigating
  past a photo doesn't score it.)

### Zoom & pan
- **Mouse wheel** — zoom in / out, centred on the cursor
- **Click + drag** — pan around when zoomed in
- **+ / − / Reset** — zoom buttons in the top bar (Reset = fit to window)
- **Double-click** — reset to fit

### Pixel labelling (liana / not-liana)
- Tick **“Label pixels”** in the toolbar.
- Choose **🔴 Liana** or **🔵 Not-liana** (or press **1** / **2**).
- **Left-click** a pixel to drop a labelled point — its `(x, y)` and RGB colour
  are sampled from the original image.
- **Right-click** a point to remove it; **Undo point** / **Clear this photo**
  buttons are in the toolbar.
- Markers stay pinned to the photo as you zoom and pan.

### Shortcuts
- **Enter** — submit current photo
- **← / →** — nudge the slider by 1 · **Shift + ← / →** — by 5
- **1 / 2** — select Liana / Not-liana
- **Ctrl+S** — Save project · **Ctrl+Shift+S** — Save As

## Saving progress (projects)

Use the **Save** / **Save As** buttons (or the File menu) to store **all
progress — COI scores *and* pixel labels — in a `.coiproj` project file**. You
can close the app and reopen the project later (File ▸ Open Project) to carry on
exactly where you left off. Once a project is saved, each **Submit** auto-saves
to it. The app also warns about unsaved changes before closing.

## Exporting data

From the **File** menu:

- **Export COI CSV** — one row per scored photo:

  | filename     | coi | timestamp           |
  |--------------|-----|---------------------|
  | IMG_0123.jpg | 42  | 2026-06-24T14:05:31 |

- **Export Pixel Labels CSV** — one row per labelled pixel:

  | filename     | x   | y   | r   | g   | b   | label    |
  |--------------|-----|-----|-----|-----|-----|----------|
  | IMG_0123.jpg | 512 | 340 | 38  | 71  | 22  | liana    |

The **photo filename is the first column** in both exports.

## Requirements

- Python 3.8+
- Pillow — `pip install pillow`

Supported image types: jpg, jpeg, png, bmp, gif, tif, tiff, webp.

## Command line

```
python coi_classifier.py                 # prompts for a folder
python coi_classifier.py path/to/photos  # open a folder directly
python coi_classifier.py session.coiproj # reopen a saved project
```
