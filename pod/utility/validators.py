import json
import re
import subprocess
import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional

import cv2
from fastapi import UploadFile
from PIL import Image
from PIL.ImageFile import ImageFile
from pymediainfo import MediaInfo, Track
from settings.my_exceptions import ValidationException

email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
violent_words = ["sex", "sexy", "sexual", "nude", "porn", "pornography", "nudes", "nudity"]
violent_words_regex = r"(" + "|".join(re.escape(word) for word in violent_words) + r")"
allowed_image_extension = {"png", "jpg", "jpeg"}
allowed_video_extension = {"mp4", "mov"}


def validate_username(username: Optional[str] = None) -> None:
    if username is not None:
        if not username:
            raise ValidationException(detail="Username cannot be empty.")
        validate_length(field=username, min_len=3, max_len=20, field_name="Username")
        if re.search(violent_words_regex, username, re.IGNORECASE):
            raise ValidationException("Username contains restricted or inappropriate content.")


def validate_email(email: Optional[str] = None) -> None:
    if email is not None:
        if not email:
            raise ValidationException(detail="Email cannot be empty.")
        validate_length(field=email, min_len=5, max_len=255, field_name="Email")
        if not re.match(email_regex, email):
            raise ValidationException("Invalid email format.")


def validate_phone_number(phone_number: Optional[str] = None):
    if phone_number is not None:
        if not phone_number:
            raise ValidationException(detail="Phone number cannot be empty.")


def validate_password(password_string: Optional[str] = None) -> None:
    if password_string is not None:
        if not password_string:
            raise ValidationException(detail="Password cannot be empty.")
        validate_length(field=password_string, min_len=8, max_len=255, field_name="Password")
        if not re.search(pattern=r"\d", string=password_string):
            raise ValidationException("Password must contain at least one digit.")
        if not re.search(pattern=r"[a-zA-Z]", string=password_string):
            raise ValidationException("Password must contain at least one letter.")


def validate_length(field: str, min_len: int, max_len: int, field_name: str):
    if not (min_len <= len(field) <= max_len):
        raise ValidationException(f"{field_name} must be between {min_len} and {max_len} characters.")


def get_file_extension(file: UploadFile) -> str:
    if file.filename and "." in file.filename:
        return file.filename.rsplit(sep=".", maxsplit=1)[-1].lower()
    return ""


async def get_video_duration(file_path: str) -> float:
    try:
        video = cv2.VideoCapture(file_path)
        if not video.isOpened():
            raise ValidationException(f"Could not open video file: {file_path}")

        fps = video.get(cv2.CAP_PROP_FPS)
        total_frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)

        if fps <= 0 or total_frame_count <= 0:
            raise ValidationException(f"Invalid video properties: fps={fps}, frame_count={total_frame_count}")

        duration = total_frame_count / fps
        video.release()
        return duration
    except Exception as e:
        raise ValidationException(f"Could not get video duration: {e}")


async def get_video_duration_using_ffprobe(file_path: str) -> float:
    result = subprocess.run(args=["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", file_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = json.loads(result.stdout)
    return float(output["format"]["duration"])


async def get_video_duration_using_mediainfo(file_path: str) -> float:
    media_info = MediaInfo.parse(filename=file_path)
    video_track: Track = media_info.video_tracks[0]
    return video_track.duration


def get_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    try:
        image: ImageFile = Image.open(fp=BytesIO(image_bytes))
        width, height = image.size
        return width, height
    except Exception as e:
        raise ValueError(f"Failed to get image dimensions: {e}")


def convert_for_redis(data: dict) -> dict:
    """Convert UUID to hex and datetime to ISO format for Redis compatibility."""

    def convert_value(value):
        if isinstance(value, uuid.UUID):
            return value.hex
        elif isinstance(value, datetime):
            return value.timestamp()
        elif isinstance(value, dict):
            return convert_for_redis(value)
        elif isinstance(value, (list, tuple)):
            return [convert_value(v) for v in value]
        return value

    return {key: convert_value(value) for key, value in data.items()}


def escape_redisearch_special_chars(value: str) -> str:
    # RediSearch special characters (from official docs)
    special_chars = r'[\[\]\(\)\{\}\<\>\:\\"\'\+\-\=\&\|\!\~\@\#\^\*\%\`\?\.\,\/]'
    return re.sub(special_chars, lambda m: f"\\{m.group(0)}", value)
