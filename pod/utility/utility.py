import random
import re
import string
from io import BytesIO
from typing import Optional
from uuid import UUID

import aiohttp
from modern_colorthief import get_color
from PIL import Image
from settings.my_minio import put_object_to_minio
from utility.my_logger import my_logger


async def get_dominant_color(image_url: str) -> Optional[str]:
    print(f"🚧 image_url: {image_url}")
    try:
        # Download image or fetch it from MinIO
        image_data, _ = await download_image(image_url=image_url)

        if not image_data:
            print("🌋 No image data found.")
            return None

        # Prepare image data and extract dominant color
        image_bytes: Optional[BytesIO] = await prepare_image_data(image_data)
        if image_bytes:
            dominant_color_rgb = get_color(image_bytes, quality=1)
            if dominant_color_rgb:
                return "#{:02x}{:02x}{:02x}".format(*dominant_color_rgb)
        return None
    except Exception as e:
        print(f"🌋 Exception in get_dominant_color: {e}")
        return None


async def download_image(image_url: str) -> tuple[bytes, str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    raise ValueError(f"Failed to download image from {image_url}")
                image_data = await response.read()

                print(f"🔨 1 Uploading image of size {len(image_data)} bytes to MinIO.")
                if not image_data:
                    raise ValueError("Downloaded image is empty.")

                # Detect image format
                image_stream = BytesIO(image_data)
                try:
                    with Image.open(image_stream) as img:
                        extension = img.format.lower() if img.format else ""
                except Exception as e:
                    raise ValueError(f"Couldn't get image extension. {e}")

                return image_data, extension
    except Exception as e:
        print(f"🌋 Exception in download_image: {e}")
        raise Exception("🌋 Exception in download_imag")


async def prepare_image_data(image_data: bytes, max_width: int = 72, max_height: int = 72) -> BytesIO:
    try:
        # Open the image using BytesIO
        print(f"🔨 2 Uploading image of size {len(image_data)} bytes to MinIO.")
        image_stream = BytesIO(image_data)
        pil_image = Image.open(image_stream)

        # Verify and convert to RGB in a single step
        pil_image.load()  # Ensure the image is loaded
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        # Resize the image while maintaining aspect ratio
        pil_image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        # Save into output BytesIO
        output_image = BytesIO()
        pil_image.save(output_image, format="PNG", quality=85)
        output_image.seek(0)

        return output_image
    except Exception as e:
        print(f"🌋 Exception in prepare_image_data: {e}")
        raise ValueError(f"🌋 Exception in prepare_image_data: {e}")


def generate_unique_username(base_name: str) -> str:
    return re.sub(pattern=r"[^a-zA-Z0-9_]", repl="", string=base_name.lower().replace(" ", "_"))


def generate_password_string() -> str:
    characters = string.ascii_letters + string.digits + string.punctuation
    password = "".join(random.choice(characters) for _ in range(12))
    return password


async def generate_avatar_url(user_id: UUID, image_url: str) -> Optional[str]:
    print(f"🚧 image_url: {image_url}, user_id: {user_id}")

    try:
        image_data, extension = await download_image(image_url=image_url)
        my_logger.debug(f"generate_avatar_url image_data, extension : _, {extension}")
        if image_data:
            image_stream: BytesIO = await prepare_image_data(image_data=image_data)
            image_data: bytes = image_stream.read()
            if image_data:
                print(f"🔨 3 Uploading image of size {len(image_data)} bytes to MinIO.")
                print(f"🔨 4 Uploading image of size {len(image_stream.getbuffer())} bytes to MinIO.")
                uploaded_object = await put_object_to_minio(object_name=f"users/{user_id.hex}/avatar.{extension}", data=image_data)
                if uploaded_object:
                    print(f"✅ Successfully uploaded image to MinIO: {uploaded_object}")
                return uploaded_object
        return None
    except Exception as e:
        print(f"🌋 Exception in generate_avatar_url: {e}")
        raise ValueError(f"🌋 Exception in generate_avatar_url: {e}")
