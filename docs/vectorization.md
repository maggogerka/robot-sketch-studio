# Confidence map to DexArm trajectories

Version 0.5.0 provides six accepted vector mode values and a dedicated
`generated_line_art` raster engine:

- `plotter_fidelity` preserves the cleaned AI sketch with the selected physical
  pen width. This is the default for Clean AI Sketch and Artistic Remote.
- `event_quality` creates face-aware hybrid trajectories for event portraits.
- `event_single_line` creates one physical centerline per ordinary contour.
- `event_speed` is a compatible v0.4.0 alias routed to `event_quality`.
- `centerline` exports an improved one-stroke centreline representation.
- `minimal` ranks paths and applies the legacy `target_paths` limit.

## Generated Line-Art Import

This engine consumes already generated black line art and never runs AI, XDoG,
or Canny. RGBA input is composited onto white, normalized from measured
background/line levels, and retained as a continuous confidence map. Hysteresis
removes only isolated low-confidence specks; thin source lines remain eligible.

Auto analysis estimates physical source stroke width from the distance transform
on its skeleton. The selected profile controls noise removal, minimum path,
small-gap closing, simplification, cubic fitting, and duplicate radius in final
millimetres. Thick components are skeletonized and traced edge-disjointly, so a
stroke becomes one centerline rather than an outline pair. Joins require close,
direction-compatible endpoints and are bounded by the configured physical gap.

`preserve_quality` is deliberately gentle. `dexarm_optimized` permits small
reductions but the pipeline compares face and centerline coverage and falls back
to Preserve Quality when important topology measurably improves. The generated
SVG is black (`#000000`); legacy modes retain their existing colour/output.

The browser exposes `threshold`, `minimum_path_length_mm`, pen/paper size and
`line_art_noise_removal_mm`, `line_art_gap_closing_mm`,
`line_art_smoothing_mm`, `line_art_simplify_tolerance_mm`, and
`line_art_duplicate_tolerance_mm`. `centerline-overlay.png` is an additional
artifact; all existing artifact names remain compatible.

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

## Event Single-Line

Single-Line consumes the same finished confidence map as Event Quality, but its
candidate set accepts only `path_type == centerline`. A protected structural
contour or fill pass is still rejected. The cleaned mask is skeletonized, short
medial-axis cap spurs are removed using local physical stroke radius, and every
undirected graph edge is consumed at most once. Odd vertices are paired only as
virtual traversal edges; splitting the Euler circuit at those virtual edges
produces the minimum number of real edge-disjoint trails. Real choices at a
junction prefer minimum turning angle.

Endpoint joins require distance, direction, and confidence support at every
sample in the gap. Geometry is simplified and fitted with bounded cubic Bézier
commands, then `collapse_parallel_paths()` compares same-component paths at
0.4–0.6 physical pen widths. More than 70% parallel overlap removes the less
important path; partial overlap retains only unique runs. Detected face paths
use stricter distance and overlap thresholds.

Open paths may reverse. Nearest-neighbour plus bounded 2-opt optimizes actual
pen lifts/travel; it never joins disconnected features or writes several `M`
commands into one path. Scoring uses skeleton topology, centerline distance,
face/silhouette recall, path count, pen lifts, and estimated time—not black fill
area. `redundant_path_count`, `parallel_overlap_ratio`, and
`unique_centerline_coverage` describe the final result.

The `event_single_line` preset selects `rotrics_centerline`,
`fill_strategy: none`, a 0.8 mm pen, and the physical `rotrics_80x113` paper. SVG schema 1.5
records the export profile and centerline metrics. Single-Line jobs also include
`rotrics-line-test.svg`.

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

The schema 1.2/1.4/1.5 trajectory JSON stores the exact ordered commands, real path
count, vectorization mode, pen width, fill strategy, metrics, and warnings.
Legacy centreline JSON and v0.3.0 request fields remain accepted.
