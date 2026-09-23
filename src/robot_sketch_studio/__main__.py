from __future__ import annotations

import argparse
import os
import threading
import time
import webbrowser

import uvicorn

from robot_sketch_studio import __version__
from robot_sketch_studio.config import Settings
from robot_sketch_studio.model_manager import ModelManager, UnknownModelError


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
