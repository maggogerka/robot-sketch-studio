# Robot Sketch Studio

Local and remote photo-to-vector sketch pipeline for robotic pen drawing.

Robot Sketch Studio accepts JPG, PNG, and WebP, creates a cleaned monochrome sketch, reduces its marks to one-pixel centrelines, and exports robot-friendly open SVG paths plus a JSON trajectory in millimetres. The required `opencv_xdog` engine is CPU-only and needs no model weights.

> v0.1.0 simulates drawing with `MockRobot`; it does **not** control physical hardware.

## What works in v0.1.0

- CPU photo → XDoG sketch → skeleton → SVG pipeline.
- Optional background removal with `rembg` and optional `controlnet_aux` line art.
- 8-connected graph tracing for endpoints, junctions, and closed cycles without reusing edges.
- short-branch removal, Ramer–Douglas–Peucker simplification, and nearest-neighbour stroke ordering with direction reversal;
- A4 portrait, A4 landscape, and custom paper dimensions/margins;
- `sketch.png`, `drawing.svg`, and `trajectory.json` downloads;
- responsive drag-and-drop Web UI with source/sketch/SVG previews and drawing simulation;
- asynchronous versioned API with a bounded work queue and expiring jobs;
- protected remote host mode, CPU/NVIDIA Docker Compose, Windows scripts, and portable-lite build workflow.

Known limitations: detailed or noisy images can produce many short strokes; processing uses a proportion-preserving 2400 px working preview; vectorization follows the visible pixels and does not infer hidden geometry; AI/background extras download third-party weights separately; only the local CPU engine is guaranteed in CI; and real robot adapters are intentionally disabled. See [the roadmap](docs/roadmap.md).

## Windows: double-click start

1. Install 64-bit Python 3.11 or newer and enable `py`/`python` in PATH.
2. Double-click `setup_windows.bat` once. It creates `.venv`, installs dependencies, and copies `.env.example` to `.env`.
3. Double-click `start_local.bat`. The browser opens at <http://127.0.0.1:8000>.

For a portable-lite onedir build, run `build_portable.ps1` after setup. The ZIP appears in `dist/` and includes XDoG, vectorization, Web UI/API, and MockRobot—not Qwen, CUDA, rembg, or model weights. A matching build is also produced by the Windows GitHub workflow.

## Developer start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env          # Windows: copy .env.example .env
python -m robot_sketch_studio
```

Then open <http://127.0.0.1:8000>. Processing starts only after you choose a file and press **Process image**.

Quality checks:

```bash
ruff format --check .
ruff check .
pytest
```

Optional components are deliberately separate:

```bash
python -m pip install -e ".[background]"  # rembg + ONNX Runtime
python -m pip install -e ".[ai]"          # controlnet_aux + PyTorch
```

Their first use can download large model files. Missing extras never prevent `opencv_xdog` from running. Selecting unavailable `lineart_ai` yields a clear failed-job message; selecting unavailable background removal continues without it and returns a warning.

## Docker: CPU or NVIDIA

Copy `.env.example` to `.env` and set a long random `SKETCHARM_API_TOKEN`, because containers listen on `0.0.0.0`:

```bash
docker compose -f compose.cpu.yml up --build -d
# or, on a configured NVIDIA Container Toolkit host:
docker compose -f compose.nvidia.yml up --build -d
```

Named volumes keep `/models`, `/data`, and `/results` outside the image. Move to another Windows/Linux machine by cloning the repository, recreating `.env`, selecting the appropriate Compose file, and starting it; application source changes are not required. Connect to `http://HOST-IP:8000` and supply the Bearer token in the UI or API.

## Remote host and Tailscale

`start_host.bat` generates a per-session token when one is not already set, binds to `0.0.0.0`, prints local URLs, and displays a security warning. For a stable deployment, set a secret token in the machine environment or `.env`.

Do not port-forward this development server directly to the public internet. Prefer [Tailscale](https://tailscale.com/), restrict access to trusted devices, keep CORS origins narrow, and use a reverse proxy with TLS for any broader deployment. Full instructions are in [docs/remote-host.md](docs/remote-host.md).

## API

Endpoints:

- `GET /health`
- `GET /api/v1/capabilities`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/artifacts`
- `GET /api/v1/jobs/{job_id}/artifacts/{name}`
- `DELETE /api/v1/jobs/{job_id}`

Example (omit `Authorization` in localhost mode):

```bash
curl -H "Authorization: Bearer $SKETCHARM_API_TOKEN" \
  -F "image=@portrait.jpg" \
  -F 'options={"engine":"opencv_xdog","paper":"a4_portrait","margin_mm":10}' \
  http://HOST-IP:8000/api/v1/jobs

curl -H "Authorization: Bearer $SKETCHARM_API_TOKEN" \
  http://HOST-IP:8000/api/v1/jobs/JOB_ID
```

OpenAPI documentation is served at `/docs`. The queue is bounded by `SKETCHARM_MAX_WORKERS + SKETCHARM_QUEUE_SIZE`; excess requests return HTTP 429. Uploads are decoded and verified, names are discarded for storage paths, UUID directories are used, and expired finished jobs are cleaned on startup.

## Result layout

Runtime locations are configurable and ignored by Git:

```text
runtime/
├── data/jobs/<uuid>/
│   ├── input.png
│   └── metadata.json
├── results/<uuid>/
│   ├── sketch.png
│   ├── drawing.svg
│   └── trajectory.json
└── models/
```

`drawing.svg` uses physical `mm` dimensions, a matching `viewBox`, `fill="none"`, and open path centrelines. `trajectory.json` contains identical ordered points, page metadata, and distance/time statistics.

## Configuration

All requested settings are documented in `.env.example`: `SKETCHARM_HOST`, `SKETCHARM_PORT`, `SKETCHARM_API_TOKEN`, `SKETCHARM_DEVICE`, `SKETCHARM_MODEL_DIR`, `SKETCHARM_DATA_DIR`, `SKETCHARM_MAX_UPLOAD_MB`, `SKETCHARM_JOB_TTL_HOURS`, `SKETCHARM_CORS_ORIGINS`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_API_KEY`. `SKETCHARM_RESULTS_DIR`, worker count, and queue size are additional deployment controls.

The OpenAI-compatible provider is only an extension point for future Ollama, vLLM, llama.cpp, or LocalAI work. Qwen and Ollama are not required by the core pipeline.

## Architecture and future adapters

The code defines `SketchEngine`, `BackgroundRemovalProvider`, `ComputeProvider`, `LLMProvider`, and `RobotAdapter`. Only `MockRobot` is active. Serial, G-code, ROS, vendor SDK, ONNX Runtime/DirectML, SAM 2, Qwen3-VL, and a Tauri desktop client are future work. See [architecture](docs/architecture.md), [vectorization](docs/vectorization.md), and [robot adapters](docs/robot-adapters.md).

## Acknowledgements and licensing

Robot Sketch Studio source is MIT licensed, copyright © 2026 maggogerka. Third-party libraries and optional models retain their own copyrights and licenses; they are not relicensed by this project. See [docs/model-licenses.md](docs/model-licenses.md) for the authors, licenses, and download behavior of FastAPI, OpenCV, scikit-image, rembg/U²-Net, ControlNet annotators, and other components.

**Developed by [maggogerka](https://github.com/maggogerka).**
