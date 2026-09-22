from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from robot_sketch_studio.models import ProcessingOptions


class EngineUnavailableError(RuntimeError):
    pass


class SketchEngine(ABC):
    name: str

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def render(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        """Return an uint8 image with black ink on a white background."""
        raise NotImplementedError
