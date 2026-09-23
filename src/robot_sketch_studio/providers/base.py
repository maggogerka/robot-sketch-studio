from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import numpy as np


class BackgroundRemovalProvider(ABC):
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def remove(self, rgb: np.ndarray, mode: str) -> np.ndarray:
        raise NotImplementedError


class ComputeProvider(ABC):
    @property
    @abstractmethod
    def device(self) -> str:
        raise NotImplementedError


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, messages: list[Mapping[str, str]]) -> Mapping[str, Any]:
        raise NotImplementedError


class ImageEditProvider(ABC):
    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def edit(self, rgb: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class LocalComputeProvider(ComputeProvider):
    def __init__(self, requested_device: str = "auto") -> None:
        self.requested_device = requested_device

    @property
    def device(self) -> str:
        if self.requested_device != "auto":
            return self.requested_device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
