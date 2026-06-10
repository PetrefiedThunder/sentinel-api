"""Structured (JSON) logging via structlog.

Configures structlog to render every log line as a single JSON object
with timestamp, level, logger, event, plus any bound context (request_id,
tenant_id, route, etc.). Wired into FastAPI's request lifecycle via
RequestContextMiddleware.

Why JSON: Railway's log search is grep over raw text. JSON lines let us
filter by `tenant_id` / `route` / `request_id` without false positives.
When we eventually ship logs to Datadog/Better Stack/etc, the JSON
fields become indexed dimensions for free.
"""
from __future__ import annotations

import logging
import secrets
import sys
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Per-request context that gets stamped onto every log line emitted during
# the request. set() in middleware, .get() inside structlog processor.
_request_ctx: ContextVar[dict[str, Any] | None] = ContextVar("_request_ctx", default=None)


def _inject_request_ctx(_, __, event_dict: dict) -> dict:
    """structlog processor: merge any active request context into the log."""
    ctx = _request_ctx.get() or {}
    for k, v in ctx.items():
        event_dict.setdefault(k, v)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Replace stdlib logging output with JSON structlog. Idempotent."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _inject_request_ctx,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper()) if isinstance(level, str) else level
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (FastAPI / uvicorn / SQLAlchemy) through structlog
    # so we get JSON for those too — otherwise we'd have two log formats.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Don't double up handlers if reload re-imports this module
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Quieter health-check noise from uvicorn access logs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamp every log line emitted during a request with request_id +
    method + route, and emit a structured access log on completion.

    Tenant_id is added downstream by the auth dependency when a request
    hits an authenticated route — see auth.get_current_tenant.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or secrets.token_hex(8)
        ctx = {
            "request_id": request_id,
            "method": request.method,
            "route": request.url.path,
        }
        token = _request_ctx.set(ctx)
        logger = structlog.get_logger("http")
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request.error")
            raise
        else:
            logger.info(
                "request.completed",
                status_code=response.status_code,
            )
            response.headers["X-Request-Id"] = request_id
            # Surface rate-limit context if the handler enforced a bucket
            rl = getattr(request.state, "rate_limit_headers", None)
            if isinstance(rl, dict):
                for k, v in rl.items():
                    response.headers[k] = v
            return response
        finally:
            _request_ctx.reset(token)


def bind_request_context(**fields: Any) -> None:
    """Call from anywhere inside a request handler to attach additional
    fields (tenant_id, action_id, etc.) to every subsequent log line in
    this request."""
    current = dict(_request_ctx.get() or {})
    current.update({k: v for k, v in fields.items() if v is not None})
    _request_ctx.set(current)


def get_logger(name: str = "sentinel") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
