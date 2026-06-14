# Postgres Read Replica Runbook

How to provision an optional Postgres read replica on Railway and point Sentinel's
read-only traffic at it. The application code already supports this: setting the
`READ_REPLICA_URL` env var is the only switch. Leaving it unset is fully
backward-compatible — reads fall back to the primary engine and behaviour is
identical to having no replica.

**This is a manual, paid operation.** Do not provision unless read load on the
primary is actually a bottleneck. A replica roughly doubles the Postgres line on
the bill (you pay for a second instance's compute + storage).

## What the code does

- `app/config.py` declares `READ_REPLICA_URL` (default `""`).
- `app/db.py`:
  - **Unset:** `read_engine` / `ReadSessionLocal` are aliases of the primary
    `engine` / `SessionLocal`. The `get_read_session` FastAPI dependency yields
    a primary session.
  - **Set:** a second async engine + sessionmaker are created against the
    replica URL, and `get_read_session` yields a replica-backed session.
- Endpoints opt in by depending on `get_read_session` instead of `get_db`.
  As of this change, no endpoints are switched yet — the dependency is provided
  for future read-only endpoints to adopt deliberately (see "Caveats").

The replica URL is normalized the same way the primary URL is: a plain
`postgres://` / `postgresql://` scheme is rewritten to `postgresql+asyncpg://`.

## Provisioning on Railway

> Replication setup steps vary slightly by Railway's current Postgres plugin
> version. If the UI differs, the goal is the same: a second Postgres instance
> that streams from the primary, plus a read-only connection string. Confirm
> against Railway's current Postgres docs before running.

1. **Open the project** in the Railway dashboard → the environment running
   `sentinel-api` (usually `production`).
2. **Add the replica.** On the primary Postgres service, use **Settings → Read
   Replicas → Add Replica** (or, if your plan exposes it differently, provision a
   new Postgres service configured as a streaming replica of the primary).
   - Pick the **same region** as the primary to keep replication lag low.
   - Size it for read load; it does not need the primary's write headroom.
3. **Wait for it to catch up.** The replica must finish its initial sync before
   it serves reads. Watch the replica service logs for streaming/replication to
   reach a steady state.
4. **Grab the connection string.** On the replica service: **Variables /
   Connect** → copy the `DATABASE_URL` (or the read-only connection string
   Railway exposes for the replica). It looks like
   `postgresql://USER:PASS@HOST:PORT/DBNAME`.

## Wiring it into Sentinel

5. **Set the env var** on the `sentinel-api` service (NOT on the Postgres
   services):

   ```bash
   railway variables set READ_REPLICA_URL='postgresql://USER:PASS@REPLICA_HOST:PORT/DBNAME' --service sentinel-api
   ```

   (Or via dashboard: `sentinel-api` → **Variables** → add `READ_REPLICA_URL`.)
   No scheme rewrite needed — the app normalizes `postgres://` /
   `postgresql://` to the asyncpg driver automatically.

6. **Redeploy** `sentinel-api` so the new env var is read at boot (engines are
   built at import time):

   ```bash
   railway up --service sentinel-api
   # or trigger a redeploy from the dashboard
   ```

## Verify

7. **Health check** still returns ok:

   ```bash
   curl -fsS https://api.pauseapi.app/health
   ```

8. **Confirm the replica is actually receiving reads.** On the replica Postgres
   service, watch active queries / connections (Railway metrics, or `psql` on the
   replica: `SELECT count(*) FROM pg_stat_activity WHERE state='active';`). As
   read-only endpoints adopt `get_read_session`, query traffic should appear on
   the replica and primary read load should drop.

9. **Check replication lag** stays low (seconds, not minutes). On the replica:

   ```sql
   SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;
   ```

   Sustained high lag means the replica is undersized or the region differs —
   fix that before routing latency-sensitive reads to it.

## Rollback

The var is the only switch, so rollback is instant and safe:

10. **Unset the env var** on `sentinel-api`:

    ```bash
    railway variables delete READ_REPLICA_URL --service sentinel-api
    ```

11. **Redeploy** `sentinel-api`. With the var gone, `get_read_session` falls back
    to the primary engine — exactly today's behaviour. No code change, no
    migration.

12. **(Optional) Tear down the replica** to stop paying for it: delete the
    replica Postgres service in Railway. Do this only after step 11 has deployed
    and you've confirmed `/health` is green — otherwise reads that were routed to
    the replica will fail.

## Caveats — read this before routing endpoints to the replica

- **Replication lag means stale reads.** A read on the replica can miss a write
  that just committed on the primary. **Never route read-after-write flows to the
  replica** — anything that writes a row and then immediately reads it back (or
  reads it back on the next request in the same user flow) must stay on `get_db`
  (primary). Examples to keep on the primary: idempotency replay checks, "create
  then show the created resource", token/nonce consumption, audit-chain
  verification right after appending.
- **Good candidates for the replica:** large list/export endpoints, dashboards,
  analytics, and reporting where a few seconds of staleness is acceptable.
- **Adopt one endpoint at a time.** Switch a single read-only endpoint's
  dependency from `get_db` to `get_read_session`, deploy, watch lag and
  correctness, then move on. Do not bulk-rewrite.
- **Migrations and writes always target the primary** (`DATABASE_URL`). The
  replica is read-only; never point Alembic or any write path at it.
