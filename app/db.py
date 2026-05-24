from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


_db_url = settings.DATABASE_URL
if _db_url.startswith("postgresql://"):
    _db_url = "postgresql+asyncpg://" + _db_url[len("postgresql://"):]
elif _db_url.startswith("postgres://"):
    _db_url = "postgresql+asyncpg://" + _db_url[len("postgres://"):]

engine = create_async_engine(_db_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as session:
        yield session
