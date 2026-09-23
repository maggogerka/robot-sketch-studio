# Artistic Remote

Artistic Remote lets Robot Sketch Studio keep its vectorization/UI locally while
a stronger image-edit model produces the clean line drawing on another PC.

## Fixed instruction

Every backend receives this instruction; the UI cannot silently weaken it:

~~~text
Transform the input photograph into a clean minimalist pen-and-ink
single-line drawing. Preserve identity, pose, proportions, silhouette
and recognizable features. Use a pure white background and uniform
black lines. Use a small number of long, smooth, continuous strokes.
Remove shadows, textures, photographic noise, skin and fabric texture,
hatching, cross-hatching, dots and tiny disconnected details.
Do not add objects or change the composition. The result must be
suitable for drawing by a pen plotter.
~~~

The returned raster remains a soft grayscale confidence map and goes through the
same hysteresis, graph, join, Bézier, path-budget, and route stages as local AI.

## OpenAI-compatible image edits

This adapter is intended for a gateway exposing Qwen-Image-Edit, FLUX Kontext,
or another edit model with an OpenAI-style API.

- URL: API root, for example http://render-pc:8000/v1
- Connectivity check: GET {URL}/models
- Edit request: multipart POST {URL}/images/edits
- Fields: image, model, prompt, response_format=b64_json
- Accepted response: data[0].b64_json or data[0].url
- Authentication: Authorization: Bearer API_KEY

The model field is passed through unchanged so the same client works with
different gateways.

## ComfyUI

1. Build and test an image-edit workflow in ComfyUI.
2. Export it with **Save (API Format)**.
3. In the JSON, replace the LoadImage node's inputs.image value with {{IMAGE}}.
4. Replace the intended positive prompt text with {{PROMPT}}.
5. Put the JSON on the PC running Robot Sketch Studio.
6. Set SKETCHARM_COMFYUI_WORKFLOW to its absolute path and restart the app.
7. In the UI select ComfyUI and enter the ComfyUI root, normally
   http://render-pc:8188.

The adapter uses /upload/image, /prompt, /history/{prompt_id}, and /view. It
chooses the first image returned by the completed workflow. A reverse proxy may
require a Bearer API key.

## Secrets and networking

The browser stores the remote API key only in sessionStorage. Robot Sketch
Studio receives it in X-Remote-API-Key and removes it from memory when the job
finishes. The key is not part of ProcessingOptions, metadata.json, the workflow
JSON, logs, or repository.

Prefer a trusted LAN or Tailscale. If a gateway crosses an untrusted network,
use TLS and a maintained authenticated reverse proxy. URLs containing embedded
usernames/passwords are rejected.

## Adding another backend

Implement ImageEditProvider.test_connection and ImageEditProvider.edit, then
register it in create_image_edit_provider. The pipeline and GUI consume the
same RGB result and require no vectorization changes. This is the intended
extension point for CLIPasso and SLD-Vectorization.
