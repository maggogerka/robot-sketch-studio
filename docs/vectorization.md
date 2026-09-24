# Confidence map to DexArm trajectories

Version 0.3.1 provides three vector modes:

- `plotter_fidelity` preserves the cleaned AI sketch with the selected physical
  pen width. This is the default for Clean AI Sketch and Artistic Remote.
- `centerline` exports an improved one-stroke centreline representation.
- `minimal` ranks paths and applies the legacy `target_paths` limit.

## Plotter Fidelity

The input remains a grayscale ink-confidence map. Nearly binary AI output skips
Gaussian softening; other input receives only a small confidence-aware blur.
Hysteresis thresholding keeps weak pixels connected to strong evidence.
Component cleanup uses physical size and retains short, high-confidence details.

The vectorizer maps the image to the drawable page in millimetres and normalizes
processing resolution to roughly four samples across the chosen pen. It then:

1. traces every skeleton edge and continues through junctions by minimum turn;
2. joins aligned endpoints only when the confidence map supports every point in
   the gap;
3. calculates a distance transform per connected-component ROI;
4. creates concentric distance contours or parallel passes for wide ink;
5. simplifies paths conservatively and fits error-bounded cubic Bézier segments;
6. falls back to an `L` command when a safe cubic fit is unavailable;
7. orders trajectories to reduce travel without changing their geometry.

`target_paths` is ignored in Fidelity. `maximum_plotter_paths` is only a
resource guard; reaching it adds an explicit warning. Fidelity performs at most
three refinement attempts with shorter detail filtering, tighter curve fitting,
and denser fill spacing.

## Quality measurement

The exact M/L/C trajectories are rasterized with `pen_width_mm` and compared
with the cleaned source mask. The job and trajectory JSON report:

- `ink_recall`, `ink_precision`, and `ink_iou`;
- source and rendered ink area;
- signed `coverage_difference`;
- symmetric `mean_line_distance_mm`.

Targets are recall 0.95, precision 0.85, and IoU 0.80. Missing a target never
blocks export: the best bounded attempt is returned with a warning.

`vector-preview.png` is the physically thick rasterization. In
`difference-overlay.png`, green is reproduced ink, red is lost source ink,
and blue is extra rendered ink.

## DexArm SVG

Fidelity SVG contains the root `svg` and direct `path` children only. Drawing
commands are M, L, and C; paths use no fill, transform, CSS, masks, filters, or
Z command. Every path carries round caps/joins and a stroke width equal to the
selected pen width. Page dimensions, viewBox, and coordinates are millimetres,
finite, and clamped to the drawable area.

The schema 1.2 trajectory JSON stores the exact ordered commands, real path
count, vectorization mode, pen width, fill strategy, metrics, and warnings.
Legacy centreline JSON and v0.3.0 request fields remain accepted.
