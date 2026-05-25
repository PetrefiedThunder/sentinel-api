from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import approver_contacts, approvals, audit, tenants, twilio_webhooks
from app.services.decision_bus import bus


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bus.start()
    try:
        yield
    finally:
        await bus.stop()


app = FastAPI(title="Sentinel API", version="0.1.0", lifespan=lifespan)

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


@app.get("/health")
async def health():
    return {"status": "ok", "bus": bus._started}
