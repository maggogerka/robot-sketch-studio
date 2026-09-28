# API and remote client

The simplest remote workflow is the Web UI at http://HOST-IP:8000. Enter the
host Bearer token once; it remains only in that browser tab's session storage.

## One-file Python client

tools/remote_client.py uses only Python's standard library:

~~~powershell
py -3 tools\remote_client.py portrait.jpg --url http://HOST-IP:8000 --token YOUR_TOKEN
~~~

Useful variants:

~~~powershell
py -3 tools\remote_client.py scan.png --url http://HOST-IP:8000 --engine opencv_xdog --profile document
py -3 tools\remote_client.py portrait.jpg --url http://HOST-IP:8000 --preset minimal
py -3 tools\remote_client.py photo.jpg --url http://HOST-IP:8000 --options '{"pen_width_mm":0.5,"ink_coverage_target":0.97}'
~~~

The command creates robot-sketch-result and downloads every artifact listed by
the server. Use --output PATH to change it. SKETCHARM_URL and
SKETCHARM_API_TOKEN can replace the corresponding arguments.

## Direct HTTP sequence

All /api/v1/* endpoints require Authorization: Bearer TOKEN in host mode.
/health remains public.

1. POST /api/v1/jobs as multipart form data with image and JSON options.
2. Poll GET /api/v1/jobs/{id} to completed or failed.
3. Read GET /api/v1/jobs/{id}/artifacts.
4. Download the listed artifact URLs.
5. Optionally DELETE /api/v1/jobs/{id}.

~~~powershell
curl.exe -H "Authorization: Bearer YOUR_TOKEN" -F "image=@portrait.jpg" -F "options={\engine\:\clean_ai\,\drawing_preset\:\balanced\}" http://HOST-IP:8000/api/v1/jobs
curl.exe -H "Authorization: Bearer YOUR_TOKEN" http://HOST-IP:8000/api/v1/jobs/JOB_ID
~~~

OpenAPI documentation is at http://HOST-IP:8000/docs.

## Vector options in v0.5.0

`vectorization_mode` accepts `plotter_fidelity`, `event_quality`,
`event_single_line`, `event_speed`, `centerline`, or `minimal`. Fidelity uses
`pen_width_mm` (0.2–2.0),
`ink_coverage_target` (0.80–0.995), `fill_strategy` (`contour`,
`parallel`, or `none`), `maximum_plotter_paths` (100–10000), and
`preserve_short_details`. `target_paths` is applied only in Minimal.

The default `dexarm_fidelity` preset selects a 0.5 mm pen, 97% target recall,
concentric filling, and a 3000-path protection limit. Existing v0.3.0 requests
and the Minimal/Balanced/Detailed preset names remain valid.

`event_quality` selects the hybrid mass-portrait preset.
`event_quality_level` accepts `quick`, `balanced`, or `detailed`. It uses
`adaptive_sparse` fill and reports face recall plus quality score. Time estimates
use configurable `drawing_speed_mm_s`, `travel_speed_mm_s`, and
`pen_lift_delay_s`. The v0.4.0 values `fast_portrait`, `event_speed`, and
`event_speed_level` remain accepted and map to the new implementation.

`event_single_line` selects only centerline candidates. Use
`export_profile: "rotrics_centerline"`, `paper: "rotrics_80x113"`, and
`fill_strategy: "none"` to generate the final 80 × 113 mm Rotrics file without
import scaling. The matching preset name is `event_single_line`. Schema 1.5
adds `redundant_path_count`, `parallel_overlap_ratio`,
`unique_centerline_coverage`, and `silhouette_recall`.

For existing line art, send `engine: "generated_line_art"` and
`drawing_preset: "generated_line_art"`. `line_art_import_profile` accepts
`preserve_quality` or `dexarm_optimized`; `line_art_auto` defaults to true.
POST `/api/v1/line-art/analyze` accepts the same multipart image/options fields
and returns detected background, line level, physical stroke width, noise ratio,
and recommended manual values. It is offline and does not create a job.

Completed jobs list six artifacts: confidence.png, sketch.png, drawing.svg,
trajectory.json, vector-preview.png, and difference-overlay.png. Schema 1.2
trajectory JSON includes exact M/L/C commands, quality metrics, warnings, and
the real path count.

Event Quality, Event Single-Line, and legacy Event Speed jobs additionally list
drawing-speed.svg, trajectory-speed.json, vector-speed-preview.png, and
speed-difference-overlay.png. Single-Line also lists rotrics-line-test.svg. The original six
names remain present so existing clients do not need conditional download code.
Generated line-art jobs additionally list `centerline-overlay.png`.

## Models and remote image edits

GET /api/v1/models reports dependency, weights, progress, path, and license.
POST /api/v1/models/informative-drawings/download starts a verified download.
Only fixed registry IDs are accepted.

POST /api/v1/remote/test accepts backend, url, and optional model JSON. Put an
image-edit secret only in X-Remote-API-Key. The same header can accompany a job
whose engine is artistic_remote. It is never included in the options JSON.

Common errors are 401 for a wrong host token, 413 for a large upload, 415 for an
unsupported format, 422 for invalid options, 429 for a full queue, and 502 when
a remote image backend cannot be reached.
