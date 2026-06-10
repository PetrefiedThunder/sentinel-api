"""Regression: dispatch_approval_webhook must hold strong references to its
delivery tasks — the event loop only keeps weak refs, so an untracked
fire-and-forget task can be garbage-collected mid-delivery."""
import asyncio
from datetime import UTC, datetime

from test_support import TENANT_ID, make_sqlite_session, run

from app.models import Approval, WebhookEndpoint
from app.services import webhooks


def _approval(decision="approved"):
    return Approval(
        id="act_wh",
        tenant_id=TENANT_ID,
        function_name="transfer_funds",
        arguments={},
        risk_level="high",
        approvers=[],
        timeout_seconds=300,
        decision=decision,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


def test_dispatch_tracks_delivery_tasks_until_done(monkeypatch):
    async def main():
        engine, session, _ = await make_sqlite_session()
        session.add(
            WebhookEndpoint(
                tenant_id=TENANT_ID, url="https://example.com/hook", secret="whsec_x"
            )
        )
        await session.commit()

        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_deliver(endpoint, event_type, approval):
            started.set()
            await release.wait()

        monkeypatch.setattr(webhooks, "_deliver_with_retries", fake_deliver)

        await webhooks.dispatch_approval_webhook(session, _approval())
        await started.wait()
        assert len(webhooks._inflight) == 1

        release.set()
        await asyncio.gather(*webhooks._inflight)
        await asyncio.sleep(0)
        assert len(webhooks._inflight) == 0
        await session.close()
        await engine.dispose()

    run(main())


def test_dispatch_logs_crashed_delivery_tasks(monkeypatch, caplog):
    async def main():
        engine, session, _ = await make_sqlite_session()
        session.add(
            WebhookEndpoint(
                tenant_id=TENANT_ID, url="https://example.com/hook", secret="whsec_x"
            )
        )
        await session.commit()

        async def fake_deliver(endpoint, event_type, approval):
            raise RuntimeError("boom")

        monkeypatch.setattr(webhooks, "_deliver_with_retries", fake_deliver)

        await webhooks.dispatch_approval_webhook(session, _approval())
        await asyncio.gather(*webhooks._inflight, return_exceptions=True)
        await asyncio.sleep(0)
        assert len(webhooks._inflight) == 0
        assert any(
            "webhook delivery task crashed" in r.message for r in caplog.records
        )
        await session.close()
        await engine.dispose()

    run(main())


def test_dispatch_skips_pending_decisions():
    async def main():
        engine, session, _ = await make_sqlite_session()
        await webhooks.dispatch_approval_webhook(session, _approval(decision="pending"))
        assert len(webhooks._inflight) == 0
        await session.close()
        await engine.dispose()

    run(main())
