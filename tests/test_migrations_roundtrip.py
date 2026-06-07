"""Migration round-trip: every alembic migration must be reversible.

Strategy: spin up an empty SQLite-async database, walk forward through
every revision, then walk back, then forward again. If any down-migration
is broken or the chain has a gap, this fails.

Why SQLite: round-trip on a real Postgres is slow + needs CI Postgres
service. SQLite catches ≈90% of issues (revision chain bugs, missing
op.drop_column / op.drop_table calls, model-vs-migration drift) and runs
in 2 seconds with zero infra.

Production-only features (Postgres-specific column types, RLS policies)
won't be exercised here — that's why we still run an actual `alembic
upgrade head` on the container start in Dockerfile CMD.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _make_config(db_url: str) -> Config:
    # env.py reads DATABASE_URL directly (not the alembic cfg) — see alembic/env.py
    os.environ["DATABASE_URL"] = db_url
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _list_revisions(cfg: Config) -> list[str]:
    """All revisions oldest → newest."""
    script = ScriptDirectory.from_config(cfg)
    revs = list(script.walk_revisions(base="base", head="head"))
    return [r.revision for r in reversed(revs)]


@pytest.mark.skipif(
    not ALEMBIC_INI.exists(),
    reason="alembic.ini missing — not a deployed checkout",
)
def test_revision_chain_is_linear(tmp_path):
    """No branches, no gaps. revision n must have down_revision = revision n-1."""
    db_path = tmp_path / "chain.sqlite"
    # async sqlite — matches the async-engine pattern alembic/env.py expects
    cfg = _make_config(f"sqlite+aiosqlite:///{db_path}")
    revisions = _list_revisions(cfg)

    # First migration has down_revision = None. Each subsequent must point at
    # the one that came before it.
    script = ScriptDirectory.from_config(cfg)
    for i, rev_id in enumerate(revisions):
        rev = script.get_revision(rev_id)
        if i == 0:
            assert rev.down_revision is None, (
                f"First migration {rev_id} should have down_revision = None, "
                f"got {rev.down_revision!r}"
            )
        else:
            assert rev.down_revision == revisions[i - 1], (
                f"Migration {rev_id} has down_revision={rev.down_revision!r} "
                f"but the previous revision is {revisions[i - 1]!r}. "
                f"Make sure new migrations chain off the last one."
            )


@pytest.mark.skipif(
    not ALEMBIC_INI.exists(),
    reason="alembic.ini missing — not a deployed checkout",
)
def test_full_upgrade_then_downgrade_to_base(tmp_path):
    """upgrade head → downgrade base — every reverse op must succeed."""
    db_path = tmp_path / "roundtrip.sqlite"
    # async sqlite — matches the async-engine pattern alembic/env.py expects
    cfg = _make_config(f"sqlite+aiosqlite:///{db_path}")

    # Forward to head
    command.upgrade(cfg, "head")

    # All the way back to base — exercises every downgrade()
    command.downgrade(cfg, "base")

    # Forward again to prove we can re-apply on a clean slate
    command.upgrade(cfg, "head")


@pytest.mark.skipif(
    not ALEMBIC_INI.exists(),
    reason="alembic.ini missing — not a deployed checkout",
)
def test_step_by_step_roundtrip(tmp_path):
    """Each migration individually: upgrade +1, downgrade -1, upgrade +1.

    Surfaces the case where the chain works going forward but one specific
    downgrade is broken. Slower than the all-at-once test but pinpoints
    which migration is the problem.
    """
    db_path = tmp_path / "stepwise.sqlite"
    # async sqlite — matches the async-engine pattern alembic/env.py expects
    cfg = _make_config(f"sqlite+aiosqlite:///{db_path}")
    revisions = _list_revisions(cfg)

    for rev in revisions:
        command.upgrade(cfg, rev)
        # Go back one (only meaningful if there's something to go back to)
        if rev != revisions[0]:
            command.downgrade(cfg, "-1")
            command.upgrade(cfg, "+1")
