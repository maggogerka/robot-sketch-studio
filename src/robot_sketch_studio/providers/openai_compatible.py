from __future__ import annotations

import json
import urllib.request
from collections.abc import Mapping
from typing import Any

from robot_sketch_studio.providers.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """Optional adapter for Ollama, vLLM, llama.cpp, or LocalAI chat endpoints."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, messages: list[Mapping[str, str]]) -> Mapping[str, Any]:
        if not self.model:
            raise ValueError("An OpenAI-compatible model name is required")
        payload = json.dumps({"model": self.model, "messages": messages, "stream": False}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
