import json
from io import BytesIO
from pathlib import Path
from typing import Optional

import aiohttp
from miniopy_async.api import Minio
from miniopy_async.datatypes import Object
# from miniopy_async.datatypes import ListObjects, Object
from miniopy_async.helpers import ObjectWriteResult

from settings.my_config import get_settings
from utility.my_logger import my_logger

settings = get_settings()

minio_client: Minio = Minio(
    access_key=settings.S3_ACCESS_KEY_ID,
    secret_key=settings.S3_SECRET_KEY,
    endpoint=settings.S3_ENDPOINT,
    secure=False,
)


async def minio_ready() -> bool:
    try:
        if not await minio_client.bucket_exists(bucket_name=settings.S3_BUCKET_NAME):
            await minio_client.make_bucket(bucket_name=settings.S3_BUCKET_NAME)
            await minio_client.set_bucket_policy("my-bucket", json.dumps(policy))
        return True
    except Exception as e:
        print(f"🌋 Failed in check_if_bucket_exists: {e}")
        return False


async def get_object_from_minio(object_name: str) -> bytes:
    try:
        async with aiohttp.ClientSession():
            return await (await minio_client.get_object(bucket_name=settings.S3_BUCKET_NAME, object_name=object_name)).read()
    except Exception as e:
        print(f"Exception in get_data_from_minio: {e}")
        raise ValueError("Exception in get_data_from_minio: {e}")


async def put_object_to_minio(object_name: str, data: bytes, content_type: str, old_object_name: Optional[str] = None, for_update: bool = False) -> str:
    try:
        if for_update and old_object_name:
            await minio_client.remove_object(bucket_name=settings.S3_BUCKET_NAME, object_name=old_object_name)

        result: ObjectWriteResult = await minio_client.put_object(bucket_name=settings.S3_BUCKET_NAME, object_name=object_name, data=BytesIO(data), length=len(data),
                                                                  content_type=content_type)

        return result.object_name
    except Exception as e:
        print(f"Exception in put_data_to_minio: {e}")
        raise ValueError(f"Exception in put_data_to_minio: {e}")


async def put_file_to_minio(object_name: str, file_path: Path, content_type: str, old_object_name: Optional[str] = None, for_update=False) -> str:
    try:
        if for_update and old_object_name:
            await minio_client.remove_object(bucket_name=settings.S3_BUCKET_NAME, object_name=old_object_name)

        result: ObjectWriteResult = await minio_client.fput_object(bucket_name=settings.S3_BUCKET_NAME, object_name=object_name, file_path=str(file_path),
                                                                   content_type=content_type)

        return result.object_name
    except Exception as e:
        print(f"Exception in put_file_to_minio: {e}")
        raise ValueError(f"Exception in put_file_to_minio: {e}")


async def remove_objects_from_minio(object_names: list[str]) -> None:
    try:
        my_logger.debug(f"remove_objects_from_minio; object_names: {object_names}")
        for object_name in object_names:
            await minio_client.remove_object(bucket_name=settings.S3_BUCKET_NAME, object_name=object_name)
    except Exception as e:
        print(f"Exception in remove_object_from_minio: {e}")


async def wipe_objects_from_minio(user_id: str) -> None:
    try:
        list_objects: list[Object] = await minio_client.list_objects(bucket_name=settings.S3_BUCKET_NAME, prefix=f"users/{user_id}/", recursive=True)
        for user_object in list_objects:
            await remove_objects_from_minio(object_names=[f"{user_object.object_name}"])
    except Exception as e:
        print(f"Exception in wipe_objects_from_minio: {e}")
        raise ValueError(f"Exception in wipe_objects_from_minio: {e}")


policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"AWS": "*"},
            "Action": [
                "s3:GetBucketLocation",
                "s3:ListBucket",
                "s3:ListBucketMultipartUploads",
            ],
            "Resource": "arn:aws:s3:::my-bucket",
        },
        {
            "Effect": "Allow",
            "Principal": {"AWS": "*"},
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListMultipartUploadParts",
                "s3:AbortMultipartUpload",
            ],
            "Resource": "arn:aws:s3:::my-bucket/images/*",
        },
    ],
}
