"""Cursor-pagination correctness suite.

Exercises the shared keyset paginator (app/services/pagination.py) through all
three endpoints that expose it:

    GET /v1/approvals            (app/routers/approvals.py)
    GET /v1/audit-events         (app/routers/audit.py)
    GET /v1/webhooks/deliveries  (app/routers/webhooks.py)

All three order by (created_at DESC, id DESC) and return the envelope
{data, has_more, next_cursor} when `limit` or `cursor` is supplied. The
properties asserted here are paginator invariants, not endpoint-specific:

  * full cursor traversal returns every row exactly once (no dupes, no gaps)
  * `limit` is honored and next_cursor points at the correct next page
  * empty and single-page result sets behave correctly
  * ordering is stable and descending across page boundaries

Reuses the existing sqlite/TestClient harness from tests/test_support.py.
"""

from datetime import datetime, timedelta

from test_support import TENANT_ID, client_for, make_sqlite_session, run

from app.models import Approval, AuditEvent, WebhookDelivery, WebhookEndpoint

# Fixed reference time; rows are seeded at strictly decreasing created_at so the
# expected (created_at DESC, id DESC) order is unambiguous.
BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


# --------------------------------------------------------------------------- #
# Generic traversal helper
# --------------------------------------------------------------------------- #
def _traverse(client, path, *, limit, params=None):
    """Page through `path` with the given limit, following next_cursor until
    exhausted. Returns (all_ids_in_order, pages) where pages is the list of
    raw response bodies, one per request."""
    params = dict(params or {})
    ids = []
    pages = []
    cursor = None
    # Hard stop well above any row count we seed — guards against an infinite
    # loop if next_cursor ever fails to advance.
    for _ in range(1000):
        q = {"limit": limit, **params}
        if cursor is not None:
            q["cursor"] = cursor
        resp = client.get(path, params=q)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        pages.append(body)
        ids.extend(row["id"] for row in body["data"])
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        assert body["next_cursor"] is not None
        cursor = body["next_cursor"]
    else:  # pragma: no cover - only fires on a paginator bug
        raise AssertionError("traversal did not terminate; next_cursor not advancing")
    return ids, pages


def _assert_desc_by_created_then_id(rows):
    """rows: list of (created_at_str, id). Assert strictly descending in
    (created_at, id), i.e. the contract the paginator promises."""
    keys = [(r[0], r[1]) for r in rows]
    assert keys == sorted(keys, reverse=True), f"not sorted desc: {keys}"
    assert len(keys) == len(set(keys)), f"duplicate keys: {keys}"


# --------------------------------------------------------------------------- #
# Seed helpers (one per model)
# --------------------------------------------------------------------------- #
def _seed_approvals(session, n, *, start=0, decision="pending"):
    async def _seed():
        rows = []
        for i in range(start, start + n):
            rows.append(
                Approval(
                    id=f"act_{i:06d}",
                    tenant_id=TENANT_ID,
                    function_name="charge_card",
                    arguments={"amount": i},
                    decision=decision,
                    # decreasing created_at -> first row is newest
                    created_at=BASE_TIME - timedelta(seconds=i),
                )
            )
        session.add_all(rows)
        await session.commit()

    run(_seed())


def _seed_audit_events(session, n, *, start=0, action_id=None):
    async def _seed():
        rows = []
        for i in range(start, start + n):
            rows.append(
                AuditEvent(
                    id=f"evt_{i:06d}",
                    tenant_id=TENANT_ID,
                    action_id=action_id,
                    execution_result="decision:approved",
                    event_hash=f"hash_{i:06d}",  # non-nullable; value irrelevant here
                    created_at=BASE_TIME - timedelta(seconds=i),
                )
            )
        session.add_all(rows)
        await session.commit()

    run(_seed())


def _seed_webhook_deliveries(session, n, *, start=0, endpoint_id=None):
    async def _seed():
        ep_id = endpoint_id
        if ep_id is None:
            endpoint = WebhookEndpoint(
                id="whk_000001",
                tenant_id=TENANT_ID,
                url="https://example.com/hook",
                secret="whsec_test",
            )
            session.add(endpoint)
            await session.flush()
            ep_id = endpoint.id
        rows = []
        for i in range(start, start + n):
            rows.append(
                WebhookDelivery(
                    id=f"whd_{i:06d}",
                    endpoint_id=ep_id,
                    tenant_id=TENANT_ID,
                    event_type="approval.approved",
                    action_id=f"act_{i:06d}",
                    created_at=BASE_TIME - timedelta(seconds=i),
                )
            )
        session.add_all(rows)
        await session.commit()
        return ep_id

    return run(_seed())


# A small table-driven registry so the shared property tests run against every
# endpoint without copy-paste. Each entry: (path, seeder, extra_query_params).
ENDPOINTS = [
    ("/v1/approvals", lambda s, n: _seed_approvals(s, n), {}),
    ("/v1/audit-events", lambda s, n: _seed_audit_events(s, n), {}),
    ("/v1/webhooks/deliveries", lambda s, n: _seed_webhook_deliveries(s, n), {}),
]


# --------------------------------------------------------------------------- #
# Shared property tests (run for all three endpoints)
# --------------------------------------------------------------------------- #
def test_full_traversal_returns_every_row_exactly_once():
    for path, seed, params in ENDPOINTS:
        engine, session, tenant = run(make_sqlite_session())
        try:
            seed(session, 25)
            with client_for(session, tenant) as client:
                ids, pages = _traverse(client, path, limit=10, params=params)
            assert len(ids) == 25, f"{path}: expected 25 rows, got {len(ids)}"
            assert len(set(ids)) == 25, f"{path}: duplicate ids in traversal: {ids}"
            expected_ids = {_id_for(path, i) for i in range(25)}
            assert set(ids) == expected_ids, f"{path}: gap/extra rows"
            # 25 rows / limit 10 -> pages of 10, 10, 5
            assert [len(p["data"]) for p in pages] == [10, 10, 5], f"{path}"
        finally:
            run(session.close())
            run(engine.dispose())


def test_limit_is_honored_and_next_cursor_points_to_next_page():
    for path, seed, params in ENDPOINTS:
        engine, session, tenant = run(make_sqlite_session())
        try:
            seed(session, 30)
            with client_for(session, tenant) as client:
                first = client.get(path, params={"limit": 7, **params})
                assert first.status_code == 200, first.text
                fb = first.json()
                assert len(fb["data"]) == 7, f"{path}: limit not honored"
                assert fb["has_more"] is True, f"{path}"
                assert fb["next_cursor"] is not None, f"{path}"

                second = client.get(
                    path, params={"limit": 7, "cursor": fb["next_cursor"], **params}
                )
                assert second.status_code == 200, second.text
                sb = second.json()
                assert len(sb["data"]) == 7, f"{path}"

            first_ids = [r["id"] for r in fb["data"]]
            second_ids = [r["id"] for r in sb["data"]]
            # The page boundary must not overlap and must not skip a row.
            assert set(first_ids).isdisjoint(second_ids), f"{path}: overlap"
            # Newest-first ordering means page 2 starts at row index 7.
            assert second_ids[0] == _id_for(path, 7), f"{path}: wrong next page start"
        finally:
            run(session.close())
            run(engine.dispose())


def test_stable_descending_order_across_pages():
    for path, seed, params in ENDPOINTS:
        engine, session, tenant = run(make_sqlite_session())
        try:
            seed(session, 23)
            with client_for(session, tenant) as client:
                # Collect (created_at, id) across the full traversal.
                rows = []
                cursor = None
                for _ in range(1000):
                    q = {"limit": 5, **params}
                    if cursor is not None:
                        q["cursor"] = cursor
                    resp = client.get(path, params=q)
                    assert resp.status_code == 200, resp.text
                    body = resp.json()
                    rows.extend((r["created_at"], r["id"]) for r in body["data"])
                    if not body["has_more"]:
                        break
                    cursor = body["next_cursor"]
            _assert_desc_by_created_then_id(rows)
            assert len(rows) == 23, f"{path}"
        finally:
            run(session.close())
            run(engine.dispose())


def test_empty_result_set():
    for path, _seed, params in ENDPOINTS:
        engine, session, tenant = run(make_sqlite_session())
        try:
            with client_for(session, tenant) as client:
                resp = client.get(path, params={"limit": 10, **params})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["data"] == [], f"{path}"
            assert body["has_more"] is False, f"{path}"
            assert body["next_cursor"] is None, f"{path}"
        finally:
            run(session.close())
            run(engine.dispose())


def test_single_page_when_rows_fit_under_limit():
    for path, seed, params in ENDPOINTS:
        engine, session, tenant = run(make_sqlite_session())
        try:
            seed(session, 3)
            with client_for(session, tenant) as client:
                resp = client.get(path, params={"limit": 10, **params})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert len(body["data"]) == 3, f"{path}"
            assert body["has_more"] is False, f"{path}"
            assert body["next_cursor"] is None, f"{path}"
        finally:
            run(session.close())
            run(engine.dispose())


def test_exact_multiple_of_limit_terminates_cleanly():
    # When the row count is an exact multiple of the limit, the final full page
    # must report has_more=False (the +1 fetch finds nothing beyond it).
    for path, seed, params in ENDPOINTS:
        engine, session, tenant = run(make_sqlite_session())
        try:
            seed(session, 10)
            with client_for(session, tenant) as client:
                ids, pages = _traverse(client, path, limit=5, params=params)
            assert len(ids) == 10, f"{path}"
            assert len(set(ids)) == 10, f"{path}"
            assert [len(p["data"]) for p in pages] == [5, 5], f"{path}"
            assert pages[-1]["has_more"] is False, f"{path}"
        finally:
            run(session.close())
            run(engine.dispose())


# --------------------------------------------------------------------------- #
# Tie-break test: rows sharing created_at must order by id DESC and never
# duplicate or drop across a page boundary that falls inside the tie group.
# --------------------------------------------------------------------------- #
def test_same_created_at_breaks_ties_by_id_without_dupes_or_gaps():
    engine, session, tenant = run(make_sqlite_session())
    try:
        same = BASE_TIME

        async def _seed():
            session.add_all(
                Approval(
                    id=f"act_tie_{i:03d}",
                    tenant_id=TENANT_ID,
                    function_name="charge_card",
                    decision="pending",
                    created_at=same,  # identical timestamp for all rows
                )
                for i in range(12)
            )
            await session.commit()

        run(_seed())
        with client_for(session, tenant) as client:
            ids, _pages = _traverse(client, "/v1/approvals", limit=5)

        assert len(ids) == 12
        assert len(set(ids)) == 12, f"dupes across tie boundary: {ids}"
        # With equal created_at, the contract is id DESC.
        expected = sorted((f"act_tie_{i:03d}" for i in range(12)), reverse=True)
        assert ids == expected, f"tie-break order wrong: {ids}"
    finally:
        run(session.close())
        run(engine.dispose())


# --------------------------------------------------------------------------- #
# Filter + pagination interaction: a status filter must be preserved across
# pages (cursor must not leak rows that fail the base filter).
# --------------------------------------------------------------------------- #
def test_status_filter_preserved_across_pages_on_approvals():
    engine, session, tenant = run(make_sqlite_session())
    try:
        _seed_approvals(session, 12, start=0, decision="pending")
        _seed_approvals(session, 8, start=100, decision="approved")
        with client_for(session, tenant) as client:
            ids, _pages = _traverse(client, "/v1/approvals", limit=5, params={"status": "approved"})
        assert len(ids) == 8, f"filter leaked or dropped rows: {ids}"
        assert all(i.startswith("act_0001") for i in ids), ids  # act_000100..107
        assert len(set(ids)) == 8
    finally:
        run(session.close())
        run(engine.dispose())


# --------------------------------------------------------------------------- #
# Malformed cursor is a 400 (paginator contract).
# --------------------------------------------------------------------------- #
def test_malformed_cursor_returns_400():
    for path, seed, params in ENDPOINTS:
        engine, session, tenant = run(make_sqlite_session())
        try:
            seed(session, 3)
            with client_for(session, tenant) as client:
                resp = client.get(path, params={"limit": 5, "cursor": "!!!not-base64!!!", **params})
            assert resp.status_code == 400, f"{path}: {resp.status_code} {resp.text}"
        finally:
            run(session.close())
            run(engine.dispose())


# --------------------------------------------------------------------------- #
# id helper: maps a seed index to the id each seeder assigns, so shared tests
# can assert exact membership/ordering without knowing the model.
# --------------------------------------------------------------------------- #
def _id_for(path, i):
    return {
        "/v1/approvals": f"act_{i:06d}",
        "/v1/audit-events": f"evt_{i:06d}",
        "/v1/webhooks/deliveries": f"whd_{i:06d}",
    }[path]
