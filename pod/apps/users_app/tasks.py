from typing import Optional
from uuid import UUID

from sqlalchemy import exists, select

from apps.users_app.models import FollowModel, UserModel
from services.zepto_service import ZeptoMail
from settings.my_database import DBSession
from settings.my_redis import pubsub_manager
from utility.my_enums import FollowPolicy, FollowStatus, PubSubTopics
from utility.my_logger import my_logger


async def send_email_task(to_email: str, username: str, code: str = "0000", for_forgot_password: bool = False, for_thanks_signing_up: bool = False):
    my_logger.debug(f"send_email_task is starting")
    zepto = ZeptoMail()
    await zepto.send_email(to_email, username, code, for_forgot_password, for_thanks_signing_up)


async def notify_settings_stats():
    await pubsub_manager.publish(topic=PubSubTopics.SETTINGS_STATS.value, data={})
    my_logger.info("📊 Settings statistics published to all instances.")


async def add_follow_to_db(user_id: UUID, following_id: UUID, session: DBSession):
    user: Optional[UserModel] = await session.get(UserModel, user_id)
    if user is None:
        my_logger.error("WTF you are not exist!")
        # Note we can save to logs
        # raise NotFoundException(detail="WTF you are not exist!")

    following: Optional[UserModel] = await session.get(UserModel, following_id)
    if following is None:
        my_logger.error("WTF! User to follow not found")
        # Note we can save to logs
        # NotFoundException(detail="WTF! User to follow not found")

    stmt = exists().where(FollowModel.follower_id == user_id, FollowModel.following_id == following_id).select()
    already_followed = await session.scalar(stmt)
    # already_followed1 = await session.execute(stmt) worked
    # my_logger.debug(f"already_followed: {already_followed}") worked
    # my_logger.debug(f"already_followed1.scalar(): {already_followed1.scalar()}") worked
    # my_logger.debug(f"already_followed1.scalar_one_or_none(): {already_followed1.scalar_one_or_none()}") fail
    # my_logger.debug(f"already_followed1.all(): {already_followed1.all()}") fail
    # my_logger.debug(f"already_followed1.first(): {already_followed1.first()}") fail
    if already_followed:
        my_logger.error("Already following this user")
        return

    follow_status = FollowStatus.accepted if following.follow_policy == FollowPolicy.auto_accept else FollowStatus.pending
    follow = FollowModel(follower_id=user_id, following_id=following_id, follow_status=follow_status)
    session.add(follow)
    await session.commit()


async def delete_follow_from_db(user_id: UUID, following_id: UUID, session: DBSession):
    stmt = select(FollowModel).where(FollowModel.follower_id == user_id, FollowModel.following_id == following_id)
    result = await session.execute(stmt)
    follow = result.scalar_one_or_none()

    if follow is None:
        my_logger.error("Following relation not exist")
        return

    await session.delete(follow)
    await session.commit()
