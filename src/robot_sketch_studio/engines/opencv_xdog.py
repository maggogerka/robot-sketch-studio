from __future__ import annotations

import cv2
import numpy as np

from robot_sketch_studio.engines.base import SketchEngine
from robot_sketch_studio.models import ProcessingOptions


class OpenCVXDoGEngine(SketchEngine):
    name = "opencv_xdog"

    def available(self) -> bool:
        return True

    def render(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        diameter = 5 + 2 * round(options.detail / 25)
        smooth = cv2.bilateralFilter(gray, diameter, 35, 35)

        sigma = 0.7 + (100 - options.detail) / 100 * 1.5
        first = cv2.GaussianBlur(smooth, (0, 0), sigmaX=sigma)
        second = cv2.GaussianBlur(smooth, (0, 0), sigmaX=sigma * 1.6)
        dog = first.astype(np.float32) / 255.0 - 0.97 * second.astype(np.float32) / 255.0
        epsilon = -0.02
        phi = 12.0 + options.detail * 0.18
        xdog = np.where(dog >= epsilon, 1.0, 1.0 + np.tanh(phi * (dog - epsilon)))
        xdog = np.clip(xdog * 255.0, 0, 255).astype(np.uint8)

        _, binary = cv2.threshold(xdog, options.threshold, 255, cv2.THRESH_BINARY)
        # Preserve strong dark contours even when a low-contrast XDoG response is sparse.
        low = max(20, int(90 - options.detail * 0.45))
        strong_edges = cv2.Canny(smooth, low, min(255, low * 3))
        binary[strong_edges > 0] = 0

        ink = (binary == 0).astype(np.uint8)
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
        min_area = max(2, int(12 - options.detail / 10))
        clean = np.zeros_like(ink)
        for label in range(1, component_count):
            if stats[label, cv2.CC_STAT_AREA] >= min_area:
                clean[labels == label] = 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel)
        return np.where(clean > 0, 0, 255).astype(np.uint8)
