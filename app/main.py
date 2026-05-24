from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import approvals, audit, tenants, webhooks

app = FastAPI(title="Sentinel API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://oversight.sh",
        "https://app.oversight.sh",
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(tenants.router, prefix="/v1/tenants", tags=["tenants"])
app.include_router(approvals.router, prefix="/v1/approvals", tags=["approvals"])
app.include_router(audit.router, prefix="/v1/audit-events", tags=["audit"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
async def health():
    return {"status": "ok"}
