"""Coverage for app/services/onboarding.py — token round-trip + email builders."""
from types import SimpleNamespace

import pytest

import app.services.onboarding as onboarding
from app.config import settings


def test_token_round_trip_verify():
    token = onboarding.create_token("verify", "ten_abc", ttl_seconds=3600)
    assert onboarding.verify_token(token, expected_purpose="verify") == "ten_abc"


def test_verify_token_malformed():
    with pytest.raises(onboarding.InvalidOnboardingToken):
        onboarding.verify_token("nodot", expected_purpose="verify")


def test_verify_token_bad_signature():
    token = onboarding.create_token("verify", "ten_abc", ttl_seconds=3600)
    part, _sig = token.split(".", 1)
    with pytest.raises(onboarding.InvalidOnboardingToken):
        onboarding.verify_token(f"{part}.tampered", expected_purpose="verify")


def test_verify_token_wrong_purpose():
    token = onboarding.create_token("verify", "ten_abc", ttl_seconds=3600)
    with pytest.raises(onboarding.InvalidOnboardingToken):
        onboarding.verify_token(token, expected_purpose="recover")


def test_verify_token_expired():
    token = onboarding.create_token("verify", "ten_abc", ttl_seconds=-1)
    with pytest.raises(onboarding.InvalidOnboardingToken):
        onboarding.verify_token(token, expected_purpose="verify")


def test_url_builders():
    assert onboarding.verify_url("tok").endswith("/verify?t=tok")
    assert onboarding.recover_url("tok").endswith("/recover?t=tok")
    assert onboarding._dashboard_origin().startswith("http")


def test_send_skips_without_resend_key(monkeypatch):
    """_send is a no-op (no httpx call) when RESEND_API_KEY is unset."""
    import asyncio

    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    # No network: should return quietly even with a bogus client patched in
    asyncio.run(onboarding._send("to@x.io", "subj", "<p>hi</p>"))


def test_send_welcome_email_invokes_send(monkeypatch):
    import asyncio

    captured = {}

    async def fake_send(to, subject, html):
        captured["to"] = to
        captured["subject"] = subject
        captured["html"] = html

    monkeypatch.setattr(onboarding, "_send", fake_send)
    tenant = SimpleNamespace(id="ten_abc", name="Chris", email="chris@acme.io")
    asyncio.run(onboarding.send_welcome_email(tenant, "sk_live_supersecretkey123456"))
    assert captured["to"] == "chris@acme.io"
    assert "verify" in captured["subject"].lower()
    assert "Verify email" in captured["html"]


def test_send_recovery_email_invokes_send(monkeypatch):
    import asyncio

    captured = {}

    async def fake_send(to, subject, html):
        captured["to"] = to
        captured["subject"] = subject

    monkeypatch.setattr(onboarding, "_send", fake_send)
    tenant = SimpleNamespace(id="ten_abc", name="Chris", email="chris@acme.io")
    asyncio.run(onboarding.send_recovery_email(tenant))
    assert captured["to"] == "chris@acme.io"
    assert "recover" in captured["subject"].lower()


def test_send_makes_http_call_with_key(monkeypatch):
    """When RESEND_API_KEY is set, _send POSTs to Resend (mocked httpx)."""
    import asyncio

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    posted = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            posted["url"] = url
            posted["json"] = json
            return FakeResponse()

    monkeypatch.setattr(onboarding.httpx, "AsyncClient", FakeClient)
    asyncio.run(onboarding._send("to@x.io", "subj", "<p>hi</p>"))
    assert posted["url"] == "https://api.resend.com/emails"
    assert posted["json"]["to"] == ["to@x.io"]
