import json
import math
import time
from datetime import date, datetime, timedelta, timezone, UTC
from typing import Any, Optional
from uuid import uuid4, UUID

from coredis import PureToken
from coredis import Redis as SearchRedis
from coredis.exceptions import ResponseError
from coredis.modules.response.types import SearchResult
from coredis.modules.search import Field
from redis.asyncio import Redis as CacheRedis
from redis.asyncio.client import PubSub

from apps.chats_app.schemas import ChatSchema, ParticipantSchema, ChatResponseSchema, ChatMessageSchema
from settings.my_config import get_settings
from utility.my_enums import EngagementType
from utility.my_logger import my_logger
from utility.my_types import StatisticsSchema
from utility.validators import escape_redisearch_special_chars

settings = get_settings()

my_cache_redis: CacheRedis = CacheRedis.from_url(url=f"{settings.REDIS_URL}", db=0, decode_responses=True, auto_close_connection_pool=True)
my_search_redis: SearchRedis = SearchRedis.from_url(url=f"{settings.REDIS_URL}", db=0, decode_responses=True)

USER_INDEX_NAME = "idx:users"
feed_INDEX_NAME = "idx:feeds"


async def redis_ready() -> bool:
    try:
        await my_cache_redis.ping()
        await my_search_redis.ping()
        return True
    except Exception as e:
        print(f"🌋 Failed in redis_om_ready: {e}")
        return False


async def initialize_redis_indexes() -> None:
    try:
        await my_search_redis.search.create(
            index=USER_INDEX_NAME, on=PureToken.HASH, schema=[Field("email", PureToken.TEXT), Field("username", PureToken.TEXT)], prefixes=["users:"]
        )
        my_logger.info("User index created/updated")
    except ResponseError as e:
        if "Index already exists" not in str(e):
            raise

    try:
        await my_search_redis.search.create(index=feed_INDEX_NAME, on=PureToken.HASH, schema=[Field("body", PureToken.TEXT)], prefixes=["feeds:"])
        my_logger.info("Feed index created/updated")
    except ResponseError as e:
        if "Index already exists" not in str(e):
            raise


class RedisPubSubManager:
    def __init__(self, cache_redis: CacheRedis):
        self.cache_redis = cache_redis
        self.active_subscriptions: dict[str, PubSub] = {}

    async def publish(self, topic: str, data: dict):
        await self.cache_redis.publish(channel=topic, message=json.dumps(data))

    async def subscribe(self, topic: str) -> PubSub:
        pubsub = self.cache_redis.pubsub()
        await pubsub.subscribe(topic)
        self.active_subscriptions[topic] = pubsub
        return pubsub

    async def unsubscribe(self, topic: str):
        if pubsub := self.active_subscriptions.get(topic):
            try:
                await pubsub.unsubscribe(topic)
                await pubsub.close()
            finally:
                self.active_subscriptions.pop(topic, None)


class ChatCacheManager:
    def __init__(self, cache_redis: CacheRedis, search_redis: SearchRedis):
        self.cache_redis = cache_redis
        self.search_redis = search_redis

    async def create_chat(self, user_id: str, participant_id: str, chat_id: str, mapping: dict):
        last_message: dict = mapping.pop("last_message")
        async with self.cache_redis.pipeline() as pipe:
            pipe.zadd(name=f"users:{user_id}:chats", mapping={chat_id: datetime.now(UTC).timestamp()})
            pipe.zadd(name=f"users:{participant_id}:chats", mapping={chat_id: datetime.now(UTC).timestamp()})
            pipe.hset(name=f"chats:{chat_id}:meta", mapping=mapping)
            pipe.hset(name=f"chats:{chat_id}:last_message", mapping=last_message)
            pipe.sadd(f"chats:{chat_id}:participants", user_id, participant_id)
            await pipe.execute()

    async def delete_chat(self, participants: list[str], chat_id: str):
        async with self.cache_redis.pipeline() as pipe:
            for pid in participants:
                pipe.zrem(f"users:{pid}:chats", chat_id)
                pipe.delete(f"chats:{chat_id}:meta")
                pipe.delete(f"chats:{chat_id}:last_message")
            pipe.srem(f"chats:{chat_id}:participants", *participants)
            await pipe.execute()

    async def get_chats(self, user_id: str, start: int = 0, end: int = 20) -> ChatResponseSchema:
        chat_ids: list[str] = await self.cache_redis.zrevrange(name=f"users:{user_id}:chats", start=start, end=end)
        if not chat_ids:
            return ChatResponseSchema(chats=[], end=0)

        async with self.cache_redis.pipeline() as pipe:
            for chat_id in chat_ids:
                pipe.hgetall(f"chats:{chat_id}:meta")  # index 0, 3, 6...
                pipe.hgetall(f"chats:{chat_id}:last_message")  # index 1, 4, 7...
                pipe.smembers(f"chats:{chat_id}:participants")  # index 2, 5, 8...
            results = await pipe.execute()

        my_logger.warning(f"results: {results}")

        chats: list[dict] = results[::3]  # Every 3rd element starting at 0
        last_messages: list[dict] = results[1::3]  # Every 3rd element starting at 1
        participant_sets: list[set[str]] = results[2::3]  # Every 3rd element starting at 2

        participant_ids: list[str] = []
        for participant_set in participant_sets:
            participant_set.discard(user_id)
            pid: Optional[str] = next(iter(participant_set), None)
            if not pid:
                continue
            participant_ids.append(pid)

        async with self.cache_redis.pipeline() as pipe:
            for pid in participant_ids:
                pipe.hgetall(f"users:{pid}:profile")
            for pid in participant_ids:
                pipe.sismember("chats:online", pid)
            piped_results = await pipe.execute()

        profiles: list[dict] = piped_results[:len(participant_ids)]
        statuses: list[bool] = piped_results[len(participant_ids):]

        chat_list = []
        for chat_meta, last_msg, pid, profile, is_online in zip(chats, last_messages, participant_ids, profiles, statuses):
            if not pid or not profile:
                continue

            chat = ChatSchema(
                id=chat_meta.get("id"),
                participant=ParticipantSchema(
                    id=UUID(hex=pid),
                    name=profile.get("name"),
                    username=profile.get("username"),
                    avatar_url=profile.get("avatar_url"),
                    last_seen_at=datetime.fromtimestamp(int(profile.get("last_seen_at"))) if "last_seen_at" in profile else None,
                    is_online=is_online,
                ),
                last_activity_at=datetime.fromtimestamp(float(chat_meta.get("last_activity_at", time.time()))),
                last_message=ChatMessageSchema(
                    id=UUID(hex=last_msg.get("id", "")),
                    sender_id=UUID(hex=last_msg.get("sender_id", "")),
                    chat_id=UUID(hex=last_msg.get("chat_id", "")),
                    message=last_msg.get("message", ""),
                    created_at=datetime.fromtimestamp(float(last_msg.get("created_at", time.time()))),
                ),
            )
            chat_list.append(chat)

        return ChatResponseSchema(chats=chat_list, end=len(chat_ids) - 1)

    async def is_user_chat_owner(self, user_id: str, chat_id: str) -> bool:
        score: Optional[float] = await self.cache_redis.zscore(name=f"users:{user_id}:chats", value=chat_id)
        return False if score is None else True

    async def is_online(self, participant_id: str) -> bool:
        return bool(await self.cache_redis.sismember(name="chats:online", value=participant_id))

    ''' ****************************************** EVENTS ****************************************** '''

    async def add_user_to_chats(self, user_id: str) -> set[str]:
        async with self.cache_redis.pipeline() as pipe:
            pipe.sadd(f"chats:online", user_id)
            pipe.zrevrange(name=f"users:{user_id}:chats", start=0, end=-1)
            results = await pipe.execute()
        return results[1]

    async def remove_user_from_chats(self, user_id: str) -> set[str]:
        async with self.cache_redis.pipeline() as pipe:
            pipe.srem(f"chats:online", user_id)
            pipe.zrevrange(name=f"users:{user_id}:chats", start=0, end=-1)
            pipe.hset(f"users:{user_id}:profile", key="last_seen_at", value=int(datetime.now(UTC).timestamp()))
            results = await pipe.execute()
        return results[1]

    async def add_typing(self, user_id: str, chat_id: str):
        await self.cache_redis.sadd(f"typing:{chat_id}", user_id)

    async def remove_typing(self, user_id: str, chat_id: str):
        await self.cache_redis.srem(f"typing:{chat_id}", user_id)

    async def get_chat_participants(self, chat_id: str) -> set[str]:
        return await self.cache_redis.smembers(f"chats:{chat_id}:participants")

    async def get_user_chat_ids(self, user_id: str) -> list[str]:
        return await self.cache_redis.zrevrange(f"users:{user_id}:chats", start=0, end=-1)


class CacheManager:
    def __init__(self, cache_redis: CacheRedis, search_redis: SearchRedis):
        self.cache_redis = cache_redis
        self.search_redis = search_redis

    USER_TIMELINE_KEY = "user:{user_id}:user_timeline"

    ''' ****************************************** TIMELINE ****************************************** '''

    async def get_discover_timeline(self, user_id: Optional[str] = None, start: int = 0, end: int = 10) -> dict[str, list[dict] | int]:
        total_count: int = await self.cache_redis.zcard(name="global_timeline")
        if total_count == 0:
            return {"feeds": [], "end": 0}

        feed_ids: list[str] = await self.cache_redis.zrevrange(name="global_timeline", start=start, end=end)
        feeds = await self._get_feeds(user_id=user_id, feed_ids=feed_ids)
        return {"feeds": feeds, "end": total_count}

    async def get_following_timeline(self, user_id: str, start: int = 0, end: int = 10) -> dict[str, list[dict] | int]:
        total_count: int = await self.cache_redis.zcard(name=f"users:{user_id}:following_timeline")
        if total_count == 0:
            return {"feeds": [], "end": 0}

        feed_ids: list[str] = list(await self.cache_redis.zrevrange(name=f"users:{user_id}:following_timeline", start=start, end=end))
        feeds: list[dict] = await self._get_feeds(user_id=user_id, feed_ids=feed_ids)
        return {"feeds": feeds, "end": total_count}

    async def get_user_timeline(self, user_id: str, engagement_type: EngagementType, start: int = 0, end: int = 10) -> dict[str, list[dict] | int]:
        prefix: str = 'user_timeline' if engagement_type == EngagementType.feeds else engagement_type.value

        if engagement_type == EngagementType.feeds:
            total_count: int = await self.cache_redis.zcard(name=f"users:{user_id}:{prefix}")
        else:
            total_count: int = await self.cache_redis.scard(name=f"users:{user_id}:{prefix}")

        if total_count == 0:
            return {"feeds": [], "end": 0}

        if engagement_type == EngagementType.feeds:
            feed_ids = await self.cache_redis.zrevrange(name=f"users:{user_id}:{prefix}", start=start, end=end)
        else:
            all_feed_ids: set[str] = await self.cache_redis.smembers(name=f"users:{user_id}:{prefix}")
            feed_ids = list(all_feed_ids)[start:end + 1]
            # feed_ids = await self.cache_redis.lrange(name=f"users:{user_id}:{prefix}", start=start, end=end)

        feeds: list[dict] = await self._get_feeds(user_id=user_id, feed_ids=feed_ids)
        return {"feeds": feeds, "end": total_count}

    ''' ********************************************* FEED ********************************************* '''

    async def create_feed(self, mapping: dict, max_gt: int = 360, max_ft: int = 120, max_ut: int = 120):
        try:
            author_id: str = mapping.pop("author", {}).get("id", "")
            feed_id: str = mapping.get("id", "")
            parent_id: Optional[str] = mapping.get("parent_id", None)
            created_at: float = mapping.get("created_at", time.time())

            mapping.update({"author_id": author_id})

            if parent_id is not None:
                # Determine if parent is feed or comment
                is_parent_feed = await self.cache_redis.exists(f"feeds:{parent_id}:meta") > 0
                prefix = "feeds" if is_parent_feed else "comments"

                async with self.cache_redis.pipeline() as pipe:
                    pipe.sadd(f"{prefix}:{parent_id}:comments", feed_id)
                    pipe.sadd(f"users:{author_id}:comments", feed_id)
                    pipe.set(name=f"comments:{feed_id}:author_id", value=author_id)
                    pipe.set(name=f"comments:{feed_id}:parent_id", value=parent_id)
                    await pipe.execute()
                return

            # For top-level feeds only
            followers: set[str] = await self.cache_redis.smembers(f"users:{author_id}:followers")
            initial_score = _calculate_score({"comments": 0, "reposts": 0, "quotes": 0, "likes": 0, "views": 0, "bookmarks": 0}, created_at)

            async with self.cache_redis.pipeline() as pipe:
                # Save feed metadata
                pipe.hset(name=f"feeds:{feed_id}:meta", mapping=mapping)

                # Add to global timeline
                pipe.zadd(name="global_timeline", mapping={feed_id: initial_score})
                pipe.zremrangebyrank(name="global_timeline", min=0, max=-max_gt - 1)

                # Add to author's following timeline
                pipe.zadd(name=f"users:{author_id}:following_timeline", mapping={feed_id: initial_score})
                pipe.zremrangebyrank(name=f"users:{author_id}:following_timeline", min=0, max=-max_ft - 1)

                # Add to author's own(profile) timeline
                pipe.zadd(name=f"users:{author_id}:user_timeline", mapping={feed_id: initial_score})
                pipe.zremrangebyrank(name=f"users:{author_id}:user_timeline", min=0, max=-max_ut - 1)

                # Add to followers' timelines
                for follower_id in followers:
                    pipe.zadd(name=f"users:{follower_id}:following_timeline", mapping={feed_id: initial_score})
                    pipe.zremrangebyrank(name=f"users:{follower_id}:following_timeline", min=0, max=-max_ft - 1)

                # Increment user's own feeds_count
                pipe.hincrby(name=f"users:{author_id}:profile", key="feeds_count")

                await pipe.execute()

        except Exception as e:
            my_logger.error(f"Exception while creating feed: {e}")
            raise ValueError(f"Exception while creating feed: {e}")

    async def update_feed(self, feed_id: str, key: str, value: Any):
        if value is None:
            await self.cache_redis.hdel(f"feeds:{feed_id}:meta", key)
            return
        else:
            if isinstance(value, list):
                value = json.dumps(value)
            await self.cache_redis.hset(name=f"feeds:{feed_id}:meta", key=key, value=value)
            return

    async def delete_feed(self, author_id: str, feed_id: str):
        my_logger.warning(f"Deleting feed: author_id={author_id}, feed_id={feed_id}")
        is_feed = await self.cache_redis.exists(f"feeds:{feed_id}:meta") > 0
        is_comment = not is_feed

        try:
            # Get all nested comment IDs
            comment_ids = await self.get_all_nested_comment_ids(feed_id, is_feed=is_feed)
            if is_comment:
                comment_ids.add(feed_id)

            # Get comment authors
            async with self.cache_redis.pipeline() as pipe:
                for cid in comment_ids:
                    pipe.get(f"comments:{cid}:author_id")
                author_ids = await pipe.execute()

            # Delete comments and their engagement links
            async with self.cache_redis.pipeline() as pipe:
                for cid, aid in zip(comment_ids, author_ids):
                    for suffix in ["comments", "reposts", "quotes", "likes", "views", "bookmarks"]:
                        pipe.delete(f"comments:{cid}:{suffix}")
                        pipe.srem(f"users:{aid}:comments", cid)
                        pipe.srem(f"users:{aid}:{suffix}", cid)
                    pipe.delete(f"comments:{cid}:author_id")
                    pipe.delete(f"comments:{cid}:parent_id")
                    pipe.delete(f"comments:{cid}:comments")
                await pipe.execute()

            if is_feed:
                suffixes = ["comments", "reposts", "quotes", "likes", "views", "bookmarks"]

                # Get all users who interacted with this feed
                engagement_map = {
                    suffix: await self.cache_redis.smembers(f"feeds:{feed_id}:{suffix}")
                    for suffix in suffixes
                }

                # Remove the feed ID from user:<user_id>:<suffix> sets
                async with self.cache_redis.pipeline() as pipe:
                    pipe.zrem("global_timeline", feed_id)
                    pipe.zrem(f"users:{author_id}:user_timeline", feed_id)
                    pipe.zrem(f"users:{author_id}:following_timeline", feed_id)

                    # Remove from followers' timelines
                    follower_ids = await self.cache_redis.smembers(f"users:{author_id}:followers")
                    for follower_id in follower_ids:
                        pipe.zrem(f"users:{follower_id}:following_timeline", feed_id)

                    # Remove feed from all engagement sets
                    for suffix, user_ids in engagement_map.items():
                        for user_id in user_ids:
                            pipe.srem(f"users:{user_id}:{suffix}", feed_id)
                        pipe.delete(f"feeds:{feed_id}:{suffix}")

                    # Feed metadata and user’s post counter
                    pipe.delete(f"feeds:{feed_id}:meta")
                    pipe.hincrby(f"users:{author_id}:profile", key="feeds_count", amount=-1)

                    await pipe.execute()
            else:
                # Handle comment unlinking from parent
                parent_id = await self.cache_redis.get(f"comments:{feed_id}:parent_id")
                if parent_id:
                    is_parent_feed = await self.cache_redis.exists(f"feeds:{parent_id}:meta") > 0
                    prefix = "feeds" if is_parent_feed else "comments"
                    await self.cache_redis.srem(f"{prefix}:{parent_id}:comments", feed_id)

        except Exception as e:
            my_logger.error(f"Exception during feed deletion: {e}")
            raise ValueError(f"Failed to delete feed {feed_id}: {e}")

    async def get_all_nested_comment_ids(self, feed_id: str, is_feed: bool = False) -> set[str]:
        collected = set()
        queue = [feed_id]
        prefix = "feeds" if is_feed else "comments"

        while queue:
            current = queue.pop()
            key = f"{prefix}:{current}:comments"
            children = await self.cache_redis.smembers(key)
            collected.update(children)
            queue.extend(children)
            prefix = "comments"
        return collected

    async def _get_feeds(self, feed_ids: list[str], user_id: Optional[str] = None) -> list[dict]:
        feeds: list[dict] = []

        # Fetch feed metadata
        async with self.cache_redis.pipeline() as pipe:
            for feed_id in feed_ids:
                pipe.hgetall(f"feeds:{feed_id}:meta")
            feed_metas: list[dict] = await pipe.execute()

        # Process feed metadata
        for feed_meta in feed_metas:
            if not feed_meta:
                continue

            feeds.append(feed_meta)

        # Process engagement results
        engagement_keys = ["comments", "reposts", "quotes", "likes", "views", "bookmarks"]
        interaction_keys = ["reposted", "quoted", "liked", "viewed", "bookmarked"]

        async with self.cache_redis.pipeline() as pipe:
            for feed in feeds:
                feed_id = feed["id"]
                for key in engagement_keys:
                    pipe.scard(f"feeds:{feed_id}:{key}")
                if user_id:
                    for key in engagement_keys[1:]:
                        pipe.sismember(f"feeds:{feed_id}:{key}", user_id)
            results = await pipe.execute()

        for index, feed in enumerate(feeds):
            has_interactions = user_id is not None
            chunk_size = len(engagement_keys) + (len(interaction_keys) if has_interactions else 0)
            start = index * chunk_size

            metrics = results[start:start + len(engagement_keys)]
            engagement = {key: value for key, value in zip(engagement_keys, metrics) if value > 0}

            if has_interactions:
                interactions: list[bool] = results[start + len(engagement_keys):start + chunk_size]
                engagement.update({interaction_key: True for interaction_key, interacted in zip(interaction_keys, interactions) if interacted})

            feed["engagement"] = engagement

        # Fetch author profiles
        author_ids = {feed["author_id"] for feed in feeds}
        keys = ["id", "name", "username", "avatar_url"]

        async with self.cache_redis.pipeline() as pipe:
            for aid in author_ids:
                pipe.hmget(f"users:{aid}:profile", keys)
            profiles = await pipe.execute()

        author_profiles = {profile[0]: dict(zip(keys, profile)) for profile in profiles if profile and profile[0]}

        for feed in feeds:
            feed["author"] = author_profiles.get(feed.pop("author_id"), {})

        return feeds

    ''' ***************************************** INTERACTION ***************************************** '''

    async def set_engagement(self, user_id: str, feed_id: str, engagement_type: EngagementType, is_comment: bool = False):
        engagement_key, user_key = _engagement_keys(feed_id=feed_id, user_id=user_id, engagement_type=engagement_type, is_comment=is_comment)

        async with self.cache_redis.pipeline() as pipe:
            pipe.sadd(engagement_key, user_id)
            pipe.sadd(user_key, feed_id)
            await pipe.execute()

            return await self.get_engagement(user_id=user_id, feed_id=feed_id)

    async def remove_engagement(self, user_id: str, feed_id: str, engagement_type: EngagementType, is_comment: bool = False):
        engagement_key, user_key = _engagement_keys(feed_id=feed_id, user_id=user_id, engagement_type=engagement_type, is_comment=is_comment)

        async with self.cache_redis.pipeline() as pipe:
            pipe.srem(engagement_key, user_id)
            pipe.srem(user_key, feed_id)
            await pipe.execute()

        return await self.get_engagement(user_id=user_id, feed_id=feed_id)

    async def get_engagement(self, user_id: str, feed_id: str, is_comment: bool = False):
        engagement_keys = ["comments", "reposts", "quotes", "likes", "views", "bookmarks"]
        interaction_keys = ["reposted", "quoted", "liked", "viewed", "bookmarked"]

        prefix = "comments" if is_comment else "feeds"

        async with self.cache_redis.pipeline() as pipe:
            for key in engagement_keys:
                pipe.scard(f"{prefix}:{feed_id}:{key}")

            for key in engagement_keys[1:]:
                pipe.sismember(f"{prefix}:{feed_id}:{key}", user_id)

            results = await pipe.execute()

        engagement = {}
        num_engagement_keys = len(engagement_keys)
        engagement_values = results[:num_engagement_keys]
        engagement.update({key: value for key, value in zip(engagement_keys, engagement_values) if value > 0})

        interaction_results = results[num_engagement_keys:]
        engagement.update({interaction_key: True for interaction_key, interacted in zip(interaction_keys, interaction_results) if interacted})

        return engagement

    ''' ********************************************* USER ********************************************* '''

    async def create_profile(self, mapping: dict, user_id: Optional[str] = None, is_following: Optional[str] = None):
        try:

            uid = mapping.get("id")
            async with self.cache_redis.pipeline() as pipe:
                pipe.hset(name=f"users:{uid}:profile", mapping=mapping)
                if user_id is not None and is_following:
                    pipe.sadd(f"users:{uid}:followers", user_id)
                await pipe.execute()
        except Exception as e:
            raise ValueError(f"🥶 Exception while saving user data to cache: {e}")

    async def update_profile(self, user_id: str, key: str, value: Any):
        try:
            if isinstance(value, datetime):
                value = value.timestamp()
            elif isinstance(value, bool):
                value = int(value)
            elif isinstance(value, str):
                value = value.strip()

            if value is None:
                await self.cache_redis.hdel(f"users:{user_id}:profile", key)
            else:
                await self.cache_redis.hset(name=f"users:{user_id}:profile", key=key, value=value)
        except Exception as e:
            raise ValueError(f"🥶 Exception while updating user data in cache: {e}")

    async def update_profile_from_mapping(self, user_id: str, mapping: dict[str, Any]):
        try:
            keys_for_deletion: list[str] = []
            for key, value in mapping.items():
                if isinstance(value, datetime):
                    mapping[key] = value.timestamp()
                elif isinstance(value, bool):
                    mapping[key] = int(value)
                elif isinstance(value, str):
                    mapping[key] = value.strip()

                if value is None:
                    keys_for_deletion.append(key)
                    mapping.pop(key)

            async with self.cache_redis.pipeline() as pipe:
                pipe.hset(f"users:{user_id}:profile", mapping=mapping)
                pipe.hdel(f"users:{user_id}:profile", *keys_for_deletion)
                await pipe.execute()

        except Exception as e:
            raise ValueError(f"🥶 Exception while updating user data in cache: {e}")

    async def get_profile(self, user_id: str, target_user_id: Optional[str] = None) -> Optional[dict]:
        async with self.cache_redis.pipeline() as pipe:
            key = target_user_id or user_id
            pipe.hgetall(name=f"users:{key}:profile")
            if target_user_id is not None:
                pipe.sismember(name=f"users:{user_id}:followings", value=target_user_id)
            results = await pipe.execute()

        user_dict: dict = results[0]
        if target_user_id is not None:
            user_dict.update({"is_following": results[1]})
        return user_dict if user_dict else None

    async def delete_profile(self, user_id: str):
        followers: set[str] = await self.get_followers(user_id)
        following: set[str] = await self.get_following(user_id)

        feed_ids: list[str] = await self.cache_redis.lrange(name=f"user:{user_id}:user_timeline", start=0, end=-1)

        async with my_cache_redis.pipeline() as pipe:
            # Remove user profile
            pipe.delete(f"users:{user_id}:profile", f"users:{user_id}:user_timeline", f"user:{user_id}:following_timeline", f"users:{user_id}:followers",
                        f"users:{user_id}:followings")

            # Remove follow relationships
            for follower_id in followers:
                pipe.srem(f"users:{follower_id}:followings", user_id)
            for following_id in following:
                pipe.srem(f"users:{following_id}:followers", user_id)

            # delete all feeds created by the user
            for feed_id in feed_ids:
                pipe.zrem("global_timeline", feed_id)

                # Remove feed from all user followers home timelines
                for follower_id in followers:
                    pipe.zrem(f"users:{follower_id}:home_timeline", feed_id)

                # Delete feed metadata and stats
                pipe.delete(f"feeds:{feed_id}:meta")
            await pipe.execute()

            for feed_id in feed_ids:
                await self.delete_feed(author_id=user_id, feed_id=feed_id)

    async def get_profile_avatar_url(self, user_id: str) -> Optional[str]:
        return await self.cache_redis.hget(name=f"users:{user_id}:profile", key="avatar")

        # ******************************************************************** FOLLOW MANAGEMENT ********************************************************************

    async def add_follower(self, user_id: str, following_id: str, max_ft: int = 120):
        following_feed_ids: list[tuple[str, float]] = await self.cache_redis.zrange(name=f"users:{following_id}:user_timeline", start=0, end=-1, withscores=True)
        async with self.cache_redis.pipeline() as pipe:
            pipe.sadd(f"users:{following_id}:followers", user_id)
            pipe.sadd(f"users:{user_id}:followings", following_id)
            pipe.hincrby(name=f"users:{following_id}:profile", key="followers_count")
            pipe.hincrby(name=f"users:{user_id}:profile", key="followings_count")

            if following_feed_ids:
                mapping: dict[str, float] = {feed_id: score for feed_id, score in following_feed_ids}
                pipe.zadd(f"users:{user_id}:following_timeline", mapping)
                pipe.zremrangebyrank(name=f"users:{user_id}:following_timeline", min=0, max=-max_ft - 1)
            await pipe.execute()

    async def remove_follower(self, user_id: str, following_id: str):
        following_feed_ids: list[str] = await self.cache_redis.zrange(name=f"users:{following_id}:user_timeline", start=0, end=-1)
        async with self.cache_redis.pipeline() as pipe:
            pipe.srem(f"users:{following_id}:followers", user_id)
            pipe.srem(f"users:{user_id}:followings", following_id)
            pipe.hincrby(name=f"users:{following_id}:profile", key="followers_count", amount=-1)
            pipe.hincrby(name=f"users:{user_id}:profile", key="followings_count", amount=-1)

            if following_feed_ids:
                pipe.zrem(f"users:{user_id}:following_timeline", *following_feed_ids)
            await pipe.execute()

    async def get_followers(self, user_id: str) -> set[str]:
        return await self.cache_redis.smembers(f"users:{user_id}:followers")

    async def get_following(self, user_id: str) -> set[str]:
        return await self.cache_redis.smembers(f"users:{user_id}:followings")

    async def is_following(self, user_id: str, follower_id: str) -> bool:
        return await self.cache_redis.sismember(name=f"users:{user_id}:followings", value=follower_id)

    ''' ***************************** REGISTRATION & FORGOT PASSWORD MANAGEMENT ***************************** '''

    async def set_registration_credentials(self, mapping: dict, expiry: int = 600) -> tuple[str, str]:
        verify_token = uuid4().hex
        await self.cache_redis.hset(name=f"tokens:registration:{verify_token}", mapping=mapping)
        await self.cache_redis.expire(name=f"tokens:registration:{verify_token}", time=expiry)
        return verify_token, (datetime.now(timezone.utc) + timedelta(seconds=expiry)).isoformat()

    async def get_registration_credentials(self, verify_token: str) -> Optional[dict]:
        cred = await self.cache_redis.hgetall(name=f"tokens:registration:{verify_token}")
        return cred if cred else None

    async def remove_registration_credentials(self, verify_token: str):
        await self.cache_redis.delete(f"tokens:registration:{verify_token}")

    async def set_forgot_password_credentials(self, mapping: dict, expiry: int = 600) -> tuple[str, str]:
        forgot_password_token = uuid4().hex
        await self.cache_redis.hset(name=f"tokens:forgot_password:{forgot_password_token}", mapping=mapping)
        await self.cache_redis.expire(name=f"tokens:forgot_password:{forgot_password_token}", time=expiry)
        return forgot_password_token, (datetime.now(timezone.utc) + timedelta(seconds=expiry)).isoformat()

    async def get_forgot_password_credentials(self, forgot_password_token: str) -> Optional[dict]:
        cred = await self.cache_redis.hgetall(f"tokens:forgot_password:{forgot_password_token}")
        return cred if cred else None

    async def remove_forgot_password_credentials(self, forgot_password_token: str):
        await self.cache_redis.delete(f"tokens:forgot_password:{forgot_password_token}")

        # ****************************************************************** STATISTICS MANAGEMENT ******************************************************************

    ''' ****************************************** SEARCH ****************************************** '''

    async def is_username_or_email_taken(self, username: str, email: str) -> tuple[bool, bool]:
        username_query = escape_redisearch_special_chars(username)
        email_query = escape_redisearch_special_chars(email)
        username_results: SearchResult = await self.search_redis.search.search(index=USER_INDEX_NAME, query=f"@username:{username_query}", offset=0, limit=1)
        email_results: SearchResult = await self.search_redis.search.search(index=USER_INDEX_NAME, query=f"@email:{email_query}", offset=0, limit=1)
        return username_results.total > 0, email_results.total > 0

    async def search_user(self, query: str, user_id: Optional[str] = None, offset: int = 0, limit: int = 10) -> dict[str, list[dict] | int]:
        try:
            username = escape_redisearch_special_chars(query)
            results: SearchResult = await self.search_redis.search.search(index=USER_INDEX_NAME, query=f"@username:{username}*", offset=offset, limit=limit)

            users: list[dict] = []
            user_ids = []
            for document in results.documents:
                document_id: str = str(document.id)
                uid = document_id.split(":")
                if len(uid) < 2:
                    continue
                if uid[1] != user_id:
                    user_ids.append(uid[1])
                users.append(document.properties)
            if user_id is not None:
                async with self.cache_redis.pipeline() as pipe:
                    for uid in user_ids:
                        pipe.sismember(name=f"users:{uid}:followers", value=user_id)
                    is_followings = await pipe.execute()

                for user, is_following in zip(users, is_followings):
                    if user:
                        user.update({"is_following": bool(is_following)})

            return {"users": users, "end": results.total}
        except Exception as e:
            my_logger.error(f"Search error: {str(e)}")
            return {"users": [], "end": 0}

    async def search_feed(self, query: str, user_id: Optional[str] = None, offset: int = 0, limit: int = 10):
        results: SearchResult = await self.search_redis.search.search(index=feed_INDEX_NAME, query=f"@body:{query}*", offset=offset, limit=limit, withpayloads=False)

        feed_ids: list[str] = []
        for document in results.documents:
            document_id: str = str(document.id)
            fid = document_id.split(":")
            if len(fid) < 2:
                continue
            feed_ids.append(fid[1])

        feeds = await self._get_feeds(user_id=user_id, feed_ids=feed_ids)
        return {"feeds": feeds, "end": results.total}

    ''' ****************************************** HELPER FUNCTIONS ****************************************** '''

    async def get_comments_count(self, feed_id: str):
        return await self.cache_redis.scard(name=f"feeds:{feed_id}:comments")

    async def incr_statistics(self):
        today_date = date.today().isoformat()
        await self.cache_redis.hincrby(name="statistics", key=today_date)

    async def get_statistics(self) -> StatisticsSchema:
        raw_statistics: dict[str, str] = await self.cache_redis.hgetall("statistics")
        statistics: dict[str, int] = {k: int(v) for k, v in raw_statistics.items()}

        return _parse_statistics(statistics=statistics)

    async def exists(self, name: str):
        return bool(await self.cache_redis.exists(name))

    async def is_username_or_email_pending(self, username: str, email: str):
        username_exists = await self.cache_redis.exists(f"registration:usernames:{username}")
        email_exists = await self.cache_redis.exists(f"registration:emails:{email}")
        return bool(username_exists), bool(email_exists)

    async def is_user_exists(self, username: str, email: str) -> tuple[bool, bool]:
        is_username_exists = await self.cache_redis.hexists(name="user:usernames", key=username)
        is_email_exists = await self.cache_redis.hexists(name="user:emails", key=email)
        return is_username_exists, is_email_exists

    async def add_user_to_feeds(self, user_id):
        await self.cache_redis.sadd("feeds:online", user_id)

    async def remove_user_from_feeds(self, user_id):
        await self.cache_redis.srem("feeds:online", user_id)

    async def get_users_from_feeds(self) -> set[str]:
        return await self.cache_redis.smembers("feeds:online")


def _scores_getter(stats: dict[str, int]) -> tuple[int, int, int, int, int, int]:
    return stats.get("comments", 0), stats.get("reposts", 0), stats.get("quotes", 0), stats.get("likes", 0), stats.get("views", 0), stats.get("bookmarks", 0)


def _calculate_score(stats_dict: dict[str, int], created_at: float) -> float:
    comments, reposts, quotes, likes, views, bookmarks = _scores_getter(stats=stats_dict)
    engagement_score = math.log(1 + (comments + reposts + quotes) * 5 + likes * 2 + views * 0.5)
    return created_at + (engagement_score * 100)


def _calculate_score_old(stats_dict: dict, created_at: float, half_life: float = 36, boost_factor: int = 12) -> float:
    comments, likes, reposts, quotes, views, bookmarks = _scores_getter(stats=stats_dict)
    age_hours = (time.time() - created_at) / 3600

    # Weighted Engagement Score (log-scaled)
    engagement_score = math.log(1 + comments * 5 + likes * 2 + views * 0.5)

    # Exponential Decay (half-life controls decay speed)
    time_decay = math.exp(-age_hours / half_life)

    # Freshness Boost (soft decay instead of sharp drop)
    freshness_boost = 10 * math.exp(-age_hours / boost_factor)

    # Final Score
    return (engagement_score * time_decay) + freshness_boost


def _parse_statistics(statistics: dict[str, int]) -> StatisticsSchema:
    today = datetime.now(timezone.utc).date()
    current_year = today.year

    # Calculate weekly data for the current week (Monday to Sunday)
    start_of_week = today - timedelta(days=today.weekday())  # Monday of current week
    weekly = {}
    for i in range(7):
        week_day = start_of_week + timedelta(days=i)
        day_name = week_day.strftime("%a")  # e.g., "Mon", "Tue"
        date_str = week_day.strftime("%Y-%m-%d")
        weekly[day_name] = statistics.get(date_str, 0)  # 0 for missing or future days

    # Initialize monthly and yearly totals
    monthly_totals = {"Jan": 0, "Feb": 0, "Mar": 0, "Apr": 0, "May": 0, "Jun": 0, "Jul": 0, "Aug": 0, "Sep": 0, "Oct": 0, "Nov": 0, "Dec": 0}
    yearly_totals = {}
    total_count = 0

    # Map month numbers to names
    month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

    # Process statistics dictionary
    for date_str, count in statistics.items():
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            if dt > today:  # Skip future dates
                continue

            # Update total
            total_count += count

            # Update yearly totals
            year_str = str(dt.year)
            yearly_totals[year_str] = yearly_totals.get(year_str, 0) + count

            # Update monthly totals for current year
            if dt.year == current_year:
                month_name = month_names.get(dt.month)
                if month_name:
                    monthly_totals[month_name] += count

        except ValueError:  # Skip invalid date strings
            continue

    return StatisticsSchema(weekly=weekly, monthly=monthly_totals, yearly=yearly_totals, total=total_count)


def _engagement_keys(feed_id: str, user_id: str, engagement_type: EngagementType, is_comment: bool):
    prefix = "comments" if is_comment else "feeds"
    engagement_key = f"{prefix}:{feed_id}:{engagement_type.value}"
    user_key = f"users:{user_id}:{engagement_type.value}"
    return engagement_key, user_key


chat_cache_manager = ChatCacheManager(cache_redis=my_cache_redis, search_redis=my_search_redis)
cache_manager = CacheManager(cache_redis=my_cache_redis, search_redis=my_search_redis)
pubsub_manager = RedisPubSubManager(cache_redis=my_cache_redis)
