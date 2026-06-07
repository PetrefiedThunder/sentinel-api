from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_setup import RequestContextMiddleware, configure_logging
from app.routers import (
    admin,
    approver_contacts,
    approvals,
    audit,
    billing,
    tenants,
    twilio_webhooks,
    webhooks,
)
from app.services.decision_bus import bus

# Configure structured (JSON) logging first so anything below logs as JSON.
configure_logging(level="INFO")

# Initialize Sentry as early as possible so import-time errors are captured too.
if settings.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,  # never send phone/email/approval payloads
        max_breadcrumbs=50,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bus.start()
    try:
        yield
    finally:
        await bus.stop()


app = FastAPI(title="Sentinel API", version="0.1.0", lifespan=lifespan)

# Request context — stamps request_id + method + route on every log line,
# emits a structured "request.completed" record. Must be added BEFORE the
# CORS middleware so it wraps the inner handler chain.
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://pauseapi.app",
        "https://app.pauseapi.app",
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(tenants.router, prefix="/v1/tenants", tags=["tenants"])
app.include_router(approvals.router, prefix="/v1/approvals", tags=["approvals"])
app.include_router(approver_contacts.router, prefix="/v1/approver-contacts", tags=["approver-contacts"])
app.include_router(audit.router, prefix="/v1/audit-events", tags=["audit"])
app.include_router(twilio_webhooks.router)
app.include_router(webhooks.router, prefix="/v1/webhooks", tags=["webhooks"])
app.include_router(billing.router, prefix="/v1/billing", tags=["billing"])
app.include_router(admin.router, prefix="/v1", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "bus": bus._started}
