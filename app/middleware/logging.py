from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, self.datefmt),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


class RequestLoggingMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_code: list[int] = []

        async def _send(message) -> None:
            if message["type"] == "http.response.start":
                status_code.append(message["status"])
            await send(message)

        await self.app(scope, receive, _send)

        if status_code and status_code[0] >= 400:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            method = scope.get("method", "")
            path = scope.get("path", "")
            logger.warning("%s %s → %d (%.1f ms)", method, path, status_code[0], duration_ms)
