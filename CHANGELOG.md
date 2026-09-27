# Changelog

All notable changes are documented here. This project follows semantic versioning.

## 0.4.2 — 2026-09-27

- Added `event_single_line`, the Event Single-Line preset, and the Rotrics
  Centerline 80 × 113 mm export profile without changing Event Quality or
  Plotter Fidelity output.
- Added minimum-trail edge-disjoint skeleton tracing, physical parallel-path
  collapse with cautious face thresholds, fully confidence-supported endpoint
  joins, reversible routing, and bounded 2-opt.
- Added duplicate/overlap/unique-centerline metrics, schema 1.5 trajectories,
  physical-size warnings, UI comparison, and a one-line Rotrics/G-code
  diagnostic SVG using the selected pen width.
- Added Single-Line unit/regression tests and a reproducible real-SVG benchmark.
  The supplied 423-path Event Quality file becomes 114 paths/113 lifts at
  80 × 113 mm in the replay, with estimated time reduced from 217.57 s to
  61.04 s; remaining redundant paths are zero.

## 0.4.1 — 2026-09-27

- Replaced the centerline-only event result with hybrid `event_quality`:
  Fidelity-derived centerlines and bounded adaptive sparse coverage candidates.
- Added face-aware protection, marginal coverage-per-time selection, Quick / Balanced /
  Detailed goals, face recall, and a combined quality score.
- Preserved `event_speed`, `fast_portrait`, and their saved options as API aliases;
  Plotter Fidelity output remains unchanged.
- Updated the UI, DexArm-safe schema 1.4 trajectories, benchmark tooling,
  regression suite, and Windows portable metadata for v0.4.1.

## 0.4.0 — 2026-09-26

- Added the `event_speed` vector mode and Fast Portrait preset with Express,
  Event, and Fast Detailed path ranges.
- Added topology/confidence-aware importance selection that protects significant
  short details without applying a blanket length cutoff.
- Added reversible nearest-neighbour plus bounded 2-opt routing and configurable
  drawing speed, travel speed, and pen-lift delay time accounting.
- Added DexArm-safe speed SVG/trajectory exports, raster/difference previews, UI
  comparison, SVG command metrics, and regression coverage.
- Preserved the v0.3.1 Fidelity geometry and all existing API artifact names.

## 0.3.1 — 2026-09-24

- Added Plotter Fidelity as the default vector mode with physical pen-width
  rendering, contour or parallel filling, and automatic trajectory counts.
- Preserved short high-confidence details and stopped `target_paths` from
  discarding geometry outside the Minimal mode.
- Replaced unchecked curve interpolation in Fidelity with deterministic,
  error-bounded cubic Bézier fitting and safe line fallbacks.
- Added rasterized trajectory quality metrics, bounded refinement,
  vector-preview.png, and a colour-coded difference-overlay.png.
- Added DexArm-safe SVG validation, schema 1.2 trajectories, UI comparison
  controls, synthetic golden regressions, and v0.3.0 API compatibility tests.

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
