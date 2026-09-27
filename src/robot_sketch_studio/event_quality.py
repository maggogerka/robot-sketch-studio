from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from robot_sketch_studio.bezier_fit import CubicCommand, PathCommand, sample_commands
from robot_sketch_studio.event_speed import _safe_commands, optimize_event_order
from robot_sketch_studio.fidelity import (
    FidelityPathCandidate,
    Geometry,
    _confidence,
    _metrics,
    _plotting_resolution,
    _prepare_ink,
    _preview_images,
    _render,
    build_fidelity_candidate_set,
)
from robot_sketch_studio.models import DrawingStats, EventQualityLevel, ProcessingOptions
from robot_sketch_studio.vectorization import Polyline, VectorResult, polyline_length, rdp


@dataclass(frozen=True, slots=True)
class QualityLimits:
    minimum: int
    maximum: int
    target_recall: float
    target_face_recall: float
    fidelity_time_ratio: float
    simplify_factor: float
    two_opt_window: int


QUALITY_LIMITS = {
    EventQualityLevel.QUICK: QualityLimits(300, 450, 0.66, 0.76, 0.48, 1.35, 16),
    EventQualityLevel.BALANCED: QualityLimits(450, 650, 0.72, 0.82, 0.62, 1.0, 22),
    EventQualityLevel.DETAILED: QualityLimits(650, 850, 0.82, 0.89, 0.76, 0.85, 28),
}


@dataclass(frozen=True, slots=True)
class CoverageCandidate:
    candidate: FidelityPathCandidate
    coverage_indices: np.ndarray


@lru_cache(maxsize=1)
def _face_detector() -> cv2.CascadeClassifier | None:
    cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not cascade.is_file():
        return None
    detector = cv2.CascadeClassifier(str(cascade))
    return None if detector.empty() else detector


def detect_face_mask(confidence: np.ndarray, source: np.ndarray) -> tuple[np.ndarray, str]:
    """Return a deterministic face ROI, with a documented geometry fallback."""
    height, width = source.shape
    mask = np.zeros_like(source, dtype=bool)
    detector = _face_detector()
    faces: tuple[tuple[int, int, int, int], ...] | np.ndarray = ()
    if detector is not None and min(height, width) >= 48:
        preview = np.rint((1.0 - np.clip(confidence, 0.0, 1.0)) * 255.0).astype(np.uint8)
        faces = detector.detectMultiScale(
            preview,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(max(24, width // 12), max(24, height // 12)),
        )
    if len(faces):
        x, y, box_width, box_height = max(
            (tuple(int(value) for value in face) for face in faces),
            key=lambda face: (face[2] * face[3], -face[1], -face[0]),
        )
        padding_x = round(box_width * 0.14)
        padding_y = round(box_height * 0.18)
        x0, x1 = max(0, x - padding_x), min(width, x + box_width + padding_x)
        y0, y1 = max(0, y - padding_y), min(height, y + box_height + padding_y)
        mask[y0:y1, x0:x1] = True
        return mask, "opencv"

    ys, xs = np.where(source)
    if not len(xs):
        return mask, "empty"
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    object_width = max(1, x1 - x0)
    object_height = max(1, y1 - y0)
    face_x0 = max(0, round(x0 + object_width * 0.20))
    face_x1 = min(width, round(x1 - object_width * 0.20))
    face_y0 = max(0, y0)
    face_y1 = min(height, round(y0 + object_height * 0.50))
    mask[face_y0:face_y1, face_x0:face_x1] = True
    return mask, "upper-central-fallback"


def _coverage_indices(
    path: list[tuple[float, float]], source: np.ndarray, pen_width_px: float
) -> np.ndarray:
    points = np.rint([(point[1], point[0]) for point in path]).astype(np.int32)
    if len(points) < 2:
        return np.empty(0, dtype=np.int64)
    thickness = max(1, int(round(pen_width_px)))
    padding = thickness + 2
    x0 = max(0, int(points[:, 0].min()) - padding)
    x1 = min(source.shape[1], int(points[:, 0].max()) + padding + 1)
    y0 = max(0, int(points[:, 1].min()) - padding)
    y1 = min(source.shape[0], int(points[:, 1].max()) + padding + 1)
    local = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    shifted = points - np.asarray([x0, y0], dtype=np.int32)
    cv2.polylines(local, [shifted], False, 1, thickness, cv2.LINE_8)
    radius = thickness // 2
    if radius:
        cv2.circle(local, tuple(shifted[0]), radius, 1, -1)
        cv2.circle(local, tuple(shifted[-1]), radius, 1, -1)
    local_source = source[y0:y1, x0:x1]
    local_y, local_x = np.where(local.astype(bool) & local_source)
    return np.unique((local_y + y0) * source.shape[1] + local_x + x0)


def _candidate_order(item: CoverageCandidate) -> tuple[float, float, float, int, tuple]:
    candidate = item.candidate
    type_priority = {"centerline": 2, "structural_contour": 1, "fill_pass": 0}
    return (
        candidate.visual_significance,
        candidate.face_weight,
        candidate.mean_confidence,
        type_priority.get(candidate.path_type, 0),
        tuple(candidate.path[0]),
    )


def select_quality_candidates(
    candidates: list[FidelityPathCandidate],
    source: np.ndarray,
    face_mask: np.ndarray,
    options: ProcessingOptions,
    geometry: Geometry,
) -> tuple[list[FidelityPathCandidate], dict[str, float | int]]:
    """Select paths by marginal physical coverage per estimated added second."""
    limits = QUALITY_LIMITS[options.effective_event_quality_level]
    target = round(limits.minimum + (limits.maximum - limits.minimum) * options.detail / 100)
    pen_width_px = options.pen_width_mm / max(geometry.scale, 1e-9)
    items = [
        CoverageCandidate(candidate, _coverage_indices(candidate.path, source, pen_width_px))
        for candidate in candidates
    ]
    items = [item for item in items if len(item.coverage_indices)]
    selected: list[CoverageCandidate] = []
    selected_ids: set[int] = set()
    covered = np.zeros(source.size, dtype=bool)
    source_flat = source.ravel()
    face_flat = (face_mask & source).ravel()
    weighted = np.ones(source.size, dtype=np.float32)
    weighted[face_flat] = 4.0
    cursor = (0.0, 0.0)
    approximate_time = 0.0

    def add(item: CoverageCandidate) -> None:
        nonlocal cursor, approximate_time
        identity = id(item.candidate)
        if identity in selected_ids or len(selected) >= target:
            return
        path = item.candidate.path
        start = (path[0][1] * geometry.scale, path[0][0] * geometry.scale)
        stop = (path[-1][1] * geometry.scale, path[-1][0] * geometry.scale)
        approximate_time += item.candidate.length_mm / options.drawing_speed_mm_s
        approximate_time += math.dist(cursor, start) / options.travel_speed_mm_s
        if selected:
            approximate_time += options.pen_lift_delay_s
        cursor = stop
        covered[item.coverage_indices] = True
        selected.append(item)
        selected_ids.add(identity)

    protected = sorted(
        (item for item in items if item.candidate.protected),
        key=_candidate_order,
        reverse=True,
    )
    for item in protected:
        add(item)

    centerlines = sorted(
        (
            item
            for item in items
            if item.candidate.path_type == "centerline" and id(item.candidate) not in selected_ids
        ),
        key=_candidate_order,
        reverse=True,
    )
    centerline_budget = max(len(selected), round(target * 0.74))
    for item in centerlines:
        if len(selected) >= centerline_budget:
            break
        marginal = np.count_nonzero(~covered[item.coverage_indices])
        if marginal or item.candidate.protected:
            add(item)

    remaining = [item for item in items if id(item.candidate) not in selected_ids]
    face_source = max(1, int(face_flat.sum()))
    source_area = max(1, int(source_flat.sum()))
    while remaining and len(selected) < target:
        recall = int(covered[source_flat].sum()) / source_area
        face_recall = int(covered[face_flat].sum()) / face_source
        if (
            len(selected) >= limits.minimum
            and recall >= limits.target_recall
            and face_recall >= limits.target_face_recall
        ):
            break
        best_index = -1
        best_key: tuple[float, float, float, tuple] | None = None
        for index, item in enumerate(remaining):
            indices = item.coverage_indices
            unseen = ~covered[indices]
            marginal_pixels = int(unseen.sum())
            if not marginal_pixels:
                continue
            candidate = item.candidate
            marginal_ratio = marginal_pixels / len(indices)
            if (
                marginal_ratio < 0.045
                and not candidate.protected
                and len(selected) >= limits.minimum
            ):
                continue
            weighted_gain = float(weighted[indices[unseen]].sum())
            face_gain = int(face_flat[indices[unseen]].sum())
            if face_recall < limits.target_face_recall:
                weighted_gain += face_gain * 10.0
            start = (
                candidate.path[0][1] * geometry.scale,
                candidate.path[0][0] * geometry.scale,
            )
            added_time = (
                candidate.length_mm / options.drawing_speed_mm_s
                + math.dist(cursor, start) / options.travel_speed_mm_s
                + (options.pen_lift_delay_s if selected else 0.0)
            )
            surface_penalty = (
                0.72
                if candidate.path_type == "fill_pass"
                and candidate.mean_confidence < max(0.45, candidate.maximum_confidence * 0.65)
                else 1.0
            )
            score = (
                weighted_gain
                * (0.68 + 0.32 * candidate.visual_significance)
                * surface_penalty
                / max(added_time, 0.02)
            )
            key = (
                score,
                candidate.face_weight,
                candidate.visual_significance,
                tuple(candidate.path[0]),
            )
            if best_key is None or key > best_key:
                best_key = key
                best_index = index
        if best_index < 0:
            break
        add(remaining.pop(best_index))

    chosen = [item.candidate for item in selected]
    diagnostics: dict[str, float | int] = {
        "target": target,
        "candidate_count": len(items),
        "selected_count": len(chosen),
        "selection_recall": round(int(covered[source_flat].sum()) / source_area, 5),
        "selection_face_recall": round(int(covered[face_flat].sum()) / face_source, 5),
        "approximate_time_seconds": round(approximate_time, 3),
    }
    return chosen, diagnostics


def _geometry_paths(
    candidates: list[FidelityPathCandidate],
    options: ProcessingOptions,
    geometry: Geometry,
) -> tuple[list[Polyline], list[list[PathCommand]], list[list[tuple]]]:
    limits = QUALITY_LIMITS[options.effective_event_quality_level]
    tolerance = options.effective_curve_tolerance_mm * limits.simplify_factor
    lines: list[Polyline] = []
    for candidate in candidates:
        raw = [
            (geometry.offset_x + x * geometry.scale, geometry.offset_y + y * geometry.scale)
            for y, x in candidate.path
        ]
        simplified = rdp(raw, max(0.02, tolerance * 0.68))
        if len(simplified) >= 2:
            lines.append(simplified)
    lines = optimize_event_order(
        lines,
        (options.margin_mm, options.margin_mm),
        two_opt_window=limits.two_opt_window,
        maximum_passes=3,
    )
    commands, curves = _safe_commands(lines, options, geometry, tolerance)
    return lines, commands, curves


def vectorize_event_quality(sketch: np.ndarray, options: ProcessingOptions) -> VectorResult:
    confidence, geometry = _plotting_resolution(_confidence(sketch), options)
    source, softened, low_threshold = _prepare_ink(
        confidence, options, geometry, component_factor=0.55
    )
    if not source.any():
        raise ValueError("No drawable ink remained after confidence-map cleanup")
    face_mask, face_method = detect_face_mask(softened, source)
    candidates = build_fidelity_candidate_set(
        source, softened, low_threshold, options, geometry, face_mask
    )
    selected, diagnostics = select_quality_candidates(
        candidates, source, face_mask, options, geometry
    )
    if not selected:
        raise ValueError("No significant Event Quality paths remained")
    lines, commands, curves = _geometry_paths(selected, options, geometry)
    rendered = _render(lines, commands, source.shape, geometry, options.pen_width_mm)
    metrics = _metrics(source, rendered, geometry.scale)
    face_source = source & face_mask
    face_recall = (
        float(np.logical_and(rendered, face_source).sum()) / float(face_source.sum())
        if face_source.any()
        else float(metrics["ink_recall"])
    )

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
    quality_score = (
        0.25 * float(metrics["ink_recall"])
        + 0.30 * float(metrics["ink_precision"])
        + 0.25 * float(metrics["ink_iou"])
        + 0.20 * face_recall
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
        face_weighted_recall=round(face_recall, 5),
        quality_score=round(quality_score, 5),
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
    result.warnings.append(
        "Event Quality selected "
        f"{diagnostics['selected_count']} of {diagnostics['candidate_count']} real paths "
        f"(goal {diagnostics['target']}; face ROI: {face_method})."
    )
    limits = QUALITY_LIMITS[options.effective_event_quality_level]
    if stats.ink_recall < limits.target_recall or face_recall < limits.target_face_recall:
        result.warnings.append(
            "The requested quality target was not fully reachable from the bounded sparse "
            f"candidate set (recall={stats.ink_recall:.3f}, face={face_recall:.3f})."
        )
    return result
