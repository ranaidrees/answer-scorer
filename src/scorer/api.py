"""The HTTP API and the demo page (spec FR-1, FR-9, FR-10).

Routes: `POST /api/score`, `GET /healthz`, `GET /readyz` and `GET /`.

Nothing here logs a request body, an answer, a question, a rationale or an evidence quote,
and no error body ever echoes the input. A model failure is a 503 with no score of any
kind. A platform guardrail block is a 200 with `score: null`, as the pipeline returns it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from scorer.config import (
    PromptError,
    RubricError,
    Settings,
    load_all_rubrics,
    load_prompt,
)
from scorer.model_client import ModelClient, ModelUnavailableError, build_model_client
from scorer.pipeline import ScoringError, score_answer
from scorer.schemas import ScoreRequest
from scorer.telemetry import (
    SCORE_SPAN_NAME,
    PricesError,
    configure_telemetry,
    flush_telemetry,
    get_tracer,
    load_prices,
    score_span_attributes,
    trace_id_of,
)

logger = logging.getLogger("scorer.api")

DEMO_TOKEN_HEADER = "X-Demo-Token"
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60.0
MAX_BODY_BYTES = 100_000
UNPROBED_URLS = "healthz,readyz"
UI_PAGE = Path(__file__).parent / "ui" / "index.html"

_INLINE_BLOCK = re.compile(r"<(script|style)>(.*?)</\1>", re.DOTALL)


class RateLimiter:
    """A sliding-window limit per key, held in memory. One process, so one replica each."""

    def __init__(
        self,
        limit: int = RATE_LIMIT_REQUESTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Record one request for `key`. False when it is over the limit."""
        now = self._clock()
        cutoff = now - self.window_seconds
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self._max_keys:
                self._drop_idle(cutoff)
            hits = self._hits[key] = deque()
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def _drop_idle(self, cutoff: float) -> None:
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
        if len(self._hits) >= self._max_keys:
            # Still full of active keys: start again rather than grow without limit.
            self._hits.clear()


def client_address(request: Request) -> str:
    """The first `X-Forwarded-For` hop when present, else the peer address."""
    first_hop = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if first_hop:
        return first_hop[:64]
    return request.client.host if request.client else "unknown"


def token_matches(provided: str | None, expected: str | None) -> bool:
    """Constant-time comparison. No token configured means no request is let in."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def readiness_problems(settings: Settings) -> list[str]:
    """What stops the service from scoring, by name only. Makes no model call."""
    problems: list[str] = []
    try:
        load_all_rubrics(settings)
    except RubricError:
        problems.append("rubrics")
    try:
        load_prompt(settings)
    except PromptError:
        problems.append("prompt")
    try:
        load_prices(settings)
    except PricesError:
        problems.append("prices")
    required = {
        "FOUNDRY_ENDPOINT": settings.foundry_endpoint,
        "DEMO_TOKEN": settings.demo_token,
        "ANSWER_HASH_SALT": settings.answer_hash_salt,
    }
    problems.extend(name for name, value in required.items() if not value)
    return problems


def error_response(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    """An error body with a code and a fixed message. It never repeats the input."""
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status, headers=headers
    )


async def read_body(request: Request) -> bytes | None:
    """The request body, or None when it is larger than the limit."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return None
    return bytes(body)


def load_page() -> tuple[str, str]:
    """The demo page and a content security policy that allows only its own inline blocks."""
    html = UI_PAGE.read_text(encoding="utf-8").replace("\r\n", "\n")
    sources: dict[str, list[str]] = {"script": [], "style": []}
    for kind, text in _INLINE_BLOCK.findall(html):
        digest = base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")
        sources[kind].append(f"'sha256-{digest}'")
    policy = "; ".join(
        [
            "default-src 'none'",
            f"script-src {' '.join(sources['script']) or "'none'"}",
            f"style-src {' '.join(sources['style']) or "'none'"}",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )
    return html, policy


def create_app(
    settings: Settings | None = None,
    model_client: ModelClient | None = None,
    *,
    tracer_provider: trace.TracerProvider | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Build the app. The model client is created once here, or injected by tests."""
    settings = settings or Settings.from_env()
    telemetry_on = configure_telemetry(settings)
    tracer = get_tracer(tracer_provider)
    limiter = rate_limiter or RateLimiter()
    page, page_policy = load_page()
    if model_client is None and settings.foundry_endpoint:
        model_client = build_model_client(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        warm = getattr(model_client, "warm", None)
        warming = asyncio.create_task(_warm(warm)) if callable(warm) else None
        yield
        if warming is not None:
            warming.cancel()
            with suppress(asyncio.CancelledError):
                await warming
        flush_telemetry()

    app = FastAPI(
        title="Answer scorer",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.model_client = model_client

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        problems = readiness_problems(settings)
        if problems:
            return JSONResponse({"status": "not_ready", "problems": problems}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(
            page,
            headers={
                "Content-Security-Policy": page_policy,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/score")
    async def score(request: Request) -> JSONResponse:
        if not limiter.allow(client_address(request)):
            return error_response(
                429,
                "rate_limited",
                "Too many requests. Try again in a minute.",
                {"Retry-After": str(int(limiter.window_seconds))},
            )
        if not token_matches(request.headers.get(DEMO_TOKEN_HEADER), settings.demo_token):
            return error_response(401, "unauthorised", "A valid demo token is required.")

        body = await read_body(request)
        try:
            if body is None:
                raise ValueError("the body is too large")
            payload = ScoreRequest.model_validate_json(body)
        except ValueError:
            # A validation error quotes the input, so nothing from it is returned or logged.
            return error_response(400, "invalid_request", "The request body is not valid.")

        # The exception is handled here, never recorded on the span: its text is not metadata.
        with tracer.start_as_current_span(
            SCORE_SPAN_NAME, record_exception=False, set_status_on_exception=False
        ) as span:
            trace_id = trace_id_of(span)
            try:
                if model_client is None:
                    raise ModelUnavailableError("no model client is configured")
                outcome = await score_answer(payload, client=model_client, settings=settings)
                span.set_attributes(score_span_attributes(outcome, settings))
            except ScoringError as error:
                # The caller's input was not scorable: not a fault of the service.
                return error_response(error.status, error.code, error.message)
            except ModelUnavailableError:
                span.set_status(Status(StatusCode.ERROR, "model_unavailable"))
                return error_response(
                    503, "model_unavailable", "The model is unavailable. No score was produced."
                )
            except Exception as error:
                span.set_status(Status(StatusCode.ERROR, "internal_error"))
                logger.error("score request stopped: %s", type(error).__name__)
                return error_response(
                    500, "internal_error", "The request could not be completed. No score."
                )
            response = outcome.response.model_copy(update={"trace_id": trace_id})
        return JSONResponse(response.model_dump(mode="json"), headers={"Cache-Control": "no-store"})

    if telemetry_on:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Health probes and the per-message ASGI spans would only add rows to pay for.
        FastAPIInstrumentor.instrument_app(
            app, excluded_urls=UNPROBED_URLS, exclude_spans=["receive", "send"]
        )
    return app


async def _warm(warm: Callable[[], object]) -> None:
    """Fetch the first access token in the background, so the first score is not slower."""
    try:
        await warm()
    except Exception as error:
        logger.warning("token warm-up did not complete: %s", type(error).__name__)


app = create_app()
