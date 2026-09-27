# Confidence map to DexArm trajectories

Version 0.4.1 provides five accepted vector mode values:

- `plotter_fidelity` preserves the cleaned AI sketch with the selected physical
  pen width. This is the default for Clean AI Sketch and Artistic Remote.
- `event_quality` creates face-aware hybrid trajectories for event portraits.
- `event_speed` is a compatible v0.4.0 alias routed to `event_quality`.
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

## Event Quality

Event Quality consumes the finished grayscale confidence map; AI generation is
not changed or repeated. It builds annotated Fidelity candidates: base
centerlines, structural contours, protected details, and bounded sparse fill
passes. Metadata includes source component, path type, confidence, physical
length, connectivity, topology, visual significance, and face weight.

OpenCV's frontal-face detector is used when it finds a plausible face. Otherwise
the upper-central part of the main ink bounding box is used deterministically.
Eyes, nose, mouth, hair/silhouette, and other short high-confidence connected
details receive extra weight. Low-confidence clothing and broad flat surfaces
receive a penalty.

Candidates are selected by marginal source pixels reproduced at the physical pen
width divided by estimated added time. The time cost includes drawing length,
travel to the candidate, and a pen lift. Redundant passes with negligible new
coverage are skipped. Each selected item remains one real connected path: the
optimizer never inserts a connecting line or several unrelated `M` commands.

Quick, Balanced, and Detailed target 300–450, 450–650, and 650–850 paths. These
are goals rather than blind slices: a sparse input is not padded, while selection
may stop after reaching both global and face quality targets. Balanced targets
global recall 0.72 and face-weighted recall 0.82, with precision 0.85 and IoU
0.65 used by the benchmark gate.

Open paths are reversible. Final routing is nearest-neighbour followed by bounded,
deterministic 2-opt; simplification and cubic fitting remain error-bounded in mm.

Time is `draw_length / drawing_speed + travel_length / travel_speed + pen_lifts ×
pen_lift_delay`. JSON/UI also report SVG command count. Event jobs retain the six
standard artifacts and add `drawing-speed.svg`, `trajectory-speed.json`,
`vector-speed-preview.png`, and `speed-difference-overlay.png`.

`event_speed`, `fast_portrait`, and `event_speed_level` remain accepted for saved
v0.4.0 jobs. Express maps to Quick, Event to Balanced, and Fast Detailed to
Detailed. New integrations should use `event_quality` and `event_quality_level`.

## Quality measurement

The exact M/L/C trajectories are rasterized with `pen_width_mm` and compared
with the cleaned source mask. The job and trajectory JSON report:

- `ink_recall`, `ink_precision`, `ink_iou`, and `face_weighted_recall`;
- a combined `quality_score` for quick UI comparison;
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

The schema 1.2/1.4 trajectory JSON stores the exact ordered commands, real path
count, vectorization mode, pen width, fill strategy, metrics, and warnings.
Legacy centreline JSON and v0.3.0 request fields remain accepted.
