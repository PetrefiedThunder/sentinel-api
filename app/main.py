from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import approvals, audit, tenants, webhooks

app = FastAPI(title="Sentinel API", version="0.1.0")

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
app.include_router(audit.router, prefix="/v1/audit-events", tags=["audit"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/_debug/slack")
async def _debug_slack():
    import httpx
    from app.config import settings as s
    token = s.SLACK_BOT_TOKEN
    channel = s.SLACK_CHANNEL
    if not token:
        return {"error": "no token", "channel_env": channel}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                json={"channel": channel or "C0AK369AEUE", "text": "[debug] direct from /_debug/slack"},
            )
        return {"status": r.status_code, "body": r.text[:500], "channel": channel, "code_version": "debug-v2"}
    except Exception as e:
        return {"exception": f"{type(e).__name__}: {e}", "channel": channel}


@app.get("/health")
async def health():
    return {"status": "ok"}
