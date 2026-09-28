# Robot Sketch Studio

Photo-to-vector sketch conversion for robotic pen drawing. Developed by
[maggogerka](https://github.com/maggogerka).

Robot Sketch Studio v0.5.0 turns a photograph or ready-made line-art image into a pen-width-aware SVG in
millimetres. It preserves the visual density of the AI sketch with real drawing
passes suitable for a Rotrix DexArm workflow; it does not control the arm.

## What is new in v0.5.0

- **Generated Line-Art Import** accepts ready-made PNG/JPG/WebP line drawings,
  including transparent PNG, and works fully offline without AI, XDoG, or Canny.
- **Preserve Quality** protects thin hair, glasses, eyes, lips, clothing lines,
  and small high-confidence details. **DexArm Optimized** cautiously reduces
  paths and automatically falls back when centerline/face retention degrades.
- **Auto** measures background, contrast, noise, physical stroke width, and
  resolution, then exposes every selected millimetre setting for manual tuning.
- Source, cleaned mask, centerline overlay, and physical SVG previews update in
  the browser. Metrics include paths, nodes, lengths, lifts, overlap, final
  80 × 113 mm size, and configurable estimated drawing time.
- Direct SVG paths use black M/L/C strokes, round caps/joins, no fill or
  unsupported transforms, and one real connected trajectory per path.

The v0.4.2 Single-Line workflow remains available unchanged:

- **Event Single-Line / Один контур — одна линия** exports centerlines only:
  no structural contour, fill pass, repeated coverage pass, or fake multi-`M`
  path can enter the SVG.
- An edge-disjoint skeleton traversal uses every undirected graph edge once,
  continues through junctions by minimum turn, then suppresses physical
  parallel overlap while applying stricter protection inside detected faces.
- **Rotrics Centerline** generates the final 80 × 113 mm SVG directly. Pen
  width, joins, duplicate suppression, and curve tolerance are therefore all
  evaluated in final physical millimetres, not before a 2.62× import resize.
- UI/trajectory metrics now include remaining duplicate paths, parallel overlap,
  unique centerline coverage, pen lifts, physical lengths, commands, and time.
- A one-path `rotrics-line-test.svg` verifies the selected real stroke width in
  Rotrics/G-code before drawing a portrait.

Event Quality from v0.4.1 remains available unchanged:

- **Event Quality / Массовый портрет** combines correct centerlines with sparse
  Fidelity coverage, instead of throwing away all wide-stroke information.
- Quick, Balanced, and Detailed use quality-aware goals. Balanced aims for
  450–650 real paths, global recall 0.72, and face recall 0.82 when the source
  geometry makes those goals reachable.
- OpenCV face detection (with an upper-central fallback) protects eyes, nose,
  mouth, hair, and silhouette. Added contour passes are ranked by marginal
  physical coverage per added drawing second; low-value surfaces stay sparse.
- Reversible nearest-neighbour routing plus bounded 2-opt reduces pen-up travel.
  Drawing speed, travel speed, and pen-lift delay drive the displayed time estimate.
- Speed jobs add `drawing-speed.svg`, `trajectory-speed.json`,
  `vector-speed-preview.png`, and `speed-difference-overlay.png` while retaining
  the original artifact names for API compatibility.

DexArm Fidelity from v0.3.1 is unchanged and remains the quality-first default:

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

1. Download and extract RobotSketchStudio-v0.5.0-windows-x64.zip.
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

### Generated Line-Art Import

Use this when another image generator or drawing application has already made
a clean black-on-white (or transparent) line drawing. Select the engine, choose
**Preserve Quality** or **DexArm Optimized**, set the final paper/pen size, and
press **Auto · analyze**. You can also paste an image from the clipboard.

This mode does not run a photo model and does not trace both sides of a thick
stroke: it converts thick ink to one centerline while preserving thin semantic
lines. `centerline-overlay.png` shows exactly what will become the physical
trajectory. See [the line-art import guide](docs/generated-line-art.md).

Suggested generation instruction:

> Create clean minimalist black pen line art on a pure white or transparent
> background. Preserve identity, pose, silhouette, facial features, hair and
> clothing structure. Use a small number of smooth connected strokes. No gray,
> shadows, texture, hatching, dots, fill, duplicated outlines, text or objects.

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
| Generated Line-Art Import | Offline centerline | Automatic from topology | 0.8 / Auto mm; 80 × 113 mm |
| DexArm Fidelity | Plotter fidelity | Automatic, guard 3000 | 0.5 / 0.08 mm |
| Event Quality / Массовый портрет | Event quality | Quick 300–450; Balanced 450–650; Detailed 650–850 | 0.8 / 0.3 mm |
| Event Single-Line / Один контур — одна линия | Centerline only | Automatic from topology | 0.8 / 0.2 mm; 80 × 113 mm |
| Minimal | Minimal | Target 16 | 0.35 / 0.5 mm |
| Balanced | Centreline | Automatic | 0.35 / 0.3 mm |
| Detailed | Centreline | Automatic | 0.35 / 0.2 mm |

Set **Толщина ручки** to the real tip size. The comparison control switches
between the cleaned AI sketch, physical SVG preview, and a difference map:
green is reproduced ink, red is lost ink, and blue is extra ink.

drawing.svg uses direct unfilled M/L/C paths, real mm dimensions, round
caps/joins, and no transforms or CSS. See the
[DexArm verification guide](docs/dexarm.md) before a physical run.

For mass portrait drawing choose **Event Quality / Массовый портрет**, start with
**Balanced**, use a measured 0.7–1.0 mm pen width, set the DexArm draw/travel
speeds and pen-lift delay, then download
`drawing-speed.svg`. The path ranges are quality-aware targets: sparse sketches
are not padded with invented strokes, and disconnected paths are never combined
with extra `M` commands merely to lower the object count.

When repeated parallel outlines are visible in Rotrics Studio, choose
**Event Single-Line** and the **Rotrics Centerline** export profile. Download
`drawing-speed.svg`; it is already 80 × 113 mm and must be imported at 100%.
Scaling changes the physical spacing between trajectories while the real pen
tip does not scale. Use `rotrics-line-test.svg` for the G-code width check
described in [docs/dexarm.md](docs/dexarm.md).

Legacy API values `event_speed`, `fast_portrait`, and `event_speed_level` remain
accepted and migrate to Event Quality. New clients should send
`vectorization_mode: "event_quality"` and `event_quality_level: "quick" |
"balanced" | "detailed"`.

Runtime data is ignored by Git:

~~~text
runtime/
├── data/jobs/<uuid>/{input.*,metadata.json}
├── results/<uuid>/{confidence.png,sketch.png,drawing.svg,trajectory.json,
│                  vector-preview.png,difference-overlay.png,
│                  drawing-speed.svg,trajectory-speed.json,
│                  vector-speed-preview.png,speed-difference-overlay.png,
│                  rotrics-line-test.svg,centerline-overlay.png}
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
- POST /api/v1/line-art/analyze
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
repeatability, event path budgets, importance retention, bounded 2-opt routing,
time accounting, raster metrics, API jobs, remote image edits, and pipeline output.

Known limitations: AI quality still depends on the photograph and pretrained
model domain; very cluttered or occluded scenes can require Artistic Remote or
manual cleanup. Imported line art with touching unrelated strokes can be
topologically ambiguous and may need source cleanup. The ComfyUI adapter requires a user-supplied API-format workflow.
ONNX/DirectML and real robot control are intentionally outside this release.

See [architecture](docs/architecture.md), [vectorization](docs/vectorization.md),
[DexArm guide](docs/dexarm.md), [API client](docs/api-client.md),
[model licenses](docs/model-licenses.md), and [roadmap](docs/roadmap.md).

Robot Sketch Studio source is MIT licensed. Third-party code and separately
downloaded weights keep their upstream licenses.
