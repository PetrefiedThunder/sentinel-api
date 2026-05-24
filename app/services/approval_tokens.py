import base64
import hashlib
import hmac
import json
import time

from app.config import settings

VALID_DECISIONS = {"approved", "rejected"}
WEAK_SIGNING_SECRETS = {
    "",
    "change-me",
    "dev-only-replace",
    "replace-with-rs256-key",
    "replace-with-32-byte-random-secret",
}


class InvalidApprovalToken(ValueError):
    pass


def create_decision_token(
    action_id: str,
    decision: str,
    expires_in_seconds: int,
    now: int | None = None,
) -> str:
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be 'approved' or 'rejected'")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "action_id": action_id,
        "decision": decision,
        "exp": issued_at + expires_in_seconds,
    }
    payload_part = _base64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    signature_part = _sign(payload_part)
    return f"{payload_part}.{signature_part}"


def verify_decision_token(
    token: str,
    action_id: str,
    now: int | None = None,
) -> str:
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError as exc:
        raise InvalidApprovalToken("Malformed approval token") from exc

    expected_signature = _sign(payload_part)
    if not hmac.compare_digest(expected_signature, signature_part):
        raise InvalidApprovalToken("Invalid approval token signature")

    try:
        payload = json.loads(_base64url_decode(payload_part))
    except (ValueError, TypeError) as exc:
        raise InvalidApprovalToken("Malformed approval token payload") from exc

    if payload.get("action_id") != action_id:
        raise InvalidApprovalToken("Approval token action mismatch")
    decision = payload.get("decision")
    if decision not in VALID_DECISIONS:
        raise InvalidApprovalToken("Invalid approval token decision")
    current_time = int(time.time() if now is None else now)
    if int(payload.get("exp", 0)) < current_time:
        raise InvalidApprovalToken("Approval token expired")
    return decision


def _sign(payload_part: str) -> str:
    _require_strong_signing_secret()
    digest = hmac.new(
        settings.JWT_SECRET.encode(),
        payload_part.encode(),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(digest)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _require_strong_signing_secret() -> None:
    secret = settings.JWT_SECRET
    if secret in WEAK_SIGNING_SECRETS or len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be a strong random value for approval links")
