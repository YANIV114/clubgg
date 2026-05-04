from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict

# (max_requests, window_seconds)
_DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "/api/v1/auth/login": (10, 60),
    "/api/v1/auth/register": (5, 60),
}


class RateLimitMiddleware:
    def __init__(
        self,
        app,
        limits: dict[str, tuple[int, int]] | None = None,
        enforce: bool = True,
    ) -> None:
        self.app = app
        self._limits = limits if limits is not None else _DEFAULT_LIMITS
        self._enforce = enforce
        self._lock = asyncio.Lock()
        self._hits: dict[tuple[str, str], list[float]] = defaultdict(list)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self._enforce:
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path not in self._limits:
            await self.app(scope, receive, send)
            return

        max_reqs, window = self._limits[path]
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        key = (client_ip, path)
        now = time.monotonic()

        async with self._lock:
            timestamps = self._hits[key]
            cutoff = now - window
            self._hits[key] = [t for t in timestamps if t > cutoff]
            if len(self._hits[key]) >= max_reqs:
                body = json.dumps({"detail": "Too many requests. Please try again later."}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"retry-after", str(window).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            self._hits[key].append(now)

        await self.app(scope, receive, send)
