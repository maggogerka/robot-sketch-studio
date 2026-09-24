from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class LineCommand:
    end: Point


@dataclass(frozen=True, slots=True)
class CubicCommand:
    control1: Point
    control2: Point
    end: Point


PathCommand = LineCommand | CubicCommand


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-12 else np.zeros(2, dtype=float)


def _evaluate(start: np.ndarray, command: CubicCommand, value: float) -> np.ndarray:
    one_minus = 1.0 - value
    control1 = np.asarray(command.control1, dtype=float)
    control2 = np.asarray(command.control2, dtype=float)
    end = np.asarray(command.end, dtype=float)
    return (
        one_minus**3 * start
        + 3.0 * one_minus**2 * value * control1
        + 3.0 * one_minus * value**2 * control2
        + value**3 * end
    )


def _fit_candidate(points: np.ndarray) -> tuple[CubicCommand, np.ndarray]:
    start, end = points[0], points[-1]
    tangent_start = _unit(points[1] - start)
    tangent_end = _unit(points[-2] - end)
    distances = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(distances.sum())
    if total <= 1e-12:
        command = CubicCommand(tuple(start), tuple(end), tuple(end))
        return command, np.zeros(len(points), dtype=float)
    parameters = np.concatenate(([0.0], np.cumsum(distances) / total))
    matrix = np.zeros((2, 2), dtype=float)
    vector = np.zeros(2, dtype=float)
    for point, value in zip(points, parameters, strict=True):
        one_minus = 1.0 - value
        b0 = one_minus**3
        b1 = 3.0 * one_minus**2 * value
        b2 = 3.0 * one_minus * value**2
        b3 = value**3
        a1 = tangent_start * b1
        a2 = tangent_end * b2
        base = start * (b0 + b1) + end * (b2 + b3)
        delta = point - base
        matrix[0, 0] += float(np.dot(a1, a1))
        matrix[0, 1] += float(np.dot(a1, a2))
        matrix[1, 0] += float(np.dot(a1, a2))
        matrix[1, 1] += float(np.dot(a2, a2))
        vector[0] += float(np.dot(a1, delta))
        vector[1] += float(np.dot(a2, delta))
    try:
        alpha_start, alpha_end = np.linalg.solve(matrix, vector)
    except np.linalg.LinAlgError:
        alpha_start = alpha_end = total / 3.0
    maximum_handle = total * 2.0
    if (
        not np.isfinite(alpha_start)
        or not np.isfinite(alpha_end)
        or alpha_start <= 1e-6
        or alpha_end <= 1e-6
        or alpha_start > maximum_handle
        or alpha_end > maximum_handle
    ):
        alpha_start = alpha_end = total / 3.0
    control1 = start + tangent_start * alpha_start
    control2 = end + tangent_end * alpha_end
    command = CubicCommand(tuple(control1), tuple(control2), tuple(end))
    errors = np.asarray(
        [
            float(np.linalg.norm(point - _evaluate(start, command, value)))
            for point, value in zip(points, parameters, strict=True)
        ]
    )
    return command, errors


def _safe_controls(
    start: Point, command: CubicCommand, points: np.ndarray, tolerance: float
) -> bool:
    controls = np.asarray([start, command.control1, command.control2, command.end])
    lower = points.min(axis=0) - tolerance
    upper = points.max(axis=0) + tolerance
    return bool(
        np.isfinite(controls).all() and (controls >= lower).all() and (controls <= upper).all()
    )


def _fit_recursive(points: np.ndarray, tolerance: float, depth: int = 0) -> list[PathCommand]:
    if len(points) <= 2:
        return [LineCommand(tuple(points[-1]))]
    command, errors = _fit_candidate(points)
    worst = int(np.argmax(errors))
    if float(errors[worst]) <= tolerance and _safe_controls(
        tuple(points[0]), command, points, tolerance
    ):
        return [command]
    if depth >= 18 or worst <= 0 or worst >= len(points) - 1:
        return [LineCommand(tuple(point)) for point in points[1:]]
    return _fit_recursive(points[: worst + 1], tolerance, depth + 1) + _fit_recursive(
        points[worst:], tolerance, depth + 1
    )


def _corner_indices(points: np.ndarray, corner_angle_deg: float) -> list[int]:
    corners = [0]
    for index in range(1, len(points) - 1):
        incoming = _unit(points[index] - points[index - 1])
        outgoing = _unit(points[index + 1] - points[index])
        cosine = float(np.clip(np.dot(incoming, outgoing), -1.0, 1.0))
        if math.degrees(math.acos(cosine)) >= corner_angle_deg:
            corners.append(index)
    corners.append(len(points) - 1)
    return sorted(set(corners))


def fit_path(
    points: list[Point],
    tolerance: float,
    corner_angle_deg: float = 38.0,
) -> list[PathCommand]:
    """Fit deterministic cubic segments whose sampled error stays within tolerance.

    Sharp corners are hard split points. Unsafe or underconstrained pieces remain
    straight L commands, so the exported trajectory never invents large loops.
    """
    if len(points) < 2:
        return []
    array = np.asarray(points, dtype=float)
    if not np.isfinite(array).all():
        raise ValueError("Path contains non-finite coordinates")
    commands: list[PathCommand] = []
    corners = _corner_indices(array, corner_angle_deg)
    for first, last in zip(corners, corners[1:], strict=False):
        commands.extend(_fit_recursive(array[first : last + 1], max(tolerance, 1e-6)))
    return commands


def sample_commands(start: Point, commands: list[PathCommand], step_mm: float) -> list[Point]:
    sampled = [start]
    cursor = start
    for command in commands:
        if isinstance(command, LineCommand):
            length = math.dist(cursor, command.end)
            count = max(1, int(math.ceil(length / max(step_mm, 1e-3))))
            sampled.extend(
                (
                    cursor[0] + (command.end[0] - cursor[0]) * index / count,
                    cursor[1] + (command.end[1] - cursor[1]) * index / count,
                )
                for index in range(1, count + 1)
            )
        else:
            polygon_length = (
                math.dist(cursor, command.control1)
                + math.dist(command.control1, command.control2)
                + math.dist(command.control2, command.end)
            )
            count = max(2, int(math.ceil(polygon_length / max(step_mm, 1e-3))))
            start_array = np.asarray(cursor, dtype=float)
            sampled.extend(
                tuple(_evaluate(start_array, command, index / count))
                for index in range(1, count + 1)
            )
        cursor = command.end
    return sampled
