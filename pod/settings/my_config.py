from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BASE_DIR: Path = Path(__file__).parent.parent.parent.resolve()
    TEMP_IMAGES_FOLDER_PATH: Path = Path(__file__).parent.parent.parent.resolve() / "static/images"
    TEMP_VIDEOS_FOLDER_PATH: Path = Path(__file__).parent.parent.resolve() / "static/videos"

    DEBUG: int = 1

    # DATABASE
    DATABASE_URL: str = ""

    # REDIS & TASKIQ
    REDIS_HOST: str = ""
    REDIS_PASSWORD: str = ""

    # FIREBASE ADMIN SDK
    FIREBASE_ADMINSDK: str = ""

    # S3
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_KEY: str = ""
    S3_ENDPOINT: str = ""
    S3_BUCKET_NAME: str = ""

    # FASTAPI JWT
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_TIME: int = 60
    REFRESH_TOKEN_EXPIRE_TIME: int = 7

    # EMAIL
    EMAIL_SERVICE_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", secrets_dir="/run/secrets")


@lru_cache
def get_settings():
    return Settings()
