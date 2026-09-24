# Roadmap

## Completed in 0.3.1

- Plotter Fidelity with physical pen passes, automatic path counts, contour and
  parallel fill, short-detail retention, and bounded refinement.
- Error-bounded cubic Bézier fitting with safe line fallback and deterministic
  DexArm SVG output.
- Raster similarity metrics, physical vector preview, difference overlay,
  synthetic golden tests, and updated Windows portable workflow.

## Completed in 0.3.0

- Official Informative Drawings local backend with CPU/CUDA auto-selection and
  soft confidence maps.
- OpenAI-compatible and ComfyUI Artistic Remote adapters with connection test
  and memory-only API keys.
- Minimal, Balanced, and Detailed physical presets.
- Hysteresis cleanup, graph continuation through junctions, direction-aware
  endpoint joining with empty-gap rejection, path budgeting, cubic Bézier
  output, and pen-up route optimization.
- Four original downloadable artifacts and full Windows AI portable build.

## Next photo-to-vector work

- Versioned visual benchmark corpus and perceptual regression scoring.
- ONNX Runtime / DirectML export after a reproducible parity test against the
  official PyTorch checkpoint.
- Better global route optimization for very large trajectory sets.
- Foreground-aware adaptive detail and interactive keep/remove stroke editing.
- Ready-made, versioned ComfyUI workflow examples for selected open models.
- Optional CLIPasso and SLD-Vectorization providers behind ImageEditProvider.

## Later, outside the current focus

- Safe, separately packaged Serial/G-code/ROS/vendor robot plugins.
- Desktop project history and signed installers.

Any real-hardware milestone requires independent workspace, collision, pen
height, emergency-stop, and operator-safety design.
