import asyncio
from datetime import datetime, timedelta, UTC
from typing import Annotated, Optional
from uuid import UUID

import aiofiles
from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from ffmpeg.asyncio import FFmpeg
from sqlalchemy import Result, select
from sqlalchemy.orm import selectinload

from apps.feeds_app.models import EngagementType, FeedModel, TagModel, CategoryModel
from apps.feeds_app.schemas import FeedSchema, FeedResponseSchema, EngagementSchema
from apps.feeds_app.tasks import notify_followers_task, set_engagement_task, remove_engagement_task
from settings.my_config import get_settings
from settings.my_database import DBSession
from settings.my_dependency import strictJwtDependency, jwtDependency
from settings.my_exceptions import NotFoundException, ValidationException
from settings.my_minio import put_file_to_minio, put_object_to_minio, remove_objects_from_minio
from settings.my_redis import cache_manager
from utility.my_enums import CommentPolicy, FeedVisibility
from utility.my_logger import my_logger
from utility.validators import allowed_image_extension, allowed_video_extension, get_file_extension, get_video_duration_using_ffprobe

feed_router = APIRouter()

settings = get_settings()


@feed_router.post(path="/create", response_model=FeedSchema, response_model_exclude_defaults=True, response_model_exclude_none=True, status_code=201)
async def create_feed_route(jwt: strictJwtDependency, session: DBSession,
                            body: Annotated[Optional[str], Form()] = None,
                            scheduled_at: Annotated[Optional[datetime], Form()] = None,
                            feed_visibility: Annotated[Optional[FeedVisibility], Form()] = None,
                            comment_policy: Annotated[Optional[CommentPolicy], Form()] = None,
                            quote_id: Annotated[Optional[UUID], Form()] = None,
                            parent_id: Annotated[Optional[UUID], Form()] = None,
                            category_id: Annotated[Optional[UUID], Form()] = None,
                            tags: Annotated[Optional[list[UUID]], Form()] = None,
                            video_file: Annotated[Optional[UploadFile], File()] = None,
                            image_file: Annotated[Optional[UploadFile], File()] = None):
    try:
        if not body.strip():
            raise ValidationException(detail="body must be provided.")
        if len(body) > 300:
            raise ValidationException(detail="body is exceeded max 300 character limit.")

        if scheduled_at is not None:
            now = datetime.now(UTC)
            max_future = now + timedelta(days=7)
            if scheduled_at < now:
                raise ValidationException("Scheduled time cannot be in the past.")
            if scheduled_at > max_future:
                raise ValidationException("Scheduled time cannot be more than 7 days in the future.")

        feed = FeedModel(author_id=jwt.user_id, body=body, scheduled_at=scheduled_at, quote_id=quote_id, parent_id=parent_id)

        if comment_policy is not None and comment_policy != CommentPolicy.everyone:
            feed.comment_policy = comment_policy
        if feed_visibility is not None and feed_visibility != FeedVisibility.public:
            feed.feed_visibility = feed_visibility

        if category_id:
            category_exists: Optional[CategoryModel] = await session.scalar(select(CategoryModel).where(CategoryModel.id == category_id))
            if not category_exists:
                raise HTTPException(status_code=400, detail="Invalid category ID.")
            feed.category_id = category_exists.id

        if tags:
            tag_ids_in_db = await session.scalars(select(TagModel.id).where(TagModel.id.in_(tags)))
            found_tag_ids = set(tag_ids_in_db.all())
            missing_tags = set(tags) - found_tag_ids
            if missing_tags:
                raise NotFoundException(detail=f"Tag(s) not found: {', '.join(str(tag) for tag in missing_tags)}")

            tags = await session.scalars(select(TagModel).where(TagModel.id.in_(tags)))
            feed.tags.extend(tags.all())

        if image_file:
            my_logger.debug(f"image_file: {image_file}")
            image_url = await validate_and_save_image(user_id=jwt.user_id.hex, image_file=image_file)
            my_logger.debug(f"image_url: {image_url}")
            feed.image_url = image_url

        if video_file:
            my_logger.debug(f"video_file.filename: {video_file.filename}")
            video_url = await validate_and_save_video(user_id=jwt.user_id.hex, video_file=video_file)
            my_logger.debug(f"video_url: {video_url}")
            feed.video_url = video_url

        session.add(instance=feed)
        await session.commit()
        await session.refresh(instance=feed, attribute_names=["id", "created_at", "updated_at", "author", "tags", "category"])

        feed_schema = FeedSchema.model_validate(obj=feed)
        mapping = feed_schema.model_dump(exclude_unset=True, exclude_defaults=True, exclude_none=True, mode="json")
        my_logger.debug(f"mapping: {mapping}")

        await cache_manager.create_feed(mapping=mapping)

        my_logger.warning("notification is starting...")
        if feed.feed_visibility in [FeedVisibility.public, FeedVisibility.followers] and parent_id is None:
            my_logger.warning("notification is processing...")
            await notify_followers_task.kiq(user_id=jwt.user_id.hex)

        return feed_schema
    except Exception as e:
        my_logger.exception(f"Exception while creating feed, e: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@feed_router.patch(path="/update", response_model=FeedSchema, status_code=200)
async def update_feed_route(jwt: strictJwtDependency, session: DBSession,
                            feed_id: UUID,
                            body: Annotated[Optional[str], Form()] = None,
                            scheduled_at: Annotated[Optional[datetime], Form()] = None,
                            feed_visibility: Annotated[Optional[FeedVisibility], Form()] = None,
                            comment_policy: Annotated[Optional[CommentPolicy], Form()] = None,
                            tags: Annotated[Optional[list[UUID]], Form()] = None,
                            category_id: Annotated[Optional[UUID], Form()] = None,
                            video_file: Annotated[Optional[UploadFile], File()] = None,
                            image_file: Annotated[Optional[UploadFile], File()] = None,
                            remove_video: Annotated[Optional[str], Form()] = None,
                            remove_image: Annotated[Optional[str], Form()] = None):
    try:
        my_logger.debug(f"body: {body}")
        my_logger.debug(f"video_file.filename: {video_file.filename if video_file is not None else None}")
        my_logger.debug(f"image_file.filename: {image_file.filename if video_file is not None else None}")
        my_logger.debug(f"remove_video: {remove_video}")
        my_logger.debug(f"remove_image: {remove_image}")

        stmt = select(FeedModel).where(FeedModel.id == feed_id)
        result: Result = await session.execute(stmt)
        feed: Optional[FeedModel] = result.scalar_one_or_none()
        if feed is None:
            raise NotFoundException(detail="feed not found")

        if body is not None:
            if not body.strip():
                raise ValidationException(detail="body must be provided.")
            if len(body) > 300:
                raise ValidationException(detail="body is exceeded max 300 character limit.")

            if feed.body != body:
                feed.body = body
                await cache_manager.update_feed(feed_id=feed_id.hex, key="body", value=body)

        now = datetime.now(UTC)
        if scheduled_at is not None and feed.scheduled_at > now:
            max_future = now + timedelta(days=7)
            if scheduled_at < now:
                raise ValidationException("Scheduled time cannot be in the past.")
            if scheduled_at > max_future:
                raise ValidationException("Scheduled time cannot be more than 7 days in the future.")

        if feed_visibility is not None and feed.feed_visibility != feed_visibility:
            feed.feed_visibility = feed_visibility
            await cache_manager.update_feed(feed_id=feed.id.hex, key="feed_visibility", value=feed_visibility.value)

        if comment_policy is not None and feed.comment_policy != comment_policy:
            feed.comment_policy = comment_policy
            await cache_manager.update_feed(feed_id=feed.id.hex, key="comment_policy", value=comment_policy.value)

        if category_id:
            category_exists: Optional[CategoryModel] = await session.scalar(select(CategoryModel).where(CategoryModel.id == category_id))
            if not category_exists:
                raise HTTPException(status_code=400, detail="Invalid category ID.")
            feed.category_id = category_exists.id
            await cache_manager.update_feed(feed_id=feed.id.hex, key="category_id", value=category_id)

        if tags:
            tag_ids_in_db = await session.scalars(select(TagModel.id).where(TagModel.id.in_(tags)))
            found_tag_ids = set(tag_ids_in_db.all())
            missing_tags = set(tags) - found_tag_ids
            if missing_tags:
                raise NotFoundException(detail=f"Tag(s) not found: {', '.join(str(tag) for tag in missing_tags)}")

            db_tags = await session.scalars(select(TagModel).where(TagModel.id.in_(tags)))
            feed.tags.extend(db_tags.all())
            await cache_manager.update_feed(feed_id=feed.id.hex, key="tags", value=tags)

        if remove_image and feed.image_url:
            await remove_objects_from_minio([feed.image_url])
        if remove_video and feed.video_url == remove_video:
            await remove_objects_from_minio([feed.video_url])

        if image_file:
            my_logger.debug(f"image_file: {image_file}")
            url = await validate_and_save_image(user_id=jwt.user_id.hex, image_file=image_file)
            my_logger.debug(f"url: {url}")
            feed.image_url = url
            await cache_manager.update_feed(feed_id=feed.id.hex, key="image_url", value=url)

        if video_file:
            my_logger.debug(f"video_file.filename: {video_file.filename}")
            object_name = await validate_and_save_video(user_id=jwt.user_id.hex, video_file=video_file)
            my_logger.debug(f"object_name: {object_name}")
            feed.video_url = object_name
            await cache_manager.update_feed(feed_id=feed.id.hex, key="video_url", value=object_name)

        session.add(instance=feed)
        await session.commit()
        await session.refresh(instance=feed, attribute_names=["id", "created_at", "updated_at", "author", "tags", "category"])

        feed_schema = FeedSchema.model_validate(obj=feed)
        return feed_schema
    except Exception as e:
        my_logger.exception(f"Exception while creating post media, e: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@feed_router.delete(path="/delete", status_code=204)
async def delete_feed_route(jwt: strictJwtDependency, feed_id: UUID, session: DBSession):
    feed: Optional[FeedModel] = await session.get(FeedModel, feed_id)
    if feed is None:
        raise NotFoundException(detail="feed not found")

    if feed.video_url:
        await remove_objects_from_minio(object_names=[feed.video_url])
    if feed.image_url:
        await remove_objects_from_minio(object_names=[feed.image_url])
    await session.delete(instance=feed)
    await session.commit()
    await cache_manager.delete_feed(author_id=jwt.user_id.hex, feed_id=feed_id.hex)


@feed_router.get(path="/timeline/discover", response_model=FeedResponseSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def discover_timeline_route(jwt: jwtDependency, start: int = 0, end: int = 9):
    try:
        feeds = await cache_manager.get_discover_timeline(user_id=jwt.user_id.hex if jwt is not None else None, start=start, end=end)
        return feeds
    except Exception as e:
        print(f"Exception in discover_timeline_route: {e}")
        raise HTTPException(status_code=400, detail=f"Exception in discover_timeline_route: {e}")


@feed_router.get(path="/timeline/following", response_model=FeedResponseSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def following_timeline_route(jwt: strictJwtDependency, start: int = 0, end: int = 9):
    try:
        feeds = await cache_manager.get_following_timeline(user_id=jwt.user_id.hex, start=start, end=end)
        return feeds
    except Exception as e:
        my_logger.critical(f"Exception in following_timeline_route: {e}")
        raise HTTPException(status_code=400, detail=f"Exception in following_timeline_route: {e}")


@feed_router.get(path="/timeline/user", response_model=FeedResponseSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def user_timeline_route(jwt: strictJwtDependency, engagement_type: EngagementType, start: int = 0, end: int = 9):
    try:
        feeds = await cache_manager.get_user_timeline(user_id=jwt.user_id.hex, engagement_type=engagement_type, start=start, end=end)
        return feeds
    except Exception as e:
        my_logger.debug(f"Exception in user_timeline route: {e}")
        raise HTTPException(status_code=500, detail="Server error occurred while creating feed.")


@feed_router.get(path="/comments", response_model=FeedResponseSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def get_comments(jwt: strictJwtDependency, feed_id: UUID, session: DBSession, start: int = 0, end: int = 9):
    try:
        stmt = (
            select(FeedModel)
            .where(FeedModel.parent_id == feed_id)
            .order_by(FeedModel.created_at.asc())
            .offset(start)
            .limit(end - start + 1)
            .options(selectinload(FeedModel.author), selectinload(FeedModel.tags), selectinload(FeedModel.category))
        )
        results = await session.scalars(stmt)
        comments: list[FeedModel] = results.all()

        if comments:
            my_logger.debug(f"comments: {comments}, comments[0].__dict__: {comments[0].__dict__}")
            my_logger.debug(f"comments: {comments}, comments[0].author.username: {comments[0].author.username}")

        end: int = await cache_manager.get_comments_count(feed_id=feed_id.hex)
        my_logger.debug(f"end: {end}")
        engagements: list[dict] = await asyncio.gather(*[cache_manager.get_engagement(user_id=jwt.user_id.hex, feed_id=comment.id.hex, is_comment=True) for comment in comments])
        schemas: list[FeedSchema] = [FeedSchema.model_validate({**comment.__dict__, "engagement": engagement}) for comment, engagement in zip(comments, engagements)]

        return {"feeds": schemas, "end": end}
    except Exception as e:
        my_logger.exception(f"Error fetching comments for feed {feed_id}: {e}")
        raise HTTPException(status_code=500, detail="Error fetching comments")


@feed_router.post(path="/engagement/set", response_model=EngagementSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def set_engagement(jwt: strictJwtDependency, feed_id: UUID, engagement_type: EngagementType, is_comment: bool = False):
    engagement = await cache_manager.set_engagement(user_id=jwt.user_id.hex, feed_id=feed_id.hex, engagement_type=engagement_type, is_comment=is_comment)
    await set_engagement_task.kiq(user_id=jwt.user_id.hex, feed_id=feed_id, engagement_type=engagement_type)
    my_logger.debug(f"engagement: {engagement}")

    if engagement_type == EngagementType.reposts:
        follower_ids = cache_manager.get_followers(user_id=jwt.user_id.hex)

        async with cache_manager.cache_redis.pipeline() as pipe:
            for fid in follower_ids:
                pipe.hset(name=f"users:{fid}:following_timeline", value=feed_id.hex)

    return engagement


@feed_router.post(path="/engagement/remove", response_model=EngagementSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def remove_engagement(jwt: strictJwtDependency, feed_id: UUID, engagement_type: EngagementType, is_comment: bool = False):
    engagement = await cache_manager.remove_engagement(user_id=jwt.user_id.hex, feed_id=feed_id.hex, engagement_type=engagement_type, is_comment=is_comment)
    await remove_engagement_task.kiq(user_id=jwt.user_id.hex, feed_id=feed_id, engagement_type=engagement_type)
    my_logger.debug(f"engagement: {engagement}")
    return engagement


@feed_router.get(path="/search", response_model=FeedResponseSchema, status_code=200)
async def feed_search(jwt: jwtDependency, query: str, offset: int = 0, limit: int = 10):
    try:
        return await cache_manager.search_feed(query=query, user_id=jwt.user_id.hex if jwt.user_id is not None else None, offset=offset, limit=limit)
    except Exception as exception:
        my_logger.critical(f"Exception in feed_search: {exception}")
        raise HTTPException(status_code=500, detail="🤯 WTF? Something just exploded on our end. Try again later!")


async def cleanup_temp_files(paths: list):
    for path in paths:
        try:
            if path.exists():
                path.unlink()
                my_logger.debug(f"Deleted temp file: {path}")
        except Exception as cleanup_error:
            my_logger.error(f"Failed to delete temp file {path}: {cleanup_error}")


async def validate_and_save_image(user_id: str, image_file: UploadFile) -> str:
    ext = get_file_extension(file=image_file)
    if ext not in allowed_image_extension:
        raise ValidationException(detail="Only PNG, JPG, and JPEG formats are allowed for feed images")
    content = await image_file.read()
    if len(content) > 4 * 1024 * 1024:
        raise ValidationException(detail="Feed image size exceeded limit 4MB.")
    return await put_object_to_minio(object_name=f"users/{user_id}/feed_images/{image_file.filename}", data=content, content_type=image_file.content_type)


async def validate_and_save_video(user_id: str, video_file: UploadFile) -> str:
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

        return await put_file_to_minio(object_name=f"users/{user_id}/feed_videos/{video_file.filename}", file_path=temp_video_path, content_type=video_file.content_type)

    finally:
        await cleanup_temp_files([temp_video_path, faststart_video_path])


def validate_feed_create_fields():
    pass
