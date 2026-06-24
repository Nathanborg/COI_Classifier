# COI Classifier

A tiny desktop tool for rapidly scoring close-up photos with a single
continuous **COI** value (0–100 %). Same idea as a "Label box", but instead of
drawing a box you drag a slider.

## How it works

1. **Launch** — double-click `run.bat`, or run `python coi_classifier.py`.
2. **Pick a folder** of close-up photos when prompted.
3. A **random un-scored photo** appears.
4. **Zoom in** to inspect detail (see below), then **drag the slider** at the
   bottom (0–100 %) to set the COI.
5. Click **Submit** (or press **Enter**) — the score is saved and the next
   random photo loads.

### Zoom & pan
- **Mouse wheel** — zoom in / out, centred on the cursor
- **Click + drag** — pan around when zoomed in
- **+ / − / Reset** — zoom buttons in the top bar (Reset = fit to window)
- **Double-click** — reset to fit
- The view resets to "fit" automatically for each new photo.

### Shortcuts
- **Enter** — submit current photo
- **← / →** — nudge the slider by 1
- **Shift + ← / →** — nudge by 5

## Output

A CSV called `coi_labels.csv` is written **inside the photo folder** you chose:

| filename        | coi | timestamp           |
|-----------------|-----|---------------------|
| IMG_0123.jpg    | 42  | 2026-06-24T14:05:31 |

Each Submit appends one row. Open it in Excel/R for analysis.

## Resume support

The app reads the existing `coi_labels.csv` on launch and **skips photos that
are already scored**, so you can stop and come back later, or have several
people work through the same folder in turns.

## Requirements

- Python 3.8+
- Pillow — install with `pip install pillow` (already present in your env)

Supported image types: jpg, jpeg, png, bmp, gif, tif, tiff, webp.
