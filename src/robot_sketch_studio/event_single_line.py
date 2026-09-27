from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
from skimage.morphology import skeletonize

from robot_sketch_studio.bezier_fit import CubicCommand, sample_commands
from robot_sketch_studio.event_quality import detect_face_mask
from robot_sketch_studio.event_speed import _safe_commands, optimize_event_order
from robot_sketch_studio.fidelity import (
    FidelityPathCandidate,
    Geometry,
    _confidence,
    _metrics,
    _number,
    _plotting_resolution,
    _prepare_ink,
    _preview_images,
    _render,
)
from robot_sketch_studio.models import DrawingStats, ProcessingOptions
from robot_sketch_studio.vectorization import (
    Pixel,
    Polyline,
    VectorResult,
    build_graph,
    merge_close_paths,
    polyline_length,
    rdp,
    trace_graph_edge_disjoint,
)


@dataclass(frozen=True, slots=True)
class SingleLineFeature:
    line: Polyline
    component_id: int
    importance: float
    face_weight: float
    mean_confidence: float


@dataclass(frozen=True, slots=True)
class CollapseStats:
    removed_path_count: int
    redundant_path_count: int
    parallel_overlap_ratio: float
    input_parallel_overlap_ratio: float


def _prune_medial_axis_spurs(
    skeleton: np.ndarray,
    source: np.ndarray,
    scale: float,
    face_mask: np.ndarray,
    cautious_face: bool,
) -> np.ndarray:
    """Remove only terminal branches explained by the local stroke radius."""
    cleaned = skeleton.copy()
    radius = cv2.distanceTransform(source.astype(np.uint8), cv2.DIST_L2, 5)
    for _ in range(12):
        graph = build_graph(cleaned)
        removals: set[Pixel] = set()
        for endpoint in sorted(node for node, neighbors in graph.items() if len(neighbors) == 1):
            branch = [endpoint]
            previous: Pixel | None = None
            current = endpoint
            while True:
                following = [node for node in graph[current] if node != previous]
                if len(following) != 1:
                    break
                next_node = following[0]
                branch.append(next_node)
                previous, current = current, next_node
                if len(graph[current]) != 2:
                    break
            if len(graph[current]) < 3 or len(branch) < 2:
                continue
            length_mm = polyline_length(branch) * scale
            radius_mm = max(float(radius[node]) for node in branch) * scale
            in_face = cautious_face and float(np.mean([face_mask[node] for node in branch])) > 0.2
            factor = 0.65 if in_face else 1.65
            if length_mm <= max(scale * 2.1, radius_mm * factor):
                removals.update(branch[:-1])
        if not removals:
            break
        for y, x in removals:
            cleaned[y, x] = False
    return cleaned


def _centerline_candidates(
    paths: list[list[Pixel]],
    source: np.ndarray,
    confidence: np.ndarray,
    face_mask: np.ndarray,
    graph: dict[Pixel, list[Pixel]],
    geometry: Geometry,
    options: ProcessingOptions,
) -> list[FidelityPathCandidate]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(source.astype(np.uint8), 8)
    maximum_area = max(1, int(stats[1:, cv2.CC_STAT_AREA].max(initial=1)))
    height, width = source.shape
    candidates: list[FidelityPathCandidate] = []
    for path in paths:
        if len(path) < 2:
            continue
        pixels = [
            (
                int(np.clip(round(point[0]), 0, height - 1)),
                int(np.clip(round(point[1]), 0, width - 1)),
            )
            for point in path
        ]
        component_values = np.asarray([labels[y, x] for y, x in pixels], dtype=np.int32)
        nonzero = component_values[component_values > 0]
        component_id = int(np.bincount(nonzero).argmax()) if len(nonzero) else 0
        values = np.asarray([confidence[y, x] for y, x in pixels], dtype=np.float32)
        mean_confidence = float(values.mean())
        maximum_confidence = float(values.max(initial=0.0))
        length_mm = polyline_length(path) * geometry.scale
        degrees = [len(graph.get(pixel, ())) for pixel in pixels]
        junctions = sum(degree > 2 for degree in degrees)
        endpoints = sum(degree == 1 for degree in (degrees[0], degrees[-1]))
        connectivity = min(1.0, junctions * 0.24 + endpoints * 0.18)
        closed = math.dist(path[0], path[-1]) <= math.sqrt(2.0)
        component_area = int(stats[component_id, cv2.CC_STAT_AREA]) if component_id else 1
        topology = min(
            1.0,
            (0.5 if closed else 0.0) + 0.5 * math.sqrt(component_area / maximum_area),
        )
        face_weight = float(np.mean([face_mask[y, x] for y, x in pixels]))
        length_term = min(1.0, math.log1p(length_mm) / math.log(81.0))
        importance = (
            0.34 * mean_confidence
            + 0.16 * maximum_confidence
            + 0.18 * length_term
            + 0.14 * connectivity
            + 0.08 * topology
            + 0.10 * face_weight
        )
        protected = bool(
            options.preserve_short_details
            and maximum_confidence >= 0.82
            and mean_confidence >= 0.60
            and (face_weight >= 0.25 or connectivity > 0.0 or closed)
        )
        if (
            length_mm < options.effective_minimum_path_length_mm
            and not protected
            and connectivity == 0.0
            and importance < 0.56
        ):
            continue
        candidates.append(
            FidelityPathCandidate(
                path=path,
                path_type="centerline",
                component_id=component_id,
                mean_confidence=mean_confidence,
                maximum_confidence=maximum_confidence,
                length_mm=length_mm,
                connectivity=connectivity,
                topology=topology,
                visual_significance=importance,
                face_weight=face_weight,
                protected=protected,
            )
        )
    if any(candidate.path_type != "centerline" for candidate in candidates):
        raise RuntimeError("Single-Line candidate set contains a non-centerline path")
    return candidates


def _sample_line(line: Polyline, step: float) -> tuple[np.ndarray, np.ndarray]:
    points: list[tuple[float, float]] = []
    tangents: list[tuple[float, float]] = []
    for start, stop in zip(line, line[1:], strict=False):
        vector = np.asarray(stop, dtype=np.float64) - np.asarray(start, dtype=np.float64)
        length = float(np.linalg.norm(vector))
        if length <= 1e-9:
            continue
        tangent = vector / length
        sample_count = max(1, int(math.ceil(length / step)))
        for position in np.linspace(0.0, 1.0, sample_count, endpoint=False):
            point = np.asarray(start) + position * vector
            points.append((float(point[0]), float(point[1])))
            tangents.append((float(tangent[0]), float(tangent[1])))
    if len(line) >= 2:
        vector = np.asarray(line[-1]) - np.asarray(line[-2])
        length = float(np.linalg.norm(vector))
        tangent = vector / max(length, 1e-9)
        points.append(line[-1])
        tangents.append((float(tangent[0]), float(tangent[1])))
    return np.asarray(points, dtype=np.float64), np.asarray(tangents, dtype=np.float64)


def _parallel_mask(
    points: np.ndarray,
    tangents: np.ndarray,
    reference: Polyline,
    maximum_distance: float,
    maximum_angle_deg: float = 18.0,
) -> np.ndarray:
    if len(points) == 0 or len(reference) < 2:
        return np.zeros(len(points), dtype=bool)
    starts = np.asarray(reference[:-1], dtype=np.float64)
    stops = np.asarray(reference[1:], dtype=np.float64)
    segments = stops - starts
    squared = np.einsum("ij,ij->i", segments, segments)
    valid = squared > 1e-12
    if not valid.any():
        return np.zeros(len(points), dtype=bool)
    starts, segments, squared = starts[valid], segments[valid], squared[valid]
    segment_tangents = segments / np.sqrt(squared)[:, None]
    result = np.zeros(len(points), dtype=bool)
    cosine_limit = math.cos(math.radians(maximum_angle_deg))
    for first in range(0, len(points), 256):
        last = min(len(points), first + 256)
        relative = points[first:last, None, :] - starts[None, :, :]
        projection = np.einsum("ijk,jk->ij", relative, segments) / squared[None, :]
        projection = np.clip(projection, 0.0, 1.0)
        nearest = starts[None, :, :] + projection[:, :, None] * segments[None, :, :]
        distances = np.linalg.norm(points[first:last, None, :] - nearest, axis=2)
        indices = np.argmin(distances, axis=1)
        minimum = distances[np.arange(last - first), indices]
        parallel = np.abs(np.einsum("ij,ij->i", tangents[first:last], segment_tangents[indices]))
        result[first:last] = (minimum <= maximum_distance) & (parallel >= cosine_limit)
    return result


def _boxes_overlap(first: Polyline, second: Polyline, padding: float) -> bool:
    first_points = np.asarray(first)
    second_points = np.asarray(second)
    return bool(
        first_points[:, 0].min() - padding <= second_points[:, 0].max()
        and first_points[:, 0].max() + padding >= second_points[:, 0].min()
        and first_points[:, 1].min() - padding <= second_points[:, 1].max()
        and first_points[:, 1].max() + padding >= second_points[:, 1].min()
    )


def _unique_runs(
    points: np.ndarray, duplicated: np.ndarray, minimum_length: float
) -> list[Polyline]:
    runs: list[Polyline] = []
    start = 0
    while start < len(points):
        while start < len(points) and duplicated[start]:
            start += 1
        stop = start
        while stop < len(points) and not duplicated[stop]:
            stop += 1
        if stop - start >= 2:
            line = [(float(x), float(y)) for x, y in points[start:stop]]
            if polyline_length(line) >= minimum_length:
                runs.append(line)
        start = stop + 1
    return runs


def collapse_parallel_paths(
    features: list[SingleLineFeature],
    pen_width_mm: float,
    minimum_length_mm: float = 0.2,
) -> tuple[list[SingleLineFeature], CollapseStats]:
    """Remove or trim same-component physical parallel duplicates."""
    ordered = sorted(
        features,
        key=lambda item: (
            item.importance,
            polyline_length(item.line),
            item.mean_confidence,
            item.line[0],
        ),
        reverse=True,
    )
    kept: list[SingleLineFeature] = []
    redundant = 0
    input_overlap = 0
    input_samples = 0
    step = max(0.06, pen_width_mm * 0.16)
    for feature in ordered:
        points, tangents = _sample_line(feature.line, step)
        if len(points) < 2:
            continue
        duplicated = np.zeros(len(points), dtype=bool)
        face_sensitive = feature.face_weight >= 0.15
        distance = pen_width_mm * (0.40 if face_sensitive else 0.55)
        full_threshold = 0.88 if face_sensitive else 0.70
        partial_threshold = 0.62 if face_sensitive else 0.35
        for reference in kept:
            if reference.component_id != feature.component_id:
                continue
            if not _boxes_overlap(feature.line, reference.line, distance):
                continue
            duplicated |= _parallel_mask(points, tangents, reference.line, distance)
        overlap = float(duplicated.mean())
        input_overlap += int(duplicated.sum())
        input_samples += len(points)
        if overlap >= full_threshold:
            redundant += 1
            continue
        if overlap >= partial_threshold:
            fragments = _unique_runs(points, duplicated, minimum_length_mm)
            if fragments:
                redundant += 1
                kept.extend(replace(feature, line=fragment) for fragment in fragments)
                continue
        kept.append(feature)
    remaining_redundant = 0
    remaining_overlap = 0
    remaining_samples = 0
    for index, feature in enumerate(kept):
        points, tangents = _sample_line(feature.line, step)
        duplicated = np.zeros(len(points), dtype=bool)
        face_sensitive = feature.face_weight >= 0.15
        distance = pen_width_mm * (0.40 if face_sensitive else 0.55)
        threshold = 0.88 if face_sensitive else 0.70
        for reference in kept[:index]:
            if reference.component_id == feature.component_id:
                duplicated |= _parallel_mask(points, tangents, reference.line, distance)
        remaining_samples += len(points)
        remaining_overlap += int(duplicated.sum())
        remaining_redundant += float(duplicated.mean()) >= threshold
    ratio = remaining_overlap / max(1, remaining_samples)
    input_ratio = input_overlap / max(1, input_samples)
    kept.sort(key=lambda item: (item.component_id, item.line[0], item.line[-1]))
    return kept, CollapseStats(
        redundant,
        remaining_redundant,
        round(ratio, 5),
        round(input_ratio, 5),
    )


def _geometry_features(
    candidates: list[FidelityPathCandidate], options: ProcessingOptions, geometry: Geometry
) -> list[SingleLineFeature]:
    features: list[SingleLineFeature] = []
    tolerance = max(0.015, options.effective_curve_tolerance_mm * 0.65)
    for candidate in candidates:
        if candidate.path_type != "centerline":
            continue
        raw = [
            (geometry.offset_x + x * geometry.scale, geometry.offset_y + y * geometry.scale)
            for y, x in candidate.path
        ]
        simplified = rdp(raw, tolerance)
        if len(simplified) >= 2:
            features.append(
                SingleLineFeature(
                    line=simplified,
                    component_id=candidate.component_id,
                    importance=candidate.visual_significance,
                    face_weight=candidate.face_weight,
                    mean_confidence=candidate.mean_confidence,
                )
            )
    return features


def _centerline_quality(
    source_skeleton: np.ndarray,
    rendered_centerline: np.ndarray,
    face_mask: np.ndarray,
    scale: float,
    pen_width_mm: float,
) -> dict[str, float]:
    distance = cv2.distanceTransform((~rendered_centerline).astype(np.uint8), cv2.DIST_L2, 5)
    radius_px = max(1.0, pen_width_mm * 0.5 / max(scale, 1e-9))
    covered = source_skeleton & (distance <= radius_px)
    face_source = source_skeleton & face_mask
    silhouette_source = source_skeleton & ~face_mask
    unique_coverage = float(covered.sum()) / max(1, int(source_skeleton.sum()))
    face_recall = float((covered & face_source).sum()) / max(1, int(face_source.sum()))
    silhouette_recall = float((covered & silhouette_source).sum()) / max(
        1, int(silhouette_source.sum())
    )
    return {
        "unique_centerline_coverage": round(unique_coverage, 5),
        "face_weighted_recall": round(face_recall, 5),
        "silhouette_recall": round(silhouette_recall, 5),
    }


def vectorize_event_single_line(sketch: np.ndarray, options: ProcessingOptions) -> VectorResult:
    confidence, geometry = _plotting_resolution(_confidence(sketch), options)
    source, softened, low_threshold = _prepare_ink(
        confidence, options, geometry, component_factor=0.55
    )
    if not source.any():
        raise ValueError("No drawable ink remained after confidence-map cleanup")
    face_mask, face_method = detect_face_mask(softened, source)
    source_skeleton = _prune_medial_axis_spurs(
        skeletonize(source),
        source,
        geometry.scale,
        face_mask,
        cautious_face=face_method == "opencv",
    )
    graph = build_graph(source_skeleton)
    paths = trace_graph_edge_disjoint(graph)
    for (y, x), neighbors in sorted(graph.items()):
        if not neighbors:
            direction = 0.2 if x < source.shape[1] - 1 else -0.2
            paths.append([(y, x), (y, x + direction)])
    paths = merge_close_paths(
        paths,
        softened,
        options.join_distance_mm / max(geometry.scale, 1e-9),
        options.maximum_join_angle_deg,
        low_threshold,
        max(1.0, options.minimum_feature_size_mm / max(geometry.scale, 1e-9)),
        support_factor=1.0,
    )
    candidates = _centerline_candidates(
        paths, source, softened, face_mask, graph, geometry, options
    )
    features = _geometry_features(candidates, options, geometry)
    collapsed = features
    removed_paths = 0
    collapse_stats = CollapseStats(0, 0, 0.0, 0.0)
    input_parallel_overlap = 0.0
    for _ in range(3):
        collapsed, pass_stats = collapse_parallel_paths(
            collapsed,
            options.pen_width_mm,
            max(0.08, options.effective_minimum_path_length_mm * 0.35),
        )
        removed_paths += pass_stats.removed_path_count
        input_parallel_overlap = max(
            input_parallel_overlap, pass_stats.input_parallel_overlap_ratio
        )
        collapse_stats = CollapseStats(
            removed_paths,
            pass_stats.redundant_path_count,
            pass_stats.parallel_overlap_ratio,
            input_parallel_overlap,
        )
        if pass_stats.removed_path_count == 0:
            break
    if not collapsed:
        raise ValueError("No significant Single-Line centerlines remained")
    lines = optimize_event_order(
        [feature.line for feature in collapsed],
        (options.margin_mm, options.margin_mm),
        two_opt_window=22,
        maximum_passes=3,
    )
    commands, curves = _safe_commands(
        lines, options, geometry, options.effective_curve_tolerance_mm
    )
    physical_render = _render(lines, commands, source.shape, geometry, options.pen_width_mm)
    center_render = _render(lines, commands, source.shape, geometry, geometry.scale)
    metrics = _metrics(source_skeleton, center_render, geometry.scale)
    topology_metrics = _centerline_quality(
        source_skeleton,
        center_render,
        face_mask,
        geometry.scale,
        options.pen_width_mm,
    )

    drawing_length = 0.0
    travel_length = 0.0
    cursor = (options.margin_mm, options.margin_mm)
    for line, path_commands in zip(lines, commands, strict=True):
        sampled = sample_commands(line[0], path_commands, max(0.04, options.pen_width_mm * 0.15))
        drawing_length += polyline_length(sampled)
        travel_length += math.dist(cursor, line[0])
        cursor = path_commands[-1].end if path_commands else line[-1]
    pen_lifts = max(0, len(lines) - 1)
    estimated = (
        drawing_length / options.drawing_speed_mm_s
        + travel_length / options.travel_speed_mm_s
        + pen_lifts * options.pen_lift_delay_s
    )
    quality_score = (
        0.40 * topology_metrics["unique_centerline_coverage"]
        + 0.30 * topology_metrics["face_weighted_recall"]
        + 0.30 * topology_metrics["silhouette_recall"]
    )
    stats = DrawingStats(
        stroke_count=len(lines),
        drawing_length_mm=round(drawing_length, 3),
        travel_length_mm=round(travel_length, 3),
        estimated_time_seconds=round(estimated, 2),
        average_path_length_mm=round(drawing_length / len(lines), 3),
        curve_segment_count=sum(
            isinstance(command, CubicCommand)
            for path_commands in commands
            for command in path_commands
        ),
        pen_lifts=pen_lifts,
        svg_command_count=sum(1 + len(path) for path in commands),
        redundant_path_count=collapse_stats.redundant_path_count,
        parallel_overlap_ratio=collapse_stats.parallel_overlap_ratio,
        quality_score=round(quality_score, 5),
        **topology_metrics,
        **metrics,
    )
    preview = np.where(source, 0, 255).astype(np.uint8)
    vector_preview = np.where(physical_render, 0, 255).astype(np.uint8)
    _, _, difference = _preview_images(source_skeleton, center_render)
    result = VectorResult(
        lines=lines,
        curves=curves,
        width_mm=geometry.page_width,
        height_mm=geometry.page_height,
        stats=stats,
        preview=preview,
        commands=commands,
        pen_width_mm=options.pen_width_mm,
        vector_preview=vector_preview,
        difference_overlay=difference,
    )
    if collapse_stats.removed_path_count:
        result.warnings.append(
            f"Single-Line removed or trimmed {collapse_stats.removed_path_count} "
            "parallel duplicate paths."
        )
    if not (
        math.isclose(geometry.page_width, 80.0, abs_tol=1e-6)
        and math.isclose(geometry.page_height, 113.0, abs_tol=1e-6)
    ):
        result.warnings.append(
            "Масштабирование изменит физический интервал между траекториями. "
            "Генерируйте SVG сразу в конечном размере."
        )
    return result


def write_rotrics_line_test_svg(options: ProcessingOptions, destination: Path) -> None:
    width, height = options.page_dimensions
    margin = min(options.margin_mm, width * 0.2, height * 0.2)
    y = height * 0.5
    root = ET.Element(
        "{http://www.w3.org/2000/svg}svg",
        {
            "width": f"{_number(width)}mm",
            "height": f"{_number(height)}mm",
            "viewBox": f"0 0 {_number(width)} {_number(height)}",
            "data-purpose": "Rotrics physical pen-width and G-code diagnostic",
            "data-author": "maggogerka",
        },
    )
    ET.SubElement(
        root,
        "{http://www.w3.org/2000/svg}path",
        {
            "id": "physical-width-test",
            "d": f"M {_number(margin)} {_number(y)} L {_number(width - margin)} {_number(y)}",
            "fill": "none",
            "stroke": "#111111",
            "stroke-width": _number(options.pen_width_mm),
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        },
    )
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)
