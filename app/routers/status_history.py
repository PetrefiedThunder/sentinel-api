"""Status-page uptime history — probe ingest + public daily aggregates.

POST /probe is gated by the admin bearer token (the external prober is
trusted infrastructure, not a tenant). GET /history is public so the
/status page can render real 30/90-day uptime without auth.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import UptimeProbe
from app.routers.admin import _check_admin

router = APIRouter()


class ProbeIn(BaseModel):
    region: str
    target: str
    ok: bool
    status_code: Optional[int] = None
    latency_ms: Optional[int] = None


@router.post("/probe", dependencies=[Depends(_check_admin)], include_in_schema=False)
async def ingest_probe(body: ProbeIn, db: AsyncSession = Depends(get_db)) -> dict:
    db.add(
        UptimeProbe(
            region=body.region,
            target=body.target,
            ok=body.ok,
            status_code=body.status_code,
            latency_ms=body.latency_ms,
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/history")
async def history(
    days: int = Query(default=30, ge=1, le=92),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Daily uptime aggregates for the last `days` days, ascending by date.

    Aggregation happens in Python — probe volume is tiny (a few per minute
    at most) and this sidesteps SQLite/Postgres date-trunc dialect drift.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        await db.execute(select(UptimeProbe).where(UptimeProbe.created_at >= cutoff))
    ).scalars()

    buckets: dict[str, dict] = {}
    for probe in rows:
        day = probe.created_at.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(day, {"probes": 0, "ok": 0})
        bucket["probes"] += 1
        if probe.ok:
            bucket["ok"] += 1

    return [
        {
            "date": day,
            "probes": bucket["probes"],
            "ok": bucket["ok"],
            "uptime_pct": round(bucket["ok"] / bucket["probes"] * 100, 3),
        }
        for day, bucket in sorted(buckets.items())
    ]
