# Third-party libraries and model licenses

Robot Sketch Studio source is MIT licensed. Dependencies and separately
downloaded weights retain their own terms. Verify upstream terms for the exact
versions you deploy.

## Required libraries

| Component | License |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD 3-Clause |
| Pydantic | MIT |
| Pillow | HPND |
| NumPy | BSD 3-Clause |
| OpenCV | Apache-2.0 |
| scikit-image | BSD 3-Clause |
| svgwrite | MIT |

## AI and optional components

| Component | Source | License / note |
|---|---|---|
| Informative Drawings | Caroline Chan et al., official GitHub/Hugging Face Space | MIT project; official author-hosted weights, downloaded separately |
| PyTorch | PyTorch contributors / Linux Foundation | BSD-style runtime |
| rembg | Daniel Gatis and contributors | MIT |
| U²-Net | Xuebin Qin et al. | Apache-2.0 upstream project; weights downloaded separately |
| ONNX Runtime | Microsoft and contributors | MIT runtime |

The fixed registry downloads Informative Drawings model.pth/model2.pth from the
official author's Hugging Face Space and U²-Net files from rembg's official
GitHub release. It verifies pinned SHA-256 or MD5 digests and atomically replaces
the target only after validation.

No third-party model weight is stored in Git. The Windows package includes the
PyTorch runtime but downloads line-art weights only after the user requests
them. Remote Qwen/FLUX/ComfyUI models and their licenses are controlled by the
user's external server and are never redistributed here.
