# Robot Sketch Studio

Photo-to-vector sketch conversion for robotic pen drawing. Developed by
[maggogerka](https://github.com/maggogerka).

Robot Sketch Studio v0.3.1 turns a photograph into a pen-width-aware SVG in
millimetres. It preserves the visual density of the AI sketch with real drawing
passes suitable for a Rotrix DexArm workflow; it does not control the arm.

## What is new in v0.3.1

- **DexArm Fidelity** is the default preset. Thin ink becomes centreline paths;
  wide ink gets concentric or parallel passes spaced for the selected pen.
- Fidelity retains short high-confidence facial details and determines the path
  count from the drawing. `target_paths` is used only by Minimal.
- Cubic Bézier fitting is error-bounded in millimetres and falls back to safe
  line commands at sharp or unsafe geometry.
- Every result is rasterized at physical pen width and measured for recall,
  precision, IoU, area difference, and mean line distance.
- New vector-preview.png and difference-overlay.png show the expected DexArm
  output and lost/extra ink before a physical run.

## Windows: start without a terminal

### Release ZIP

1. Download and extract RobotSketchStudio-v0.3.1-windows-x64.zip.
2. Double-click RobotSketchStudio.exe. It starts without a console window and
   opens <http://127.0.0.1:8000>.
3. Open **Models** and download **Informative Drawings (official)**.
4. Choose a photo, select a preset, press **Process image**, then download
   drawing.svg.

The model is stored in %LOCALAPPDATA%\RobotSketchStudio\models, not in the
program folder. Its SHA-256 is verified before it is installed.

### Run from source

Install 64-bit Python 3.11 or newer, then:

1. Double-click setup_windows.bat once.
2. Double-click start_local.bat; the browser opens and the server runs without
   a terminal window.
3. Download the AI weights in **Models**. Alternatively, double-click
   setup_models_windows.bat and choose Clean AI Sketch.

For development:

~~~powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev,ai]"
python -m robot_sketch_studio
~~~

## Choosing a mode

### Clean AI Sketch

Use this for normal portraits, people, and objects. The backend is a local
PyTorch implementation of the architecture published by
[Informative Drawings](https://github.com/carolineec/informative-drawings).
SKETCHARM_DEVICE=auto selects CUDA when PyTorch can use it and CPU otherwise.
The official author-hosted weights are downloaded only on request.

### Artistic Remote

Use this when another PC runs a larger Qwen-Image-Edit, FLUX Kontext, or ComfyUI
workflow:

1. Select **Artistic Remote**.
2. Choose **OpenAI-compatible image edit** or **ComfyUI workflow**.
3. Enter the server URL and optional model/API key.
4. Press **Test connection**, then process the photo normally.

The API key is sent in X-Remote-API-Key, held only in browser session storage
and job memory, and never written to job metadata. Do not put secrets into the
URL or commit them to the repository.

For OpenAI-compatible servers, enter the API root such as
http://render-pc:8000/v1; the server must implement GET /models and
POST /images/edits with either b64_json or an image URL in the result.

For ComfyUI, export a workflow in API format, set its Load Image value to
{{IMAGE}}, set the positive prompt text to {{PROMPT}}, and configure the
workflow file on the Robot Sketch Studio PC:

~~~powershell
setx SKETCHARM_COMFYUI_WORKFLOW "C:\workflows\plotter-edit-api.json"
~~~

Restart Robot Sketch Studio after setting it. Full examples and the immutable
prompt are in [docs/artistic-remote.md](docs/artistic-remote.md).

## Presets and output

| Preset | Mode | Paths | Pen / curve tolerance |
|---|---|---|---|
| DexArm Fidelity | Plotter fidelity | Automatic, guard 3000 | 0.5 / 0.08 mm |
| Minimal | Minimal | Target 16 | 0.35 / 0.5 mm |
| Balanced | Centreline | Automatic | 0.35 / 0.3 mm |
| Detailed | Centreline | Automatic | 0.35 / 0.2 mm |

Set **Толщина ручки** to the real tip size. The comparison control switches
between the cleaned AI sketch, physical SVG preview, and a difference map:
green is reproduced ink, red is lost ink, and blue is extra ink.

drawing.svg uses direct unfilled M/L/C paths, real mm dimensions, round
caps/joins, and no transforms or CSS. See the
[DexArm verification guide](docs/dexarm.md) before a physical run.

Runtime data is ignored by Git:

~~~text
runtime/
├── data/jobs/<uuid>/{input.*,metadata.json}
├── results/<uuid>/{confidence.png,sketch.png,drawing.svg,trajectory.json,
│                  vector-preview.png,difference-overlay.png}
└── models/lineart/{sk_model.pth,sk_model2.pth}
~~~

## Use a powerful PC as the complete processing host

On the powerful Windows PC:

1. Run setup_windows.bat and download the AI model.
2. Run start_host.bat.
3. Copy the printed LAN/Tailscale URL and Bearer token.

On another PC, open that URL, enter the token under **Remote host token**, and
use the same UI. Or use the standard-library client:

~~~powershell
py -3 tools\remote_client.py photo.jpg --url http://drawing-pc:8000 --token YOUR_TOKEN
~~~

Do not expose the development server directly to the public internet. Prefer
Tailscale or a trusted LAN. See [docs/remote-host.md](docs/remote-host.md) and
[docs/api-client.md](docs/api-client.md).

## API

Main endpoints:

- GET /health
- GET /api/v1/capabilities
- GET /api/v1/models
- POST /api/v1/models/{model_id}/download
- POST /api/v1/remote/test
- POST /api/v1/jobs
- GET /api/v1/jobs/{job_id}
- GET /api/v1/jobs/{job_id}/artifacts
- DELETE /api/v1/jobs/{job_id}

Example for a protected host:

~~~bash
curl -H "Authorization: Bearer TOKEN" \
  -F "image=@portrait.jpg" \
  -F 'options={"engine":"clean_ai","drawing_preset":"balanced"}' \
  http://HOST-IP:8000/api/v1/jobs
~~~

Interactive OpenAPI documentation is at /docs. Host mode requires
SKETCHARM_API_TOKEN; the bounded queue returns HTTP 429 when full. Uploads are
decoded and verified, storage uses UUID directories, and expired completed jobs
are removed on startup.

## Configuration

Copy .env.example to .env. Important settings:

- SKETCHARM_HOST, SKETCHARM_PORT, SKETCHARM_API_TOKEN
- SKETCHARM_DEVICE=auto|cpu|cuda
- SKETCHARM_MODEL_DIR, SKETCHARM_DATA_DIR, SKETCHARM_RESULTS_DIR
- SKETCHARM_MAX_UPLOAD_MB, SKETCHARM_JOB_TTL_HOURS
- SKETCHARM_MAX_WORKERS, SKETCHARM_QUEUE_SIZE
- SKETCHARM_CORS_ORIGINS
- SKETCHARM_COMFYUI_WORKFLOW

CPU and NVIDIA Docker Compose files remain available for hosting. Model weights
are not committed or bundled; the fixed registry verifies each download.

## Quality checks

~~~powershell
ruff format --check .
ruff check .
pytest
~~~

The deterministic suite includes synthetic thin/thick/circle golden fixtures,
short-detail and blank-gap checks, physical fill density, SVG safety,
repeatability, raster metrics, API jobs, remote image edits, and pipeline output.

Known limitations: AI quality still depends on the photograph and pretrained
model domain; very cluttered or occluded scenes can require Artistic Remote or
manual cleanup. The ComfyUI adapter requires a user-supplied API-format workflow.
ONNX/DirectML and real robot control are intentionally outside this release.

See [architecture](docs/architecture.md), [vectorization](docs/vectorization.md),
[DexArm guide](docs/dexarm.md), [API client](docs/api-client.md),
[model licenses](docs/model-licenses.md), and [roadmap](docs/roadmap.md).

Robot Sketch Studio source is MIT licensed. Third-party code and separately
downloaded weights keep their upstream licenses.
