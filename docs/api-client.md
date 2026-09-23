# API and remote client

The simplest remote workflow is the Web UI at `http://HOST-IP:8000`. Enter the Bearer token once, choose a photo, leave **Image profile** on **Auto**, and download the SVG. The token is kept only in that browser tab's session storage.

## One-file Python client

`tools/remote_client.py` uses only Python's standard library:

```powershell
py -3 tools\remote_client.py portrait.jpg --url http://HOST-IP:8000 --token YOUR_TOKEN
```

Useful variants:

```powershell
py -3 tools\remote_client.py scan.png --url http://HOST-IP:8000 --token YOUR_TOKEN --profile document
py -3 tools\remote_client.py object.jpg --url http://HOST-IP:8000 --token YOUR_TOKEN --background object
py -3 tools\remote_client.py photo.jpg --url http://HOST-IP:8000 --token YOUR_TOKEN --options "{\detail\:70,\smoothing\:0.8}"
```

The command creates `robot-sketch-result` with `sketch.png`, `drawing.svg`, and `trajectory.json`. Use `--output PATH` to change it. `SKETCHARM_URL` and `SKETCHARM_API_TOKEN` environment variables can replace the corresponding arguments.

## Direct HTTP sequence

All `/api/v1/*` endpoints require `Authorization: Bearer TOKEN` in host mode. `/health` remains public.

1. `POST /api/v1/jobs` as multipart form data with `image` and a JSON `options` string.
2. Poll `GET /api/v1/jobs/{id}` until `state` is `completed` or `failed`.
3. Read `GET /api/v1/jobs/{id}/artifacts`.
4. Download the listed artifact URLs.
5. Optionally call `DELETE /api/v1/jobs/{id}`.

```powershell
curl.exe -H "Authorization: Bearer YOUR_TOKEN" -F "image=@portrait.jpg" -F "options={\profile\:\auto\}" http://HOST-IP:8000/api/v1/jobs
curl.exe -H "Authorization: Bearer YOUR_TOKEN" http://HOST-IP:8000/api/v1/jobs/JOB_ID
```

OpenAPI and interactive request documentation are available at `http://HOST-IP:8000/docs`.

## Model API

`GET /api/v1/models` reports dependency, weight, progress, path, and license status. `POST /api/v1/models/{id}/download` starts one checksum-verified host download and returns HTTP 202. Poll the model list until its status becomes `installed` or `failed`. Arbitrary URLs and filesystem paths are intentionally not accepted.

Common errors are 401 for a missing/wrong token, 413 for an oversized upload, 415 for an unsupported format, 422 for invalid options, and 429 when the bounded processing queue is full.
