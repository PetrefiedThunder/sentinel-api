"""Coverage for app/services/decision_bus.py — in-process waiter registry.

We never connect to Postgres; we exercise wait_for / _on_notify / notify_decision
against the in-memory event registry and a fake DB.
"""
import asyncio

import app.services.decision_bus as dbus
from app.services.decision_bus import DecisionBus


def test_dsn_conversion(monkeypatch):
    monkeypatch.setattr(
        dbus.settings, "DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/db"
    )
    assert dbus._asyncpg_dsn() == "postgresql://u:p@h:5432/db"


def test_wait_for_times_out_without_notify():
    bus = DecisionBus()

    async def scenario():
        return await bus.wait_for("act_1", timeout=0.05)

    assert asyncio.run(scenario()) is False
    # waiter cleaned up after timeout
    assert "act_1" not in bus._waiters


def test_notify_wakes_waiter():
    bus = DecisionBus()

    async def scenario():
        async def fire_later():
            await asyncio.sleep(0.01)
            bus._on_notify(None, 0, dbus.CHANNEL, "act_1")

        task = asyncio.create_task(fire_later())
        got = await bus.wait_for("act_1", timeout=1.0)
        await task
        return got

    assert asyncio.run(scenario()) is True


def test_on_notify_ignores_empty_payload():
    bus = DecisionBus()
    # no waiters / empty payload — must not raise
    bus._on_notify(None, 0, dbus.CHANNEL, "")
    bus._on_notify(None, 0, dbus.CHANNEL, None)
    bus._on_notify(None, 0, dbus.CHANNEL, "act_unknown")


def test_start_degrades_gracefully_on_connect_failure(monkeypatch):
    bus = DecisionBus()

    async def boom(*a, **k):
        raise OSError("no postgres")

    monkeypatch.setattr(dbus.asyncpg, "connect", boom)

    async def scenario():
        await bus.start()

    asyncio.run(scenario())
    # start failed silently → not marked started
    assert bus._started is False


def test_stop_is_safe_when_never_started():
    bus = DecisionBus()
    asyncio.run(bus.stop())
    assert bus._started is False


def test_notify_decision_best_effort_swallow():
    """notify_decision swallows DB errors (best-effort)."""

    class FakeDB:
        async def execute(self, *a, **k):
            raise RuntimeError("boom")

        async def commit(self):
            pass

    async def scenario():
        await dbus.notify_decision(FakeDB(), "act_1")

    # should not raise
    asyncio.run(scenario())


def test_notify_decision_happy_path():
    calls = {}

    class FakeDB:
        async def execute(self, stmt, params):
            calls["params"] = params

        async def commit(self):
            calls["committed"] = True

    async def scenario():
        await dbus.notify_decision(FakeDB(), "act_42")

    asyncio.run(scenario())
    assert calls["params"]["p"] == "act_42"
    assert calls["committed"] is True
