import asyncio
from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from apps.chats_app import models  # noqa
from apps.users_app.models import Base
from settings.my_config import get_settings
from utility.my_logger import my_logger

settings = get_settings()

async_engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


DBSession = Annotated[AsyncSession, Depends(get_session)]


async def initialize_db():
    async with async_engine.begin() as conn:
        my_logger.debug("Database is initializing...")
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(initialize_db())
