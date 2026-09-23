# Third-party libraries and model licenses

Robot Sketch Studio's own source is MIT licensed. Dependencies and separately downloaded model weights keep their original terms. This file is informational; verify the linked upstream license at the exact version you deploy.

## Required libraries (no model weights)

| Component | Primary author/maintainer | License |
|---|---|---|
| FastAPI | Sebastián Ramírez and contributors | MIT |
| Uvicorn | Encode OSS Ltd. and contributors | BSD 3-Clause |
| Pydantic | Samuel Colvin, Pydantic Services, contributors | MIT |
| Pillow | Pillow contributors; based on PIL by Fredrik Lundh | HPND |
| NumPy | NumPy Developers | BSD 3-Clause |
| OpenCV | OpenCV team/contributors | Apache-2.0 (current 4.x) |
| scikit-image | scikit-image contributors | BSD 3-Clause |
| svgwrite | Manfred Moitzi and contributors | MIT |

The required `opencv_xdog` engine is algorithmic and stores/downloads no weights.

## Optional packages and weights

| Component | Author/source | Code license | Weight notes |
|---|---|---|---|
| rembg | Daniel Gatis and contributors | MIT | Downloads a selected segmentation model separately. |
| U²-Net | Xuebin Qin et al. | Apache-2.0 upstream repository | Used by common rembg sessions; consult the exact downloaded model card. |
| controlnet_aux | Fannovel16 and contributors | Apache-2.0 | Wrapper/annotator code; model weights are downloaded separately. |
| ControlNet annotators (`lllyasviel/Annotators`) | Lvmin Zhang / ControlNet project | Apache-2.0 repository | Confirm each hosted weight/model card before redistribution. |
| PyTorch | PyTorch contributors / Linux Foundation | BSD-style | Runtime only; no line-art weights bundled. |
| ONNX Runtime | Microsoft and contributors | MIT | Runtime only. |

No third-party model weight is stored in Git or included in portable-lite. A model's availability through a downloader does not grant redistribution rights.

The built-in registry downloads only `u2net.onnx` and `u2net_human_seg.onnx` from the official rembg GitHub release, and `sk_model.pth` / `sk_model2.pth` from the official `lllyasviel/Annotators` Hugging Face repository. The application checks the pinned MD5/SHA-256 digest before atomically installing each file. Users must still review and accept the upstream terms for their use case.

## Future integrations (not bundled)

SAM 2 (Meta, Apache-2.0 repository), Qwen3-VL (Qwen Team; consult the exact model card/license), Ollama, vLLM, llama.cpp, LocalAI, DirectML, and Tauri are roadmap items only. Their mention does not mean their code or weights are included.

Developed by maggogerka.
