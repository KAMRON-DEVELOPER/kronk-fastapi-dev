import asyncio

from settings.my_redis import cache_manager, pubsub_manager
from utility.my_enums import PubSubTopics
from utility.my_logger import my_logger


async def notify_followers_task(user_id: str):
    avatar_url = await cache_manager.get_profile_avatar_url(user_id=user_id)
    follower_ids = await cache_manager.get_followers(user_id=user_id)
    online_users = await cache_manager.get_online_users_in_home_timeline()

    online_followers = [fid for fid in follower_ids if fid in online_users]

    async def notify(follower_id: str):
        topic = PubSubTopics.HOME_TIMELINE.value.format(follower_id=follower_id)
        await pubsub_manager.publish(topic=topic, data={"user_id": user_id, "avatar_url": avatar_url, "event": "new_post"})

    tasks = [notify(follower_id) for follower_id in online_followers]
    await asyncio.gather(*tasks)

    my_logger.info(f"📣 Notified {len(online_followers)} followers of {user_id}")

    # for follower_id in online_followers:
    #     topic = PubSubTopics.HOME_TIMELINE.value.format(follower_id=follower_id)
    #     await pubsub_manager.publish(topic, {"user_id": user_id, "avatar_url": avatar_url, "event": "new_post"})
