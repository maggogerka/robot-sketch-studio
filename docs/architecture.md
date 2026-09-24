# Architecture

~~~text
browser / API
  → verified upload → bounded JobManager
  → optional BackgroundRemovalProvider
  → CleanAIEngine | Artistic Remote ImageEditProvider | XDoG fallback
  → soft confidence map
  → vector mode: Plotter Fidelity | centreline | minimal
  → hysteresis / topology / physical fill / bounded cubic fitting
  → physical raster comparison and bounded refinement
  → six artifacts including vector preview and difference overlay
~~~

SketchEngine isolates local raster-to-line inference. ImageEditProvider isolates
remote OpenAI-compatible and ComfyUI backends, so a future CLIPasso or SLD
implementation can be registered without changing the GUI contract.
BackgroundRemovalProvider and ComputeProvider remain separate. Only MockRobot
exists; no production hardware adapter is enabled.

Plotter Fidelity lives in a separate module from the legacy centreline
vectorizer. It works per connected-component ROI, uses a distance transform for
wide ink, and renders exact trajectories back at the physical pen width.
Error-bounded Bézier fitting is also isolated, allowing future vector backends
to reuse the exporter without changing the UI or job API.

The Clean AI backend implements the official Informative Drawings generator
architecture locally and loads checksum-pinned official weights. PyTorch is
imported lazily, device selection is auto, cpu, or cuda, and inference returns
floating-point confidence rather than an immediate hard threshold.

Remote URLs/models are stored with job options. Remote API keys are different:
the browser keeps one in session storage, sends it in X-Remote-API-Key, and
JobManager keeps it only in memory until that job finishes. It is never
serialized to metadata.json.

The static HTML/CSS/JavaScript UI has no frontend build toolchain. Runtime roots
are configurable, UUIDs define job directories, queue capacity is bounded, and
host-mode /api requests require a Bearer token.
