from __future__ import annotations

import argparse
import os
import threading
import webbrowser

import uvicorn

from robot_sketch_studio.config import Settings


def main() -> None:
    defaults = Settings.from_env()
    parser = argparse.ArgumentParser(description="Robot Sketch Studio v0.1.0")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--no-browser", action="store_true")
    arguments = parser.parse_args()
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
