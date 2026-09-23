# Changelog

All notable changes are documented here. This project follows semantic versioning.

## 0.3.0 — 2026-09-23

- Made official Informative Drawings the default local photo-to-line engine with
  CPU/CUDA selection and continuous confidence-map output.
- Added OpenAI-compatible and ComfyUI Artistic Remote image-edit providers,
  connection testing, and non-persistent API-key handling.
- Rebuilt vectorization around hysteresis, physical feature cleanup, continuous
  junction tracing, aligned endpoint joining, blank-gap checks, target path
  limits, cubic Bézier paths, and optimized draw order.
- Added Minimal, Balanced, and Detailed presets plus all millimetre controls to
  the Web UI.
- Added confidence.png, schema 1.1 Bézier trajectories, a no-console Windows
  start, and an AI-capable portable build.

## 0.2.0 — 2026-09-23

- Added automatic and explicit photo, portrait, object, document, and line-drawing profiles.
- Improved local contrast, multi-scale contour extraction, document thresholding, and graph topology cleanup.
- Added checksum-verified model downloads through the Web UI, API, CLI, and Windows setup script.
- Added a zero-dependency remote client and expanded host/API documentation.

## 0.1.0 — 2026-09-22

- Added local OpenCV XDoG sketch generation and optional background/AI providers.
- Added centreline skeleton graph tracing, SVG/trajectory export, and route statistics.
- Added responsive Web UI, bounded asynchronous API, local/host modes, and MockRobot simulation.
- Added tests, Windows scripts, portable-lite build, Docker configurations, and GitHub Actions.

Developed by maggogerka.
