from fastapi import APIRouter

from settings.my_minio import minio_ready
from settings.my_redis import redis_ready
from utility import my_logger
from utility.my_logger import my_logger

admin_router = APIRouter()


@admin_router.get(path="/ready", tags=["ready"])
async def ready():
    my_logger.debug("Hello 🧙")
    return {
        "tortoise": "🚀" if True else "🌋",
        "redis": "🚀" if await redis_ready() else "🌋",
        "minio": "🚀" if await minio_ready() else "🌋",
    }
