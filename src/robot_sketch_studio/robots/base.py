from __future__ import annotations

from abc import ABC, abstractmethod

from robot_sketch_studio.vectorization import Polyline


class RobotAdapter(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def home(self) -> None: ...

    @abstractmethod
    def calibrate(self) -> None: ...

    @abstractmethod
    def pen_up(self) -> None: ...

    @abstractmethod
    def pen_down(self) -> None: ...

    @abstractmethod
    def move_to(self, x: float, y: float) -> None: ...

    @abstractmethod
    def execute_trajectory(self, strokes: list[Polyline]) -> None: ...

    @abstractmethod
    def emergency_stop(self) -> None: ...
