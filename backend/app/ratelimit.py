"""Sliding-window rate limiter.

State is kept in process memory, which is correct for the single-instance demo.
A multi-instance deployment would swap `_Store` for Redis; the interface stays the same.
Account lockout (the control that matters most against password guessing) is stored
in PostgreSQL and is therefore not affected by restarts or scaling.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from .config import get_settings
from .errors import ApiError


class _Store:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> float | None:
        """Record a hit. Returns seconds to wait if the limit is exceeded, else None."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, window - (now - q[0]))
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


store = _Store()


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def check(bucket: str, key: str, limit: int, window: int) -> None:
    if not get_settings().rate_limit_enabled:
        return
    wait = store.hit(f"{bucket}:{key}", limit, window)
    if wait is not None:
        raise ApiError(429, "too_many_requests", "Too many attempts. Please wait a moment and try again.",
                       headers={"Retry-After": str(int(wait))})


def limit_ip(bucket: str, limit: int, window: int):
    def dep(request: Request) -> None:
        check(bucket, client_ip(request), limit, window)
    return dep
