"""Onboarding emails — welcome, verify, recover.

Uses the same HMAC-signed token primitive as approval magic links
(see approval_tokens.py) so we share the same JWT_SECRET infra.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

import httpx

from app.config import settings
from app.services.approval_tokens import _require_strong_signing_secret

log = logging.getLogger(__name__)


# ── HMAC token (purpose-scoped) ──────────────────────────────────────
def _sign(payload_part: str) -> str:
    _require_strong_signing_secret()
    digest = hmac.new(
        settings.JWT_SECRET.encode(),
        payload_part.encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class InvalidOnboardingToken(ValueError):
    pass


def create_token(purpose: str, subject: str, ttl_seconds: int) -> str:
    """Signed token: base64(json({purpose, sub, exp})) + '.' + sig."""
    payload = {
        "p": purpose,           # "verify" | "recover"
        "sub": subject,         # tenant.id
        "exp": int(time.time()) + int(ttl_seconds),
    }
    payload_part = _b64e(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    return f"{payload_part}.{_sign(payload_part)}"


def verify_token(token: str, expected_purpose: str) -> str:
    """Return subject (tenant_id) if the token is valid for `expected_purpose`."""
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError as e:
        raise InvalidOnboardingToken("Malformed token") from e
    if not hmac.compare_digest(_sign(payload_part), signature_part):
        raise InvalidOnboardingToken("Invalid signature")
    try:
        payload = json.loads(_b64d(payload_part))
    except (ValueError, TypeError) as e:
        raise InvalidOnboardingToken("Malformed payload") from e
    if payload.get("p") != expected_purpose:
        raise InvalidOnboardingToken("Wrong purpose")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise InvalidOnboardingToken("Expired")
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise InvalidOnboardingToken("Missing subject")
    return sub


# ── URL builders ─────────────────────────────────────────────────────
def _dashboard_origin() -> str:
    return (settings.PUBLIC_APP_URL or "https://app.pauseapi.app").rstrip("/")


def verify_url(token: str) -> str:
    return f"{_dashboard_origin()}/verify?t={token}"


def recover_url(token: str) -> str:
    return f"{_dashboard_origin()}/recover?t={token}"


# ── Resend send wrapper ──────────────────────────────────────────────
async def _send(to: str, subject: str, html: str) -> None:
    api_key = settings.RESEND_API_KEY
    if not api_key:
        log.warning("RESEND_API_KEY not set — skipping onboarding email to %s", to)
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": settings.EMAIL_FROM or "Sentinel <approvals@pauseapi.app>",
                    "reply_to": settings.EMAIL_REPLY_TO or "support@regengine.co",
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            if r.status_code >= 400:
                log.warning("Resend onboarding send failed: %s %s", r.status_code, r.text[:200])
    except Exception as e:
        # best-effort — never crash the signup
        log.exception("Onboarding email send error: %s", e)


# ── Welcome + verify ─────────────────────────────────────────────────
async def send_welcome_email(tenant, api_key: str) -> None:
    """Single email containing: API key reminder + verify link + demo snippet."""
    token = create_token("verify", tenant.id, ttl_seconds=60 * 60 * 24 * 7)  # 7 days
    link = verify_url(token)
    key_preview = f"{api_key[:14]}…{api_key[-6:]}"

    snippet = f"""from sentinel import configure, oversight

configure(api_key=\"{api_key}\")

@oversight(risk_level=\"high\", approvers=[\"{tenant.email}\"])
def wire_transfer(amount, recipient):
    return {{\"ok\": True}}

wire_transfer(50_000, \"acct_xyz\")"""

    html = f"""
    <h2>Welcome to Sentinel</h2>
    <p>Hi {tenant.name},</p>
    <p>Your workspace is live. Your API key was issued during signup
       (preview: <code>{key_preview}</code>) — keep it safe; we don't store
       it in plaintext on our end.</p>

    <h3>Verify your email</h3>
    <p>Click below within 7 days to mark your email verified. This unlocks
       branded sender domains and access to paid plans.</p>
    <p>
      <a href="{link}"
         style="display:inline-block;background:#0a0a0a;color:#fff;
                padding:10px 16px;border-radius:6px;text-decoration:none;
                font-family:system-ui,sans-serif;font-weight:600;">
        Verify email →
      </a>
    </p>

    <h3>2-minute test</h3>
    <pre style="background:#f5f5f5;padding:12px;border-radius:6px;
                font-family:Menlo,Consolas,monospace;font-size:13px;
                overflow-x:auto;line-height:1.5;">{snippet}</pre>

    <p>
      <a href="https://github.com/PetrefiedThunder/sentinel-examples">Examples repo</a>
      &middot;
      <a href="https://github.com/PetrefiedThunder/sentinel-sdk#readme">SDK docs</a>
      &middot;
      <a href="https://app.pauseapi.app">Dashboard</a>
    </p>

    <p style="color:#888;font-size:12px;margin-top:24px;">
      — RegEngine, Inc. &middot;
      <a href="https://pauseapi.app/privacy">Privacy</a> &middot;
      <a href="https://pauseapi.app/terms">Terms</a>
    </p>
    """
    await _send(tenant.email, "Welcome to Sentinel — verify your email", html)


# ── Recovery email (rotate API key) ──────────────────────────────────
async def send_recovery_email(tenant) -> None:
    token = create_token("recover", tenant.id, ttl_seconds=60 * 30)  # 30 min
    link = recover_url(token)
    html = f"""
    <h2>Rotate your Sentinel API key</h2>
    <p>Someone (hopefully you) asked us to issue a fresh API key for the
       Sentinel workspace registered to this email.</p>
    <p>
      <a href="{link}"
         style="display:inline-block;background:#0a0a0a;color:#fff;
                padding:10px 16px;border-radius:6px;text-decoration:none;
                font-family:system-ui,sans-serif;font-weight:600;">
        Issue new API key →
      </a>
    </p>
    <p>Clicking the link will <b>revoke any existing API keys</b> on this
       workspace and show you a new one. The link expires in 30 minutes.</p>
    <p>If this wasn't you, ignore this email and nothing changes.</p>
    <p style="color:#888;font-size:12px;margin-top:24px;">
      — RegEngine, Inc.
    </p>
    """
    await _send(tenant.email, "Recover your Sentinel API key", html)
