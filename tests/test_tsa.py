"""RFC 3161 TSA integration tests. All TSA HTTP calls are mocked — no network."""

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from asn1crypto import algos, cms, core, tsp
from test_support import TENANT_ID, make_sqlite_session, run

from app.config import settings
from app.services import tsa
from app.services.audit_log import append_audit_event
from app.services.tsa import (
    TSAError,
    request_timestamp,
    timestamp_audit_event,
    verify_timestamp_token,
)

GEN_TIME = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)


def make_token(event_hash: str, gen_time: datetime = GEN_TIME) -> bytes:
    """Build a minimal DER TimeStampToken (CMS SignedData wrapping TSTInfo)."""
    tst = tsp.TSTInfo(
        {
            "version": "v1",
            "policy": "1.2.3.4.1",
            "message_imprint": tsp.MessageImprint(
                {
                    "hash_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
                    "hashed_message": hashlib.sha256(event_hash.encode()).digest(),
                }
            ),
            "serial_number": 12345,
            "gen_time": gen_time,
        }
    )
    signed_data = cms.SignedData(
        {
            "version": "v3",
            "digest_algorithms": [algos.DigestAlgorithm({"algorithm": "sha256"})],
            "encap_content_info": cms.EncapsulatedContentInfo(
                {
                    "content_type": "tst_info",
                    "content": core.ParsableOctetString(tst.dump()),
                }
            ),
            "signer_infos": cms.SignerInfos([]),
        }
    )
    return cms.ContentInfo({"content_type": "signed_data", "content": signed_data}).dump()


def make_response(event_hash: str, status: str = "granted") -> bytes:
    """Build a DER TimeStampResp containing a token for event_hash."""
    return tsp.TimeStampResp(
        {
            "status": tsp.PKIStatusInfo({"status": status}),
            "time_stamp_token": cms.ContentInfo.load(make_token(event_hash)),
        }
    ).dump()


class MockAsyncClient:
    """Stand-in for httpx.AsyncClient returning a canned TSA response."""

    def __init__(self, response_body: bytes, status_code: int = 200):
        self._body = response_body
        self._status_code = status_code

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, content=None, headers=None):
        request = httpx.Request("POST", url)
        return httpx.Response(self._status_code, content=self._body, request=request)


def test_timestamp_audit_event_noop_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "TSA_URL", "")

    def explode(*args, **kwargs):
        raise AssertionError("HTTP client must not be used when TSA_URL is unset")

    monkeypatch.setattr(tsa.httpx, "AsyncClient", explode)

    engine, session, tenant = run(make_sqlite_session())
    try:
        event = run(append_audit_event(session, TENANT_ID, None, "decision:approved"))
        result = run(timestamp_audit_event(session, event))
        assert result is None
        assert event.tsa_timestamp is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_timestamp_audit_event_persists_gen_time(monkeypatch):
    monkeypatch.setattr(settings, "TSA_URL", "https://tsa.example.com/tsr")

    engine, session, tenant = run(make_sqlite_session())
    try:
        event = run(append_audit_event(session, TENANT_ID, None, "decision:approved"))
        monkeypatch.setattr(
            tsa.httpx, "AsyncClient", MockAsyncClient(make_response(event.event_hash))
        )

        result = run(timestamp_audit_event(session, event))

        assert result is not None
        assert event.tsa_timestamp == GEN_TIME.replace(tzinfo=None)
        assert verify_timestamp_token(result.token, event.event_hash)
    finally:
        run(session.close())
        run(engine.dispose())


def test_request_timestamp_rejects_non_granted_status(monkeypatch):
    monkeypatch.setattr(settings, "TSA_URL", "https://tsa.example.com/tsr")
    body = tsp.TimeStampResp(
        {
            "status": tsp.PKIStatusInfo({"status": "rejection"}),
            # asn1crypto requires the field; a rejection still must not be accepted.
            "time_stamp_token": cms.ContentInfo.load(make_token("irrelevant")),
        }
    ).dump()
    monkeypatch.setattr(tsa.httpx, "AsyncClient", MockAsyncClient(body))

    with pytest.raises(TSAError, match="rejection"):
        run(request_timestamp("somehash"))


def test_request_timestamp_rejects_imprint_mismatch(monkeypatch):
    monkeypatch.setattr(settings, "TSA_URL", "https://tsa.example.com/tsr")
    # Token attests to a different hash than the one submitted.
    monkeypatch.setattr(tsa.httpx, "AsyncClient", MockAsyncClient(make_response("otherhash")))

    with pytest.raises(TSAError, match="messageImprint"):
        run(request_timestamp("somehash"))


def test_request_timestamp_http_error(monkeypatch):
    monkeypatch.setattr(settings, "TSA_URL", "https://tsa.example.com/tsr")
    monkeypatch.setattr(tsa.httpx, "AsyncClient", MockAsyncClient(b"", status_code=503))

    with pytest.raises(TSAError, match="request failed"):
        run(request_timestamp("somehash"))


def test_verify_timestamp_token():
    token = make_token("somehash")
    assert verify_timestamp_token(token, "somehash") is True
    assert verify_timestamp_token(token, "tampered") is False
    assert verify_timestamp_token(b"not-a-der-token", "somehash") is False


def test_emit_endpoint_unaffected_when_tsa_disabled(monkeypatch):
    """Existing audit emit flow stays intact with TSA off (the default)."""
    from test_support import client_for

    from app.models import Approval

    monkeypatch.setattr(settings, "TSA_URL", "")
    engine, session, tenant = run(make_sqlite_session())
    try:

        async def _mk_approval():
            approval = Approval(tenant_id=TENANT_ID, function_name="test", arguments={})
            session.add(approval)
            await session.commit()
            await session.refresh(approval)
            return approval

        approval = run(_mk_approval())
        with client_for(session, tenant) as client:
            response = client.post(
                "/v1/audit-events",
                json={"action_id": approval.id, "execution_result": "success"},
            )
        assert response.status_code == 200
        assert response.json()["tsa_timestamp"] is None
    finally:
        run(session.close())
        run(engine.dispose())
