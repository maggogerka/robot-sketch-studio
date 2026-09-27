from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from skimage.morphology import skeletonize

from robot_sketch_studio.bezier_fit import (
    CubicCommand,
    LineCommand,
    PathCommand,
    fit_path,
    sample_commands,
)
from robot_sketch_studio.fidelity import (
    Geometry,
    _confidence,
    _metrics,
    _plotting_resolution,
    _prepare_ink,
    _preview_images,
    _render,
)
from robot_sketch_studio.models import DrawingStats, EventSpeedLevel, ProcessingOptions
from robot_sketch_studio.vectorization import (
    Pixel,
    Polyline,
    VectorResult,
    build_graph,
    merge_close_paths,
    polyline_length,
    rdp,
    trace_graph_continuous,
)


@dataclass(frozen=True, slots=True)
class SpeedLimits:
    minimum: int
    maximum: int
    simplify_factor: float
    two_opt_window: int


SPEED_LIMITS = {
    EventSpeedLevel.EXPRESS: SpeedLimits(100, 180, 2.0, 14),
    EventSpeedLevel.EVENT: SpeedLimits(180, 300, 1.5, 20),
    EventSpeedLevel.FAST_DETAILED: SpeedLimits(300, 450, 1.15, 24),
}


@dataclass(frozen=True, slots=True)
class PathFeature:
    path: list[Pixel]
    component: int
    length_mm: float
    mean_confidence: float
    maximum_confidence: float
    importance: float
    protected: bool


def _travel_length(lines: list[Polyline], origin: tuple[float, float]) -> float:
    total = 0.0
    cursor = origin
    for line in lines:
        total += math.dist(cursor, line[0])
        cursor = line[-1]
    return total


def optimize_event_order(
    lines: list[Polyline],
    origin: tuple[float, float] = (0.0, 0.0),
    *,
    two_opt_window: int = 20,
    maximum_passes: int = 3,
) -> list[Polyline]:
    """Nearest-neighbour with reversible strokes and deterministic bounded 2-opt."""
    remaining = [line[:] for line in lines if len(line) >= 2]
    ordered: list[Polyline] = []
    cursor = origin
    while remaining:
        distance, index, reverse = min(
            min(
                (math.dist(cursor, line[0]), index, False),
                (math.dist(cursor, line[-1]), index, True),
            )
            for index, line in enumerate(remaining)
        )
        del distance
        selected = remaining.pop(index)
        if reverse:
            selected.reverse()
        ordered.append(selected)
        cursor = selected[-1]

    # Reversing both the order and direction of a subsequence preserves all
    # internal pen-up edges. Only its two boundaries need evaluation.
    for _ in range(maximum_passes):
        changed = False
        for first in range(len(ordered) - 1):
            previous = origin if first == 0 else ordered[first - 1][-1]
            last_stop = min(len(ordered) - 1, first + max(2, two_opt_window))
            for last in range(first + 1, last_stop + 1):
                following = ordered[last + 1][0] if last + 1 < len(ordered) else None
                old_cost = math.dist(previous, ordered[first][0])
                new_cost = math.dist(previous, ordered[last][-1])
                if following is not None:
                    old_cost += math.dist(ordered[last][-1], following)
                    new_cost += math.dist(ordered[first][0], following)
                if new_cost + 1e-9 >= old_cost:
                    continue
                ordered[first : last + 1] = [
                    list(reversed(line)) for line in reversed(ordered[first : last + 1])
                ]
                changed = True
        if not changed:
            break
    return ordered


def _path_features(
    paths: list[list[Pixel]],
    graph: dict[Pixel, list[Pixel]],
    confidence: np.ndarray,
    skeleton: np.ndarray,
    geometry: Geometry,
    options: ProcessingOptions,
) -> list[PathFeature]:
    _, component_labels = cv2.connectedComponents(skeleton.astype(np.uint8), 8)
    component_sizes = np.bincount(component_labels.ravel())
    height, width = confidence.shape
    maximum_component = max(1, int(component_sizes[1:].max(initial=1)))
    features: list[PathFeature] = []
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
        values = np.asarray([confidence[y, x] for y, x in pixels], dtype=np.float32)
        length_mm = polyline_length(path) * geometry.scale
        mean_confidence = float(values.mean())
        maximum_confidence = float(values.max(initial=0.0))
        degrees = [len(graph.get(pixel, ())) for pixel in pixels]
        junctions = sum(degree > 2 for degree in degrees)
        endpoints = sum(degree == 1 for degree in (degrees[0], degrees[-1]))
        closed = math.dist(path[0], path[-1]) <= math.sqrt(2.0)
        component = int(component_labels[pixels[0]])
        component_term = (
            min(1.0, math.sqrt(component_sizes[component] / maximum_component))
            if component
            else 0.0
        )
        center_x = float(np.mean([point[1] for point in path])) / max(width - 1, 1)
        center_y = float(np.mean([point[0] for point in path])) / max(height - 1, 1)
        # Portrait line art normally places eyes, nose and mouth near the upper
        # centre. This is only one score term; high-confidence details elsewhere
        # remain protected as well.
        face_term = math.exp(-(((center_x - 0.5) / 0.34) ** 2 + ((center_y - 0.43) / 0.36) ** 2))
        length_term = min(1.0, math.log1p(length_mm) / math.log(61.0))
        confidence_term = 0.65 * mean_confidence + 0.35 * maximum_confidence
        connectivity_term = min(1.0, junctions * 0.32 + endpoints * 0.16)
        topology_term = min(1.0, (0.55 if closed else 0.0) + 0.45 * component_term)
        importance = (
            0.36 * confidence_term
            + 0.27 * length_term
            + 0.14 * connectivity_term
            + 0.11 * topology_term
            + 0.12 * face_term
        )
        protected = bool(
            options.preserve_short_details
            and length_mm >= 0.12
            and maximum_confidence >= 0.84
            and mean_confidence >= 0.64
        )
        # A short path may still survive when it is well connected or is a
        # closed topological feature; length alone never decides removal.
        if (
            length_mm < options.effective_minimum_path_length_mm
            and not protected
            and importance < 0.57
            and not closed
            and junctions == 0
        ):
            continue
        features.append(
            PathFeature(
                path,
                component,
                length_mm,
                mean_confidence,
                maximum_confidence,
                importance,
                protected,
            )
        )
    return features


def _feature_key(feature: PathFeature) -> tuple[float, float, float, int, Pixel]:
    return (
        feature.importance,
        feature.mean_confidence,
        feature.length_mm,
        -feature.component,
        feature.path[0],
    )


def _select_paths(
    features: list[PathFeature], options: ProcessingOptions
) -> tuple[list[list[Pixel]], int]:
    limits = SPEED_LIMITS[options.event_speed_level]
    if len(features) <= limits.maximum:
        return [feature.path for feature in features], len(features)
    target = round(limits.minimum + (limits.maximum - limits.minimum) * options.detail / 100)
    ranked = sorted(features, key=_feature_key, reverse=True)
    selected: list[PathFeature] = []
    selected_ids: set[int] = set()

    def add(feature: PathFeature) -> None:
        identity = id(feature)
        if identity not in selected_ids and len(selected) < target:
            selected.append(feature)
            selected_ids.add(identity)

    # Protect high-confidence facial marks first, then retain one representative
    # from as many connected components as the budget allows.
    for feature in ranked:
        if feature.protected:
            add(feature)
    representatives: dict[int, PathFeature] = {}
    for feature in ranked:
        representatives.setdefault(feature.component, feature)
    for feature in sorted(representatives.values(), key=_feature_key, reverse=True):
        add(feature)
    for feature in ranked:
        add(feature)
    chosen = sorted(selected, key=lambda feature: (feature.path[0], feature.path[-1]))
    return [feature.path for feature in chosen], target


def _safe_commands(
    lines: list[Polyline], options: ProcessingOptions, geometry: Geometry, tolerance: float
) -> tuple[list[list[PathCommand]], list[list[tuple]]]:
    bounds = (
        options.margin_mm,
        options.margin_mm,
        geometry.page_width - options.margin_mm,
        geometry.page_height - options.margin_mm,
    )
    command_paths: list[list[PathCommand]] = []
    curve_paths: list[list[tuple]] = []
    for line in lines:
        commands: list[PathCommand] = []
        curves: list[tuple] = []
        cursor = line[0]
        for command in fit_path(line, tolerance, corner_angle_deg=58.0):
            end = (
                float(np.clip(command.end[0], bounds[0], bounds[2])),
                float(np.clip(command.end[1], bounds[1], bounds[3])),
            )
            if isinstance(command, CubicCommand):
                control1 = (
                    float(np.clip(command.control1[0], bounds[0], bounds[2])),
                    float(np.clip(command.control1[1], bounds[1], bounds[3])),
                )
                control2 = (
                    float(np.clip(command.control2[0], bounds[0], bounds[2])),
                    float(np.clip(command.control2[1], bounds[1], bounds[3])),
                )
                safe: PathCommand = CubicCommand(control1, control2, end)
                curves.append((cursor, control1, control2, end))
            else:
                safe = LineCommand(end)
            commands.append(safe)
            cursor = end
        command_paths.append(commands)
        curve_paths.append(curves)
    return command_paths, curve_paths


def _geometry_paths(
    paths: list[list[Pixel]], options: ProcessingOptions, geometry: Geometry
) -> tuple[list[Polyline], list[list[PathCommand]], list[list[tuple]]]:
    limits = SPEED_LIMITS[options.event_speed_level]
    tolerance = options.effective_curve_tolerance_mm * limits.simplify_factor
    lines: list[Polyline] = []
    for path in paths:
        raw = [
            (geometry.offset_x + x * geometry.scale, geometry.offset_y + y * geometry.scale)
            for y, x in path
        ]
        simplified = rdp(raw, max(0.025, tolerance * 0.72))
        if len(simplified) >= 2:
            lines.append(simplified)
    lines = optimize_event_order(
        lines,
        (options.margin_mm, options.margin_mm),
        two_opt_window=limits.two_opt_window,
    )
    commands, curves = _safe_commands(lines, options, geometry, tolerance)
    return lines, commands, curves


def vectorize_event_speed_legacy(sketch: np.ndarray, options: ProcessingOptions) -> VectorResult:
    """v0.4.0 centerline-only implementation retained for regression benchmarks."""
    confidence, geometry = _plotting_resolution(_confidence(sketch), options)
    source, softened, low_threshold = _prepare_ink(
        confidence, options, geometry, component_factor=0.55
    )
    if not source.any():
        raise ValueError("No drawable ink remained after confidence-map cleanup")
    skeleton = skeletonize(source)
    graph = build_graph(skeleton)
    paths = trace_graph_continuous(graph)
    for (y, x), neighbors in sorted(graph.items()):
        if not neighbors:
            direction = 0.2 if x < source.shape[1] - 1 else -0.2
            paths.append([(y, x), (y, x + direction)])

    # Never bridge empty space: pixels below 80% of hysteresis-low are replaced
    # with zero before the common direction-aware endpoint joiner sees them.
    guarded_confidence = np.where(softened >= low_threshold * 0.8, softened, 0.0)
    paths = merge_close_paths(
        paths,
        guarded_confidence,
        options.join_distance_mm / max(geometry.scale, 1e-9),
        options.maximum_join_angle_deg,
        low_threshold,
        max(1.0, options.minimum_feature_size_mm / max(geometry.scale, 1e-9)),
    )
    features = _path_features(paths, graph, softened, skeleton, geometry, options)
    selected_paths, target = _select_paths(features, options)
    if not selected_paths:
        raise ValueError("No significant event-speed paths remained")
    lines, commands, curves = _geometry_paths(selected_paths, options, geometry)
    rendered = _render(lines, commands, source.shape, geometry, options.pen_width_mm)
    metrics = _metrics(source, rendered, geometry.scale)

    drawing_length = 0.0
    travel_length = 0.0
    cursor = (options.margin_mm, options.margin_mm)
    for line, path_commands in zip(lines, commands, strict=True):
        sampled = sample_commands(line[0], path_commands, max(0.05, options.pen_width_mm * 0.2))
        drawing_length += polyline_length(sampled)
        travel_length += math.dist(cursor, line[0])
        cursor = path_commands[-1].end if path_commands else line[-1]
    pen_lifts = max(0, len(lines) - 1)
    command_count = sum(1 + len(path_commands) for path_commands in commands)
    estimated = (
        drawing_length / options.drawing_speed_mm_s
        + travel_length / options.travel_speed_mm_s
        + pen_lifts * options.pen_lift_delay_s
    )
    stats = DrawingStats(
        stroke_count=len(lines),
        drawing_length_mm=round(drawing_length, 3),
        travel_length_mm=round(travel_length, 3),
        estimated_time_seconds=round(estimated, 2),
        average_path_length_mm=round(drawing_length / len(lines), 3) if lines else 0.0,
        curve_segment_count=sum(
            isinstance(command, CubicCommand)
            for path_commands in commands
            for command in path_commands
        ),
        pen_lifts=pen_lifts,
        svg_command_count=command_count,
        **metrics,
    )
    preview, vector_preview, difference = _preview_images(source, rendered)
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
    if len(features) > len(lines):
        result.warnings.append(
            f"Event Speed retained {len(lines)} of {len(features)} paths by importance "
            f"(level target {target}); no disconnected paths were joined to meet the target."
        )
    return result


def vectorize_event_speed(sketch: np.ndarray, options: ProcessingOptions) -> VectorResult:
    """Compatibility entry point migrated to the Event Quality implementation."""
    from robot_sketch_studio.event_quality import vectorize_event_quality

    return vectorize_event_quality(sketch, options)
