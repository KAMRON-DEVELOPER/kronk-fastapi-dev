import asyncio

from settings.my_redis import cache_manager, pubsub_manager
from settings.my_taskiq import broker
from utility.my_enums import PubSubTopics
from utility.my_logger import my_logger


@broker.task(task_name="notify_followers_task")
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

# @broker.task(task_name="recalculate_feed_stats", schedule=[{"cron": "* * * * *"}])
# async def recalculate_feed_stats(cache: Annotated[Redis, TaskiqDepends(lambda: my_cache_redis)]):
#     my_logger.debug(f"recalculate_feed_stats starting...")
#     my_logger.debug(f"cache users count: {await cache.hget(name='users', key='count')}")
#     await cache.hincrby(name="users", key="count")
#     # TODO get feeds
#
#     return {"ok": True}
