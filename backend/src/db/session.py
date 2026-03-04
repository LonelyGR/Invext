"""
Асинхронная сессия SQLAlchemy и фабрика сессий.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.db.base import Base

settings = get_settings()

# Движок для async (asyncpg)
engine = create_async_engine(
    settings.database_url,
    echo=False,  # True для отладки SQL
)

# Фабрика сессий: одна сессия на запрос
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Генератор сессии для FastAPI Depends()."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
