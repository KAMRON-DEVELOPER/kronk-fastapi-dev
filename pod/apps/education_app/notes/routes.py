import os

import aiofiles
from fastapi import APIRouter, Header, UploadFile, status

education_router = APIRouter()


@education_router.post(path="/vocabulary/images", status_code=status.HTTP_200_OK)
async def upload_images(files: list[UploadFile], content_type: str = Header()):
    print(f"📝 content_type when post: {content_type}")

    cwd: str = os.getcwd()
    os.makedirs(os.path.join(cwd, "flutter_images"), exist_ok=True)
    temp_file_path = os.path.join(cwd, "flutter_images")

    try:
        for file in files:
            file_path = os.path.join(temp_file_path, file.filename)
            async with aiofiles.open(file_path, mode="wb") as f:
                while chunk := await file.read(1024 * 1024):
                    await f.write(chunk)
    except Exception as e:
        print(f"🌋 Exception while writing file: {e}")


@education_router.get(path="/vocabulary/images/get", status_code=status.HTTP_200_OK)
async def get_images():
    cwd: str = os.getcwd()
    temp_file_path = os.path.join(cwd, "flutter_images")

    try:
        extracted_words = []

        file_paths = os.listdir(temp_file_path)
        print(f"📝 file_paths: {file_paths}")

        for file_path in file_paths:
            print(f"📝 absolute path: {temp_file_path}/{file_path}")
            extracted_text: str = ""  # await image_to_string(f"{temp_file_path}/{file_path}", lang="eng+uzb")
            print(f"extracted_text: {extracted_text}")
            for text in extracted_text:
                lines = text.split("\n")
                word = lines[0].strip()
                # print(f"📝 text: {text}, lines: {lines}, word: {word}")
                if word:
                    extracted_words.append(word)

        print(f"📝 extracted_words: {extracted_words}")
        # shutil.rmtree(temp_file_path)

        return extracted_words

    except Exception as e:
        print(f"🌋 Exception while reading file: {e}")
        return "fuck off!"
