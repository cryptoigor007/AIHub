"""
Заглушка до готовности привратника.
Туннель указывает сюда, пока gatekeeper не отвечает 200 на /health.
Все запросы → 503.
Только stdlib — без лишних зависимостей.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from ..common.config import get_settings
from ..common.logging import get_logger, setup_logging

log = get_logger(__name__)


class StubHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        log.debug("stub_request", msg=format % args)

    def _reply_503(self) -> None:
        body = json.dumps(
            {"error": "AIHub ещё не готов", "status": 503},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", "5")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._reply_503()

    def do_POST(self) -> None:  # noqa: N802
        self._reply_503()

    def do_PUT(self) -> None:  # noqa: N802
        self._reply_503()

    def do_DELETE(self) -> None:  # noqa: N802
        self._reply_503()

    def do_PATCH(self) -> None:  # noqa: N802
        self._reply_503()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._reply_503()

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(503)
        self.send_header("Retry-After", "5")
        self.end_headers()


class StubServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer((self.host, self.port), StubHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        log.info("stub_started", host=self.host, port=self.port)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            log.info("stub_stopped")


def run_stub_forever() -> None:
    setup_logging()
    settings = get_settings()
    port = settings.gatekeeper_port + 1
    server = StubServer(settings.gatekeeper_host, port)
    server.start()
    log.info("stub_blocking", port=port)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    run_stub_forever()
