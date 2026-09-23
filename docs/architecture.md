# Architecture

~~~text
browser / API
  → verified upload → bounded JobManager
  → optional BackgroundRemovalProvider
  → CleanAIEngine | Artistic Remote ImageEditProvider | XDoG fallback
  → soft confidence map
  → hysteresis / skeleton graph / smart joining / cubic fitting
  → confidence PNG + cleaned PNG + SVG + trajectory JSON
~~~

SketchEngine isolates local raster-to-line inference. ImageEditProvider isolates
remote OpenAI-compatible and ComfyUI backends, so a future CLIPasso or SLD
implementation can be registered without changing the GUI contract.
BackgroundRemovalProvider and ComputeProvider remain separate. Only MockRobot
exists; no production hardware adapter is enabled.

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
