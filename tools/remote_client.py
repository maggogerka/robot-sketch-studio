#!/usr/bin/env python3
"""Zero-dependency client for a Robot Sketch Studio host."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def api_root(value: str) -> str:
    root = value.rstrip("/")
    return root if root.endswith("/api/v1") else root + "/api/v1"


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_json(
    url: str,
    token: str,
    data: bytes | None = None,
    content_type: str | None = None,
) -> dict:
    request_headers = headers(token)
    if content_type:
        request_headers["Content-Type"] = content_type
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def multipart(image: Path, options: dict) -> tuple[bytes, str]:
    boundary = "----RobotSketch" + uuid.uuid4().hex
    marker = boundary.encode("ascii")
    filename = image.name.replace('"', "")
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks = [
        b"--" + marker,
        (
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: {media_type}\r\n"
        ).encode(),
        image.read_bytes(),
        b"--" + marker,
        b'Content-Disposition: form-data; name="options"\r\n',
        json.dumps(options, separators=(",", ":")).encode(),
        b"--" + marker + b"--",
        b"",
    ]
    return b"\r\n".join(chunks), f"multipart/form-data; boundary={boundary}"


def download(url: str, token: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=headers(token))
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--url",
        default=os.getenv("SKETCHARM_URL", "http://127.0.0.1:8000"),
        help="host URL, for example http://drawing-pc:8000",
    )
    parser.add_argument("--token", default=os.getenv("SKETCHARM_API_TOKEN", ""))
    parser.add_argument("--output", type=Path, default=Path("robot-sketch-result"))
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--engine", default="opencv_xdog")
    parser.add_argument("--background", default="off")
    parser.add_argument("--options", default="{}", help="extra options as a JSON object")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    if not args.image.is_file():
        parser.error(f"image does not exist: {args.image}")
    try:
        extra = json.loads(args.options)
        if not isinstance(extra, dict):
            raise ValueError("--options must contain a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    options = {
        "profile": args.profile,
        "engine": args.engine,
        "background": args.background,
        **extra,
    }
    root = api_root(args.url)
    body, content_type = multipart(args.image, options)
    created = request_json(f"{root}/jobs", args.token, body, content_type)
    job_id = created["id"]
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        job = request_json(f"{root}/jobs/{job_id}", args.token)
        print(
            f"\r{job['state']}: {job['progress']}% {job['message']}",
            end="",
            flush=True,
        )
        if job["state"] == "failed":
            print()
            raise RuntimeError(job.get("error") or "processing failed")
        if job["state"] == "completed":
            print()
            break
        time.sleep(0.5)
    else:
        raise TimeoutError(f"job {job_id} did not finish in {args.timeout:g} seconds")

    listing = request_json(f"{root}/jobs/{job_id}/artifacts", args.token)
    args.output.mkdir(parents=True, exist_ok=True)
    for artifact in listing["artifacts"]:
        name = Path(artifact["name"]).name
        destination = args.output / name
        download(f"{root}/jobs/{job_id}/artifacts/{name}", args.token, destination)
        print(f"saved {destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, TimeoutError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
