from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _normalize_async_url(url: str) -> str:
    """Coerce a plain Postgres URL to the asyncpg driver SQLAlchemy needs."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


_db_url = _normalize_async_url(settings.DATABASE_URL)

engine = create_async_engine(_db_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Optional read replica. If READ_REPLICA_URL is set we build a second engine +
# sessionmaker pointed at the replica; otherwise reads reuse the primary engine
# so behaviour is identical to having no replica configured.
if settings.READ_REPLICA_URL:
    read_engine = create_async_engine(
        _normalize_async_url(settings.READ_REPLICA_URL), pool_pre_ping=True
    )
    ReadSessionLocal = async_sessionmaker(read_engine, class_=AsyncSession, expire_on_commit=False)
else:
    read_engine = engine
    ReadSessionLocal = SessionLocal


async def get_db():
    async with SessionLocal() as session:
        yield session


async def get_read_session():
    """Session for read-only endpoints.

    Targets the read replica when READ_REPLICA_URL is set, otherwise falls back
    to the primary engine. Note replication lag: do not use for read-after-write
    flows that must see their own just-committed data — use get_db for those.
    """
    async with ReadSessionLocal() as session:
        yield session
