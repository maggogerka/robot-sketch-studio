from __future__ import annotations

from robot_sketch_studio.robots.base import RobotAdapter
from robot_sketch_studio.vectorization import Polyline


class MockRobot(RobotAdapter):
    """A deterministic in-memory adapter; it never controls physical hardware."""

    def __init__(self) -> None:
        self.connected = False
        self.calibrated = False
        self.pen_is_down = False
        self.position = (0.0, 0.0)
        self.stopped = False
        self.events: list[tuple[str, tuple[float, ...]]] = []

    def connect(self) -> None:
        self.connected = True
        self.stopped = False
        self.events.append(("connect", ()))

    def disconnect(self) -> None:
        self.pen_up()
        self.connected = False
        self.events.append(("disconnect", ()))

    def home(self) -> None:
        self._ready()
        self.pen_up()
        self.move_to(0, 0)

    def calibrate(self) -> None:
        self._ready()
        self.calibrated = True
        self.events.append(("calibrate", ()))

    def pen_up(self) -> None:
        self.pen_is_down = False
        self.events.append(("pen_up", ()))

    def pen_down(self) -> None:
        self._ready()
        self.pen_is_down = True
        self.events.append(("pen_down", ()))

    def move_to(self, x: float, y: float) -> None:
        self._ready()
        self.position = (float(x), float(y))
        self.events.append(("move_to", self.position))

    def execute_trajectory(self, strokes: list[Polyline]) -> None:
        self._ready()
        for stroke in strokes:
            if not stroke:
                continue
            self.pen_up()
            self.move_to(*stroke[0])
            self.pen_down()
            for point in stroke[1:]:
                self.move_to(*point)
        self.pen_up()

    def emergency_stop(self) -> None:
        self.pen_is_down = False
        self.stopped = True
        self.events.append(("emergency_stop", ()))

    def _ready(self) -> None:
        if not self.connected:
            raise RuntimeError("MockRobot is not connected")
        if self.stopped:
            raise RuntimeError("MockRobot emergency stop is active")
