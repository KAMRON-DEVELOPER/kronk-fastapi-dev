import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BASE_DIR: Path = Path(__file__).parent.parent.parent.resolve()
    TEMP_IMAGES_FOLDER_PATH: Path = Path(__file__).parent.parent.parent.resolve() / "static/images"
    TEMP_VIDEOS_FOLDER_PATH: Path = Path(__file__).parent.parent.resolve() / "static/videos"

    DEBUG: int = 1

    DATABASE_URL: str = ""

    REDIS_URL: str = ""
    TASKIQ_WORKER_URL: str = ""
    TASKIQ_REDIS_SCHEDULE_SOURCE_URL: str = ""
    TASKIQ_RESULT_BACKEND_URL: str = ""

    # MINIO
    MINIO_ROOT_USER: str = ""
    MINIO_ROOT_PASSWORD: str = ""
    MINIO_ENDPOINT: str = ""
    MINIO_BUCKET_NAME: str = ""

    # FASTAPI JWT
    SECRET_KEY: str = ""
    ALGORITHM: str = ""
    ACCESS_TOKEN_EXPIRE_TIME: int = 0
    REFRESH_TOKEN_EXPIRE_TIME: int = 0

    # EMAIL
    EMAIL_SERVICE_API_KEY: str = ""

    # FIREBASE
    FIREBASE_TYPE: str = ""
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_PRIVATE_KEY_ID: str = ""
    FIREBASE_PRIVATE_KEY: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""
    FIREBASE_CLIENT_ID: str = ""
    FIREBASE_AUTH_URI: str = ""
    FIREBASE_TOKEN_URI: str = ""
    FIREBASE_AUTH_PROVIDER_X509_CERT_URI: str = ""
    FIREBASE_CLIENT_CERT_URL: str = ""

    # AZURE TRANSLATOR
    AZURE_TRANSLATOR_KEY: str = ""
    AZURE_TRANSLATOR_REGION: str = ""
    AZURE_TRANSLATOR_ENDPOINT: str = ""

    FIREBASE_ADMINSDK_DEV: dict = {
        "type": FIREBASE_TYPE,
        "project_id": FIREBASE_PROJECT_ID,
        "private_key_id": FIREBASE_PRIVATE_KEY_ID,
        "private_key": FIREBASE_PRIVATE_KEY,
        "client_email": FIREBASE_CLIENT_EMAIL,
        "client_id": FIREBASE_CLIENT_ID,
        "auth_uri": FIREBASE_AUTH_URI,
        "token_uri": FIREBASE_TOKEN_URI,
        "auth_provider_x509_cert_url": FIREBASE_AUTH_PROVIDER_X509_CERT_URI,
        "client_x509_cert_url": FIREBASE_CLIENT_CERT_URL,
    }

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", secrets_dir="/run/secrets" if not int(os.getenv("DEBUG", "1")) else None)


@lru_cache
def get_settings():
    return Settings()
