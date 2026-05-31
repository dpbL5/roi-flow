from __future__ import annotations

import os
import threading
import time
from http.server import HTTPServer
from urllib.request import urlopen

import webview

import app


APP_URL = f"http://{app.HOST}:{app.PORT}"


def server_is_ready(timeout: float = 1.0) -> bool:
    try:
        with urlopen(f"{APP_URL}/api/health", timeout=timeout):
            return True
    except Exception:
        return False


def wait_for_server(timeout_seconds: float = 15.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if server_is_ready(timeout=1.0):
            return True
        time.sleep(0.25)
    return False


def start_embedded_server() -> HTTPServer:
    server = app.create_server()
    thread = threading.Thread(target=app.serve_server, args=(server,), daemon=True)
    thread.start()
    return server


def main() -> None:
    server = None
    if not server_is_ready(timeout=0.5):
        server = start_embedded_server()

    if not wait_for_server():
        raise RuntimeError("Server local của Flow Veo Studio không khởi động được.")

    try:
        webview.create_window(
            "Flow Veo Studio",
            APP_URL,
            width=1280,
            height=860,
            min_size=(1040, 700),
        )
        webview.start(debug=os.environ.get("FLOW_VEO_DESKTOP_DEBUG") == "1")
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
