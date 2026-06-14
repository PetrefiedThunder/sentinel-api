"""RFC 3161 trusted timestamping for audit events.

Submits an audit event hash to a configured Time Stamping Authority (TSA)
and persists the TSA-attested genTime to ``audit_events.tsa_timestamp``.
This anchors the tamper-evident hash chain (see app/services/audit_log.py)
to an independent, cryptographically signed clock: a tenant — or we — can
later prove an event existed no later than the attested time.

Configuration: set ``TSA_URL`` (e.g. https://freetsa.org/tsr or a DigiCert
TSA endpoint). When unset (the default), every entry point here is a no-op
so existing flows are unaffected.

Schema note: migration 009 created ``tsa_timestamp`` as a DateTime, so only
the attested time is persisted. The raw DER TimeStampToken is returned to
the caller; ``verify_timestamp_token`` checks a token (held by the caller /
exported for compliance) against an event hash. Persisting the token blob
itself requires a follow-up binary column.

Verification scope: ``verify_timestamp_token`` validates token structure and
that the messageImprint matches SHA-256(event_hash). It does NOT validate
the TSA's X.509 signature chain — that requires the ``cryptography`` package
and a trust store, and is out of scope here.
"""

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime

import httpx
import structlog
from asn1crypto import algos, cms, core, tsp

from app.config import settings

logger = structlog.get_logger(__name__)

_REQUEST_TIMEOUT_SECONDS = 10.0
# PKIStatus values meaning the token was granted (RFC 3161 §2.4.2).
_GRANTED_STATUSES = {0, 1}  # granted, grantedWithMods


class TSAError(Exception):
    """The TSA request failed or returned an unusable response."""


@dataclass(frozen=True)
class TimestampResult:
    """Outcome of a successful TSA round-trip."""

    token: bytes  # DER-encoded TimeStampToken (CMS ContentInfo)
    gen_time: datetime  # TSA-attested time (TSTInfo.genTime)


def _build_timestamp_request(event_hash: str, nonce: int) -> bytes:
    """DER-encode an RFC 3161 TimeStampReq for SHA-256(event_hash)."""
    imprint = hashlib.sha256(event_hash.encode()).digest()
    req = tsp.TimeStampReq(
        {
            "version": "v1",
            "message_imprint": tsp.MessageImprint(
                {
                    "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
                    "hashed_message": imprint,
                }
            ),
            "nonce": core.Integer(nonce),
            "cert_req": True,
        }
    )
    return req.dump()


def _extract_tst_info(token_der: bytes) -> tsp.TSTInfo:
    """Parse a DER TimeStampToken (CMS ContentInfo) down to its TSTInfo."""
    try:
        content_info = cms.ContentInfo.load(token_der)
        signed_data = content_info["content"]
        tst_info = signed_data["encap_content_info"]["content"].parsed
        if not isinstance(tst_info, tsp.TSTInfo):
            tst_info = tsp.TSTInfo.load(bytes(tst_info))
        return tst_info
    except (ValueError, KeyError, TypeError) as exc:
        raise TSAError(f"Malformed timestamp token: {exc}") from exc


async def request_timestamp(event_hash: str) -> TimestampResult:
    """Submit ``event_hash`` to the configured TSA and return the token.

    Raises TSAError on transport failure, a non-granted PKIStatus, or a
    token whose messageImprint does not match the submitted hash.
    """
    if not settings.TSA_URL:
        raise TSAError("TSA_URL is not configured")

    nonce = int.from_bytes(os.urandom(8), "big")
    request_der = _build_timestamp_request(event_hash, nonce)

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                settings.TSA_URL,
                content=request_der,
                headers={"Content-Type": "application/timestamp-query"},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TSAError(f"TSA request failed: {exc}") from exc

    try:
        ts_resp = tsp.TimeStampResp.load(response.content)
        status = ts_resp["status"]["status"].native
    except (ValueError, KeyError) as exc:
        raise TSAError(f"Malformed TSA response: {exc}") from exc

    if status not in ("granted", "granted_with_mods"):
        raise TSAError(f"TSA rejected request: status={status}")

    # asn1crypto marks time_stamp_token as required even though RFC 3161
    # makes it OPTIONAL, so a granted-but-tokenless response raises here.
    try:
        token = ts_resp["time_stamp_token"]
        token_der = token.dump() if not isinstance(token, core.Void) else b""
    except (ValueError, KeyError) as exc:
        raise TSAError(f"TSA response granted but contained no token: {exc}") from exc
    if not token_der:
        raise TSAError("TSA response granted but contained no token")

    if not verify_timestamp_token(token_der, event_hash):
        raise TSAError("TSA token messageImprint does not match submitted hash")

    tst_info = _extract_tst_info(token_der)
    gen_time = tst_info["gen_time"].native.replace(tzinfo=None)
    return TimestampResult(token=token_der, gen_time=gen_time)


def verify_timestamp_token(token_der: bytes, event_hash: str) -> bool:
    """Check that a stored DER TimeStampToken attests to ``event_hash``.

    Returns True when the token parses and its messageImprint equals
    SHA-256(event_hash). See module docstring for verification scope.
    """
    try:
        tst_info = _extract_tst_info(token_der)
    except TSAError:
        return False
    imprint = tst_info["message_imprint"]
    if imprint["hash_algorithm"]["algorithm"].native != "sha256":
        return False
    expected = hashlib.sha256(event_hash.encode()).digest()
    return bytes(imprint["hashed_message"]) == expected


async def timestamp_audit_event(db, event) -> TimestampResult | None:
    """Timestamp ``event.event_hash`` via the TSA and persist the genTime.

    No-op (returns None) when TSA_URL is unset. Persists the attested time
    to ``event.tsa_timestamp`` and returns the full result, including the
    DER token, to the caller.
    """
    if not settings.TSA_URL:
        return None

    result = await request_timestamp(event.event_hash)
    event.tsa_timestamp = result.gen_time
    db.add(event)
    await db.commit()
    await db.refresh(event)
    logger.info(
        "audit_event_timestamped",
        event_id=event.id,
        tsa_timestamp=result.gen_time.isoformat(),
    )
    return result
