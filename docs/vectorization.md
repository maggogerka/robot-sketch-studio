# Confidence-map to cubic SVG

The v0.3 vectorizer consumes ink confidence from 0.0 background to 1.0 ink. It
deliberately postpones binary decisions until after neural inference:

1. Gaussian-soften the confidence map.
2. Apply a low/high hysteresis threshold so weak pixels survive only when
   connected to strong evidence.
3. Remove connected components below minimum_feature_size_mm.
4. Close small gaps using a physical-size-derived kernel.
5. Skeletonize marks to one-pixel centrelines.
6. Build an undirected 8-neighbour graph without diagonal corner shortcuts.
7. At intersections, continue along the unused edge with the smallest turn.
8. Join close endpoints only when their tangents agree within
   maximum_join_angle_deg.
9. Reject longer joins whose gap has no supporting confidence.
10. Remove paths below minimum_path_length_mm.
11. Rank by length and confidence and retain at most target_paths.
12. Convert to centred millimetre coordinates and simplify with
    curve_fit_tolerance_mm.
13. Interpolate the simplified path with cubic Catmull-Rom-style Bézier
    segments.
14. Greedily order and reverse paths to reduce pen-up travel.

The SVG contains only open, unfilled cubic paths with round caps/joins.
trajectory.json schema 1.1 includes both simplified points and the exact Bézier
controls. confidence.png preserves model evidence; sketch.png shows the cleaned
hysteresis mask.

All distances that affect physical output are expressed in millimetres and
converted using the uniform image-to-page scale. The three UI presets are
ordinary parameter bundles and every value can be overridden.
