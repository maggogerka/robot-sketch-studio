from __future__ import annotations

import importlib.util
import os
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from robot_sketch_studio.providers.base import BackgroundRemovalProvider


class RembgProvider(BackgroundRemovalProvider):
    def __init__(self, model_dir: Path | None = None) -> None:
        self._sessions: dict[str, object] = {}
        if model_dir is not None:
            os.environ.setdefault("U2NET_HOME", str(model_dir.expanduser().resolve()))

    def available(self) -> bool:
        return importlib.util.find_spec("rembg") is not None

    def remove(self, rgb: np.ndarray, mode: str) -> np.ndarray:
        if not self.available():
            raise RuntimeError("rembg is not installed")
        from rembg import new_session, remove

        buffer = BytesIO()
        Image.fromarray(rgb, mode="RGB").save(buffer, format="PNG")
        model = "u2net_human_seg" if mode == "person" else "u2net"
        if model not in self._sessions:
            self._sessions[model] = new_session(model)
        output = remove(buffer.getvalue(), session=self._sessions[model], only_mask=False)
        rgba = Image.open(BytesIO(output)).convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        white.alpha_composite(rgba)
        return np.asarray(white.convert("RGB"), dtype=np.uint8)
