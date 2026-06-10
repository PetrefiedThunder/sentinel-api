import asyncio
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import get_current_tenant
from app.db import Base, get_db
from app.main import app
from app.models import Tenant

TENANT_ID = "ten_test"


def run(coro):
    return asyncio.run(coro)


async def make_sqlite_session():
    import app.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    tenant = Tenant(id=TENANT_ID, name="Test Tenant", email="team@example.com")
    session.add(tenant)
    await session.commit()
    return engine, session, tenant


@contextmanager
def client_for(session, tenant=None):
    tenant = tenant or Tenant(id=TENANT_ID, name="Test Tenant", email="team@example.com")

    async def override_get_db():
        yield session

    async def override_get_current_tenant():
        return tenant

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_tenant] = override_get_current_tenant
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
