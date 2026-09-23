# Centreline vectorization

The vectorizer does not contour both sides of a thick mark. It creates one centre trajectory:

1. Normalize output to black ink on white.
2. Binarize and remove connected components below the configured physical line size.
3. Apply `skimage.morphology.skeletonize` to obtain one-pixel-wide marks.
4. Build an undirected 8-neighbour graph over skeleton pixels.
5. Start at endpoints/junctions and trace maximal degree-two chains while marking every undirected edge. Trace remaining unvisited edges as loops.
6. Discard branches shorter than `min_line_length_mm`.
7. Convert pixels to millimetres with one uniform scale and centred placement inside the paper margins.
8. Simplify each polyline with Ramer–Douglas–Peucker using a millimetre tolerance.
9. Greedily choose the nearest next endpoint; reverse a path when its far end is closer.
10. Write the same ordered points to open, unfilled SVG paths and `trajectory.json`.

The tests cover straight lines, Y junctions, loops, exact edge coverage, short components, simplification, page bounds, aspect ratio, route reduction, SVG XML validity, and JSON consistency.

The tracer suppresses diagonal corner shortcuts whenever an orthogonal connection exists. This removes the small triangular branches that raw eight-neighbour graphs create around right angles while preserving true diagonal strokes. Noise removal and minimum physical length handle remaining isolated fragments.

Developed by maggogerka.
