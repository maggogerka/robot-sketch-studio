from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from robot_sketch_studio import __version__
from robot_sketch_studio.config import Settings
from robot_sketch_studio.model_manager import ModelManager, UnknownModelError


def _browser_host(host: str) -> str:
    if host in {"0.0.0.0", "::", "localhost"}:
        return "127.0.0.1"
    return host


def _running_server_version(host: str, port: int) -> str | None:
    """Return the version when the listener is another Studio instance."""
    target = _browser_host(host)
    if ":" in target:
        target = f"[{target}]"
    try:
        with urllib.request.urlopen(  # noqa: S310 - loopback/user-selected host
            f"http://{target}:{port}/health", timeout=0.75
        ) as response:
            payload = json.load(response)
        if payload.get("status") == "ok" and isinstance(payload.get("version"), str):
            return payload["version"]
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def _port_available(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host == "localhost" else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as listener:
            listener.bind((bind_host, port))
    except OSError:
        return False
    return True


def _show_startup_error(message: str) -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                None, message, "Robot Sketch Studio", 0x10
            )
            return
        except (AttributeError, OSError):
            pass
    print(message, file=sys.stderr)


def _models_command(settings: Settings, action: str, model_id: str | None) -> int:
    manager = ModelManager(settings.model_dir)
    try:
        if action == "path":
            print(manager.model_dir)
            return 0
        if action == "list":
            for item in manager.list():
                dependency = "ready" if item["dependency_available"] else "dependency missing"
                print(f"{item['id']:20} {item['status']:14} {dependency}")
            return 0
        if not model_id:
            raise ValueError("A model id is required")
        try:
            manager.download(model_id)
        except UnknownModelError:
            print(f"Unknown model: {model_id}")
            return 2
        while True:
            item = manager.describe(model_id)
            print(
                f"\r{item['name']}: {item['status']} {item['progress']}%",
                end="",
                flush=True,
            )
            if item["status"] in {"installed", "failed"}:
                print()
                if item["status"] == "failed":
                    print(item["error"])
                    return 1
                print(f"Saved in {item['model_dir']}")
                return 0
            time.sleep(0.25)
    finally:
        manager.close()


def main() -> None:
    # pythonw and windowed PyInstaller builds do not expose standard streams;
    # give Uvicorn's logging handlers a safe sink instead of crashing at start.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    defaults = Settings.from_env()
    parser = argparse.ArgumentParser(description=f"Robot Sketch Studio v{__version__}")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--no-browser", action="store_true")
    commands = parser.add_subparsers(dest="command")
    model_parser = commands.add_parser("models", help="list and download optional models")
    model_commands = model_parser.add_subparsers(dest="model_action", required=True)
    model_commands.add_parser("list")
    model_commands.add_parser("path")
    download = model_commands.add_parser("download")
    download.add_argument("model_id")
    arguments = parser.parse_args()
    if arguments.command == "models":
        raise SystemExit(
            _models_command(
                defaults,
                arguments.model_action,
                getattr(arguments, "model_id", None),
            )
        )
    existing_version = _running_server_version(arguments.host, arguments.port)
    if existing_version:
        url = f"http://{_browser_host(arguments.host)}:{arguments.port}"
        if existing_version == __version__:
            if not arguments.no_browser:
                webbrowser.open(url)
            return
        _show_startup_error(
            f"Port {arguments.port} is already used by Robot Sketch Studio "
            f"v{existing_version}, but this launcher is v{__version__}.\n\n"
            "Close the old Robot Sketch Studio process and start this version again."
        )
        raise SystemExit(2)
    if not _port_available(arguments.host, arguments.port):
        _show_startup_error(
            f"Port {arguments.port} is already in use. Close the program using it "
            "or launch Robot Sketch Studio with another --port value."
        )
        raise SystemExit(2)
    # The app factory reads configuration after Uvicorn imports it. Propagate CLI
    # overrides so --host 0.0.0.0 also activates host-mode authentication.
    os.environ["SKETCHARM_HOST"] = arguments.host
    os.environ["SKETCHARM_PORT"] = str(arguments.port)
    if not arguments.no_browser and arguments.host in {"127.0.0.1", "localhost"}:
        threading.Timer(
            1.0, lambda: webbrowser.open(f"http://{arguments.host}:{arguments.port}")
        ).start()
    uvicorn.run(
        "robot_sketch_studio.app:create_app",
        host=arguments.host,
        port=arguments.port,
        reload=False,
        factory=True,
    )


if __name__ == "__main__":
    main()
