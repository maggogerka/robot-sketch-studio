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
py -3 tools\remote_client.py photo.jpg --url http://HOST-IP:8000 --options '{"target_paths":24}'
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
