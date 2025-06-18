from typing import Annotated, Optional
from uuid import UUID

import aiofiles
from apps.feeds_app.models import CategoryModel, EngagementType, FeedModel, TagModel
from apps.feeds_app.schemas import FeedCreateSchema, FeedSchema
from apps.feeds_app.tasks import notify_followers_task
from apps.users_app.schemas import ResultSchema
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile, status
from ffmpeg.asyncio import FFmpeg
from settings.my_config import get_settings
from settings.my_database import DBSession
from settings.my_dependency import JWTCredential, jwtDependency
from settings.my_exceptions import NotFoundException, ValidationException
from settings.my_minio import put_file_to_minio, put_object_to_minio, remove_objects_from_minio
from settings.my_redis import cache_manager
from sqlalchemy import Result, select
from utility.my_logger import my_logger
from utility.validators import allowed_image_extension, allowed_video_extension, get_file_extension, get_video_duration_using_ffprobe

feed_router = APIRouter()

settings = get_settings()


@feed_router.post(path="/test")
async def test_route():
    try:
        return {"status": "ok"}
    except Exception as e:
        my_logger.error(f"Exception e: {e}")
        return None


@feed_router.post(path="/create", status_code=201)
async def create_feed_route(jwt: jwtDependency, session: DBSession, bgt: BackgroundTasks, schema: FeedCreateSchema):
    try:
        # 1. Validate category existence
        if schema.category:
            category_exists: Optional[CategoryModel] = await session.scalar(select(CategoryModel).where(CategoryModel.id == schema.category))
            if not category_exists:
                raise HTTPException(status_code=400, detail="Invalid category ID.")

        # 2. Validate tag UUIDs existence
        if schema.tags:
            tag_ids_in_db = await session.scalars(select(TagModel.id).where(TagModel.id.in_(schema.tags)))
            found_tag_ids = set(tag_ids_in_db.all())
            missing_tags = set(schema.tags) - found_tag_ids
            if missing_tags:
                raise NotFoundException(detail=f"Tag(s) not found: {', '.join(str(tag) for tag in missing_tags)}")

        feed = FeedModel(author_id=jwt.user_id, body=schema.body, scheduled_time=schema.scheduled_time, category_id=schema.category)

        # 4. Add tags if any
        if schema.tags:
            tags = await session.scalars(select(TagModel).where(TagModel.id.in_(schema.tags)))
            feed.tags.extend(tags.all())

        session.add(instance=feed)
        await session.commit()
        await session.refresh(instance=feed, attribute_names=["author", "tags", "category"])

        feed_schema = FeedSchema.model_validate(obj=feed)

        bgt.add_task(notify_followers_task, user_id=jwt.user_id.hex)

        mapping = feed_schema.model_dump(exclude_unset=True, exclude_defaults=True, exclude_none=True, mode="json")
        my_logger.debug(f"mapping: {mapping}")
        await cache_manager.create_feed(author_id=jwt.user_id.hex, mapping=mapping)

        return {"feed_id": feed.id}
    except Exception as e:
        my_logger.exception(f"Exception while creating feed, e: {e}")
        return {"ok": False}


@feed_router.patch(path="/update", status_code=200)
async def update_feed_route(
    _: jwtDependency,
    session: DBSession,
    feed_id: UUID,
    body: Annotated[Optional[str], Form()] = None,
    remove_image_targets: Annotated[Optional[list[str]], Form()] = None,
    remove_video_target: Annotated[Optional[str], Form()] = None,
):
    try:
        my_logger.debug(f"body: {body}")
        my_logger.debug(f"remove_image_targets: {remove_image_targets}")
        my_logger.debug(f"remove_video_target: {remove_video_target}")

        stmt = select(FeedModel).where(FeedModel.id == feed_id)
        result: Result = await session.execute(stmt)
        feed: Optional[FeedModel] = result.scalar_one_or_none()
        if feed is None:
            raise NotFoundException(detail="feed not found")

        if body is not None:
            feed.body = body
            await cache_manager.update_feed(feed_id=feed_id.hex, key="body", value=body)

        if remove_image_targets and feed.image_urls:
            for target in remove_image_targets:
                if target in feed.image_urls:
                    await remove_objects_from_minio([target])
                    feed.image_urls.remove(target)
            await cache_manager.update_feed(feed_id=feed_id.hex, key="image_urls", value=feed.image_urls)

        if remove_video_target and feed.video_url == remove_video_target:
            await remove_objects_from_minio([feed.video_url])
            feed.video_url = None
            await cache_manager.update_feed(feed_id=feed_id.hex, key="video_url", value=None)

        await session.commit()

        return {"ok": True}

    except Exception as e:
        my_logger.exception(f"Exception while creating post media, e: {e}")
        return {"ok": False}


@feed_router.patch(path="/update/media", response_model=ResultSchema, status_code=200)
async def update_feed_media_route(jwt: jwtDependency, session: DBSession, feed_id: UUID, image_files: Optional[list[UploadFile]] = None, video_file: Optional[UploadFile] = None):
    try:
        if (feed := await session.get(FeedModel, feed_id)) is None:
            raise NotFoundException(detail="feed not found")

        if image_files:
            my_logger.debug(f"image_files[0].filename: {image_files[0].filename}")
            urls = await validate_and_save_images(jwt=jwt, image_files=image_files)
            feed.image_urls = urls
            if urls:
                await cache_manager.update_feed(feed_id=feed_id.hex, key="image_urls", value=feed.image_urls)

        if video_file:
            my_logger.debug(f"video_file.filename: {video_file.filename}")
            object_name = await validate_and_save_video(jwt=jwt, video_file=video_file)
            my_logger.debug(f"object_name: {object_name}")
            feed.video_url = object_name
            await cache_manager.update_feed(feed_id=feed_id.hex, key="video_url", value=object_name)

        await session.commit()
        return {"ok": True}
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        return {"ok": False}


@feed_router.delete(path="/delete", status_code=204)
async def delete_feed_route(jwt: jwtDependency, session: DBSession, feed_id: UUID):
    my_logger.debug(f"feed_id: {feed_id}")
    if (instance := await session.get(FeedModel, feed_id)) is None:
        raise NotFoundException(detail="feed not found")
    if instance.video_url:
        await remove_objects_from_minio(object_names=[instance.video_url])
    if instance.image_urls:
        await remove_objects_from_minio(object_names=instance.image_urls)
    await session.delete(instance=instance)
    await session.commit()
    await cache_manager.delete_feed(author_id=jwt.user_id.hex, feed_id=feed_id.hex)


@feed_router.get(path="/timeline/home", status_code=status.HTTP_200_OK)
async def get_home_timeline(jwt: jwtDependency, start: int = 0, end: int = 10):
    try:
        return await cache_manager.get_home_timeline(user_id=jwt.user_id.hex, start=start, end=end)
    except Exception as e:
        my_logger.critical(f"Exception in get_home_timeline_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in get_home_timeline_route: {e}")


@feed_router.get(path="/timeline/global", status_code=status.HTTP_200_OK)
async def get_global_timeline_route(jwt: jwtDependency, start: int = 0, end: int = 10):
    try:
        return await cache_manager.get_global_timeline(user_id=jwt.user_id.hex, start=start, end=end)
    except ValueError as e:
        print(f"ValueError in get_global_timeline: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in get_global_timeline: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in get_global_timeline: {e}")


@feed_router.post(path="/interaction/add", status_code=status.HTTP_200_OK)
async def feed_track_add(feed_id: str, action: EngagementType, jwt: jwtDependency):
    try:
        user_id = jwt.user_id.hex

        # Always add the requested action first
        await cache_manager.set_user_engagement(user_id=user_id, feed_id=feed_id, action=action)

        # Enforce mutual exclusion between LIKE and DISLIKE
        if action == EngagementType.like:
            await cache_manager.remove_user_engagement(user_id=user_id, feed_id=feed_id, action=EngagementType.dislike)
        elif action == EngagementType.dislike:
            await cache_manager.remove_user_engagement(user_id=user_id, feed_id=feed_id, action=EngagementType.like)
        my_logger.debug(f"feed_id: {feed_id}, action: {action.value}")
        return {"status": "ok"}
    except Exception as e:
        print(f"Exception in feed_track_add: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in feed_track_add: {e}")


@feed_router.post(path="/interaction/remove", status_code=status.HTTP_200_OK)
async def feed_track_remove(feed_id: str, action: EngagementType, jwt: jwtDependency):
    try:
        if action in [EngagementType.like, EngagementType.dislike]:
            await cache_manager.remove_user_engagement(user_id=jwt.user_id.hex, feed_id=feed_id, action=action)
        my_logger.debug(f"feed_id: {feed_id}, action: {action.value}")
        return {"status": "ok"}
    except Exception as e:
        print(f"Exception in feed_track_remove: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in feed_track_remove: {e}")


@feed_router.post(path="/comments/{comment_id}/reaction", status_code=status.HTTP_200_OK)
async def track_feed_comment_view_route(comment_id: str, jwt: jwtDependency):
    try:
        # await cache_manager.mark(user_id=jwt.user_id.hex, comment_id=comment_id)
        return {"status": "comment view tracked"}
    except Exception as e:
        print(f"Exception in track_feed_comment_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_feed_comment_view_route: {e}")


@feed_router.post(path="/comments{comment_id}/reaction", status_code=status.HTTP_200_OK)
async def track_feed_comment_reaction_route(comment_id: str, reaction: EngagementType, jwt: jwtDependency):
    try:
        # await cache_manager.track_user_reaction_to_comment(user_id=jwt.user_id.hex, comment_id=comment_id, reaction=reaction)
        return {"status": "comment reaction tracked"}
    except Exception as e:
        print(f"Exception in track_feed_comment_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_feed_comment_view_route: {e}")


@feed_router.get(path="/user_timeline", status_code=status.HTTP_200_OK)
async def user_timeline(jwt: jwtDependency, start: int = 0, end: int = 19):
    try:
        user_timeline_feeds: list[dict] = await cache_manager.get_user_timeline(user_id=jwt.user_id.hex, start=start, end=end)

        if not user_timeline_feeds:
            return []

        return user_timeline_feeds
    except ValueError as e:
        my_logger.debug(f"ValueError in create_feed_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        my_logger.debug(f"Exception in user_timeline route: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error occurred while creating feed.")


@feed_router.get(path="/search", status_code=status.HTTP_200_OK)
async def feed_search(_: jwtDependency, query: str, offset: int = 0, limit: int = 50):
    try:
        feeds = await cache_manager.search_feed_by_body(body_query=query, offset=offset, limit=limit)
        my_logger.debug(f"feeds: {feeds}")
        return feeds
    except ValueError as value_error:
        my_logger.error(f"ValueError in feed_search: {value_error}")
        raise HTTPException(status_code=400, detail=f"{value_error}")
    except Exception as exception:
        my_logger.critical(f"Exception in feed_search: {exception}")
        raise HTTPException(status_code=500, detail="🤯 WTF? Something just exploded on our end. Try again later!")


# ********************************************** HELPER FUNCTIONS ************************************************


async def cleanup_temp_files(paths: list):
    for path in paths:
        try:
            if path.exists():
                path.unlink()
                my_logger.debug(f"Deleted temp file: {path}")
        except Exception as cleanup_error:
            my_logger.error(f"Failed to delete temp file {path}: {cleanup_error}")


async def validate_and_save_images(jwt: JWTCredential, image_files: list[UploadFile]):
    if len(image_files) > 4:
        raise ValidationException(detail="each feed allowed images limit is 4")

    validated_image_urls = []
    for image_file in image_files:
        ext = get_file_extension(file=image_file)
        if ext not in allowed_image_extension:
            raise ValidationException(detail="Only PNG, JPG, and JPEG formats are allowed for feed images")
        content = await image_file.read()
        if len(content) > 2 * 1024 * 1024:
            raise ValidationException(detail="Feed image size exceeded limit 2MB.")
        url = await put_object_to_minio(object_name=f"users/{jwt.user_id.hex}/post_images/{image_file.filename}", data=content)
        validated_image_urls.append(url)
    return validated_image_urls


async def validate_and_save_video(jwt: JWTCredential, video_file: UploadFile):
    temp_folder = settings.TEMP_VIDEOS_FOLDER_PATH
    faststart_folder = temp_folder / "faststart"
    temp_folder.mkdir(parents=True, exist_ok=True)
    faststart_folder.mkdir(parents=True, exist_ok=True)

    if video_file.filename is None:
        raise ValidationException(detail="filename is not set.")

    temp_video_path = temp_folder / video_file.filename
    faststart_video_path = faststart_folder / video_file.filename

    try:
        ext = get_file_extension(file=video_file)
        if ext not in allowed_video_extension:
            raise ValidationException("Unsupported video format provided.")

        async with aiofiles.open(faststart_video_path, mode="wb") as out_file:
            content = await video_file.read()
            await out_file.write(content)
            await out_file.flush()

        duration = await get_video_duration_using_ffprobe(str(faststart_video_path))
        if duration > 220:
            raise ValidationException("Video exceeds max allowed duration (220 seconds).")

        ffmpeg = FFmpeg().input(str(faststart_video_path)).output(str(temp_video_path), c="copy", movflags="faststart")
        await ffmpeg.execute()

        return await put_file_to_minio(object_name=f"users/{jwt.user_id.hex}/feed_videos/{video_file.filename}", file_path=temp_video_path)

    finally:
        await cleanup_temp_files([temp_video_path, faststart_video_path])
