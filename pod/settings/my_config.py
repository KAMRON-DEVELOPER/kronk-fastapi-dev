from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BASE_DIR: Path = Path(__file__).parent.parent.parent.resolve()
    TEMP_IMAGES_FOLDER_PATH: Path = Path(__file__).parent.parent.parent.resolve() / "static/images"
    TEMP_VIDEOS_FOLDER_PATH: Path = Path(__file__).parent.parent.resolve() / "static/videos"

    DEBUG: int = 1

    # DATABASE
    DATABASE_URL: str = "/run/secrets/DATABASE_URL"

    # REDIS & TASKIQ
    REDIS_URL: str = "/run/secrets/REDIS_URL"
    TASKIQ_WORKER_URL: str = "/run/secrets/TASKIQ_WORKER_URL"
    TASKIQ_REDIS_SCHEDULE_SOURCE_URL: str = "/run/secrets/TASKIQ_REDIS_SCHEDULE_SOURCE_URL"
    TASKIQ_RESULT_BACKEND_URL: str = "/run/secrets/TASKIQ_RESULT_BACKEND_URL"

    # FIREBASE ADMIN SDK
    FIREBASE_ADMINSDK: str = "/run/secrets/FIREBASE_ADMINSDK"

    # S3
    S3_ACCESS_KEY_ID: str = "/run/secrets/S3_ACCESS_KEY_ID"
    S3_SECRET_ACCESS_KEY: str = "/run/secrets/S3_SECRET_ACCESS_KEY"

    # MINIO
    MINIO_ROOT_USER: str = "/run/secrets/MINIO_ROOT_USER"
    MINIO_ROOT_PASSWORD: str = "/run/secrets/MINIO_ROOT_PASSWORD"
    MINIO_ENDPOINT: str = "/run/secrets/MINIO_ENDPOINT"
    MINIO_BUCKET_NAME: str = "/run/secrets/MINIO_BUCKET_NAME"

    # FASTAPI JWT
    SECRET_KEY: str = "/run/secrets/SECRET_KEY"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_TIME: int = 60
    REFRESH_TOKEN_EXPIRE_TIME: int = 7

    # EMAIL
    EMAIL_SERVICE_API_KEY: str = "/run/secrets/EMAIL_SERVICE_API_KEY"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", secrets_dir="/run/secrets")


@lru_cache
def get_settings():
    return Settings()
