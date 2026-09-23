# Architecture

The v0.2.0 request path is intentionally small:

```text
browser/API → upload verification → bounded JobManager
            → optional BackgroundRemovalProvider
            → SketchEngine (OpenCV XDoG or optional Lineart AI)
            → skeleton graph/vectorizer → PNG + SVG + trajectory JSON
            → Web preview / MockRobot simulation
```

`Settings` loads `.env` without storing secrets in source. `JobManager` uses UUID-only directories, a bounded semaphore, and a fixed-size thread executor. Persistent metadata permits inspection after completion; an interrupted queued/running job is marked failed after restart. Finished jobs older than the configured TTL are removed at startup.

Interfaces isolate future implementation choices:

- `SketchEngine`: raster image to clean black-on-white line art.
- `BackgroundRemovalProvider`: optional segmentation/compositing.
- `ComputeProvider`: CPU/CUDA selection without coupling the CPU path to PyTorch.
- `LLMProvider`: optional OpenAI-compatible endpoint adapter.
- `RobotAdapter`: the command vocabulary for a robot; only the in-memory mock is safe and active.

The Web UI is static HTML/CSS/JavaScript served by FastAPI. It has no build toolchain. All server paths are relative to the installed package or configured runtime roots, so moving the repository does not require code edits.

Developed by maggogerka.
