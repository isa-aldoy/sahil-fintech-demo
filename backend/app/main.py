import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import errors
from .config import get_settings
from .db import engine
from .routers import auth, banking, chat, requests

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("sahil")

app = FastAPI(
    title="Sahil API",
    version="2.0.0",
    description="Backend for the Sahil demo banking app. Fictional data only; no real money moves.",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
errors.install(app)

@app.middleware("http")
async def harden(request: Request, call_next):
    request_id = uuid.uuid4().hex[:16]
    started = time.perf_counter()
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_body_bytes:
        response = JSONResponse({"error": {"code": "too_large", "message": "Request is too large."}}, status_code=413)
    else:
        try:
            response = await call_next(request)
        except Exception:  # last resort: still answer in the standard shape, with all headers
            log.exception("%s unhandled error on %s %s", request_id, request.method, request.url.path)
            response = JSONResponse({"error": {"code": "server_error", "message": "Something went wrong on our side."}},
                                    status_code=500)
    h = response.headers
    h["X-Request-Id"] = request_id
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    h["Cross-Origin-Resource-Policy"] = "same-site"
    if request.url.path.startswith("/api"):
        h["Cache-Control"] = "no-store"
        h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.environment == "production":
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # Access log: method, path, status, time. Never bodies, tokens or query strings.
    log.info("%s %s %s -> %s %.0fms", request_id, request.method, request.url.path, response.status_code,
             (time.perf_counter() - started) * 1000)
    return response


# Added last so it is the outermost layer: even error responses carry CORS headers,
# which lets the app show a proper message instead of a generic network failure.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,           # explicit allow-list, never "*"
    allow_credentials=False,                    # tokens travel in the Authorization header, not cookies
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    expose_headers=["Idempotent-Replay", "Retry-After", "X-Request-Id"],
    max_age=600,
)


@app.get("/health", tags=["system"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "assistant": "gemini" if settings.gemini_api_key else "built-in"}


app.include_router(auth.router)
app.include_router(banking.router)
app.include_router(requests.router)
app.include_router(chat.router)
