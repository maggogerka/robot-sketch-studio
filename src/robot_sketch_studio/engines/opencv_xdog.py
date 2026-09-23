from __future__ import annotations

import cv2
import numpy as np

from robot_sketch_studio.engines.base import SketchEngine
from robot_sketch_studio.models import BackgroundMode, ImageProfile, ProcessingOptions


class OpenCVXDoGEngine(SketchEngine):
    name = "opencv_xdog"

    def available(self) -> bool:
        return True

    @staticmethod
    def _resolve_profile(
        rgb: np.ndarray, gray: np.ndarray, options: ProcessingOptions
    ) -> ImageProfile:
        if options.profile != ImageProfile.AUTO:
            return options.profile
        if options.background == BackgroundMode.PERSON:
            return ImageProfile.PORTRAIT
        if options.background in {BackgroundMode.AUTO, BackgroundMode.OBJECT}:
            return ImageProfile.OBJECT
        saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1]
        white_ratio = float(np.mean(gray > 224))
        edge_ratio = float(np.mean(cv2.Canny(gray, 60, 160) > 0))
        if white_ratio > 0.72 and float(saturation.mean()) < 42:
            return ImageProfile.LINE_DRAWING if edge_ratio < 0.16 else ImageProfile.DOCUMENT
        return ImageProfile.PHOTO

    @staticmethod
    def _clean(ink: np.ndarray, detail: int, close_gaps: bool = True) -> np.ndarray:
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
        min_area = max(2, int(10 - detail / 12))
        clean = np.zeros_like(ink)
        for label in range(1, component_count):
            if stats[label, cv2.CC_STAT_AREA] >= min_area:
                clean[labels == label] = 1
        if close_gaps:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel)
        return np.where(clean > 0, 0, 255).astype(np.uint8)

    def render(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        luminance = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[:, :, 0]
        profile = self._resolve_profile(rgb, luminance, options)
        detail = options.detail / 100.0

        if profile in {ImageProfile.DOCUMENT, ImageProfile.LINE_DRAWING}:
            block_size = 21 + 2 * round((1.0 - detail) * 10)
            local = cv2.adaptiveThreshold(
                luminance,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                block_size,
                7 if profile == ImageProfile.LINE_DRAWING else 11,
            )
            # Global dark marks restore long, low-frequency strokes that an
            # adaptive threshold can split on uneven paper.
            dark_limit = min(options.threshold, 170)
            dark = np.where(luminance < dark_limit, 255, 0).astype(np.uint8)
            ink = np.where((local > 0) | (dark > 0), 1, 0).astype(np.uint8)
            return self._clean(ink, options.detail, close_gaps=detail >= 0.35)

        if profile == ImageProfile.PORTRAIT:
            contrast_limit = 1.35 + detail * 0.55
            color_sigma = 55
            edge_bias = 14
            soft_detail = 0.68
        elif profile == ImageProfile.OBJECT:
            contrast_limit = 1.55 + detail * 0.7
            color_sigma = 48
            edge_bias = 7
            soft_detail = 0.58
        else:
            contrast_limit = 1.6 + detail * 0.9
            color_sigma = 30 + 20 * detail
            edge_bias = 0
            soft_detail = 0.45

        clahe = cv2.createCLAHE(clipLimit=contrast_limit, tileGridSize=(8, 8))
        normalized = clahe.apply(luminance)
        diameter = 5 + 2 * round((1.0 - detail) * 2)
        smooth = cv2.bilateralFilter(normalized, diameter, color_sigma, 35)

        sigma = 0.65 + (1.0 - detail) * 1.25
        if profile == ImageProfile.PORTRAIT:
            sigma += 0.2
        first = cv2.GaussianBlur(smooth, (0, 0), sigmaX=sigma)
        second = cv2.GaussianBlur(smooth, (0, 0), sigmaX=sigma * 1.6)
        dog = first.astype(np.float32) / 255.0 - 0.97 * second.astype(np.float32) / 255.0
        epsilon = -0.018 + detail * 0.008
        phi = 12.0 + options.detail * 0.2
        xdog = np.where(dog >= epsilon, 1.0, 1.0 + np.tanh(phi * (dog - epsilon)))
        xdog = np.clip(xdog * 255.0, 0, 255).astype(np.uint8)

        _, binary = cv2.threshold(xdog, options.threshold, 255, cv2.THRESH_BINARY)
        # Multi-scale Canny preserves both crisp boundaries and soft facial or
        # object contours when the XDoG response is weak.
        low = max(24, int(92 - options.detail * 0.55) + edge_bias)
        strong_edges = cv2.Canny(smooth, low, min(255, low * 3))
        soft_edges = cv2.Canny(
            cv2.GaussianBlur(smooth, (0, 0), sigmaX=1.8),
            max(18, low // 2),
            min(255, low * 2),
        )
        ink = np.where(
            (binary == 0) | (strong_edges > 0) | ((soft_edges > 0) & (detail >= soft_detail)),
            1,
            0,
        ).astype(np.uint8)
        cleanup_detail = options.detail - (12 if profile == ImageProfile.PORTRAIT else 5)
        return self._clean(ink, max(0, cleanup_detail))
