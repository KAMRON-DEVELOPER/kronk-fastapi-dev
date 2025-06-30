import json
import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from coredis import PureToken
from coredis import Redis as SearchRedis
from coredis.exceptions import ResponseError
from coredis.modules.response.types import SearchResult
from coredis.modules.search import Field
from redis.asyncio import Redis as CacheRedis
from redis.asyncio.client import PubSub

from apps.chats_app.schemas import ChatTileSchema, ParticipantSchema, ChatTileResponseSchema
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

    async def add_user_to_room(self, user_id: str) -> set[str]:
        async with self.cache_redis.pipeline() as pipe:
            pipe.sadd(f"chats:online", user_id)
            pipe.smembers(name=f"users:{user_id}:chats")
            results = await pipe.execute()
        my_logger.debug(f"results in add_user_to_room: {results}")
        return results[1]

    async def remove_user_from_room(self, user_id: str):
        async with self.cache_redis.pipeline() as pipe:
            pipe.srem(f"chats:online", user_id)
            pipe.smembers(name=f"users:{user_id}:chats")
            results = await pipe.execute()
        my_logger.debug(f"results in remove_user_from_room: {results}")
        return results[1]

    async def add_typing(self, user_id: str, chat_id: str):
        await self.cache_redis.sadd(f"typing:{chat_id}", user_id)

    async def remove_typing(self, user_id: str, chat_id: str):
        await self.cache_redis.srem(f"typing:{chat_id}", user_id)

    async def create_chat_tile(self, mapping: dict):
        chat_id = mapping.get("chat_id", "")
        user_id = mapping.get("user_id", "")
        if not chat_id or not user_id:
            raise ValueError("chat_id and user_id must be present in mapping.")
        await self.cache_redis.hset(name=f"chat_tile:{chat_id}", mapping=mapping)

    async def get_chat_tiles(self, user_id: str) -> ChatTileResponseSchema:
        chat_ids = await self.cache_redis.smembers(f"users:{user_id}:chats")
        my_logger.debug(f"chat_ids: {chat_ids}")
        if not chat_ids:
            return ChatTileResponseSchema(chat_tiles=[], end=0)

        async with self.cache_redis.pipeline() as pipe:
            for chat_id in chat_ids:
                pipe.hgetall(f"chats:{chat_id}")
            chats: list[dict] = await pipe.execute()
            my_logger.debug(f"chats: {chats}")

        participant_ids = [chat.get('author_id') for chat in chats if chat]
        my_logger.debug(f"participant_ids: {participant_ids}")
        if not participant_ids:
            return ChatTileResponseSchema(chat_tiles=[], end=0)

        async with self.cache_redis.pipeline() as pipe:
            for pid in participant_ids:
                pipe.hgetall(f"users:{pid}:profile")
            participants: list[dict] = await pipe.execute()
            my_logger.debug(f"participants: {participants}")

        statuses: list[bool] = (await self.cache_redis.smismember("chats:home", *participant_ids) if participant_ids else [])
        my_logger.debug(f"statuses: {statuses}")

        if not (len(chats) == len(participants) == len(statuses)):
            raise RuntimeError("Data mismatch while resolving chat tiles")

        chat_tiles = [
            ChatTileSchema(**chat, participant=ParticipantSchema(**participant, is_online=status))
            for chat, participant, status in zip(chats, participants, statuses)
        ]

        end = len(chat_ids)
        return ChatTileResponseSchema(chat_tiles=chat_tiles, end=end)

    async def delete_chat_tile(self, user_id: str, chat_id: str):
        await self.cache_redis.srem(f"users:{user_id}:chats", chat_id)
        await self.cache_redis.hdel(name=f"chats:{chat_id}")

    async def set_chat(self, user_id: str, chat_id: str):
        await self.cache_redis.sadd(f"users:{user_id}:chats", chat_id)


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

    async def get_user_timeline(self, user_id: str, start: int = 0, end: int = 10) -> dict[str, list[dict] | int]:
        total_count: int = await self.cache_redis.zcard(name=f"users:{user_id}:user_timeline")
        if total_count == 0:
            return {"feeds": [], "end": 0}

        feed_ids = await self.cache_redis.zrevrange(name=f"user:{user_id}:user_timeline", start=start, end=end)
        feeds: list[dict] = await self._get_feeds(user_id=user_id, feed_ids=feed_ids)
        return {"feeds": feeds, "end": total_count}

    ''' ********************************************* FEED ********************************************* '''

    async def create_feed(self, mapping: dict, max_gt: int = 360, max_ft: int = 120, max_ut: int = 120):
        try:
            author_id: str = mapping.get("author", {}).get("id", "")
            feed_id: str = mapping.get("id", "")
            parent_id: Optional[str] = mapping.get("parent_id", None)
            created_at: float = mapping.get("created_at", time.time())

            # Optional cleanup
            if "author" in mapping:
                mapping.pop("author")
            if "image_urls" in mapping and isinstance(mapping["image_urls"], list):
                mapping["image_urls"] = json.dumps(mapping["image_urls"])
            mapping["author_id"] = author_id

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
        is_feed = await self.cache_redis.exists(f"feeds:{feed_id}:meta") > 0
        is_comment = not is_feed

        try:
            # Get all nested comment IDs (including top-level if comment)
            all_comment_ids: set[str] = await self.get_all_nested_comment_ids(feed_id, is_feed=is_feed)

            if is_comment:
                all_comment_ids.add(feed_id)

            # Get authors of each comment
            async with self.cache_redis.pipeline() as pipe:
                for cid in all_comment_ids:
                    pipe.get(f"comments:{cid}:author_id")
                author_results = await pipe.execute()
            author_ids: list[str] = author_results

            # Delete comment engagements + metadata
            async with self.cache_redis.pipeline() as pipe:
                for cid, aid in zip(all_comment_ids, author_ids):
                    pipe.srem(f"users:{aid}:comments", cid)

                    # Delete all engagement metrics and relationships
                    for suffix in ["comments", "reposts", "quotes", "likes", "views", "bookmarks"]:
                        pipe.delete(f"comments:{cid}:{suffix}")
                    pipe.delete(f"comments:{cid}:author_id")
                    pipe.delete(f"comments:{cid}:parent_id")
                    pipe.delete(f"comments:{cid}:comments")
                await pipe.execute()

            # Feed deletion
            if is_feed:
                follower_ids: set[str] = await self.cache_redis.smembers(f"users:{author_id}:followers")

                async with self.cache_redis.pipeline() as pipe:
                    pipe.zrem("global_timeline", feed_id)
                    pipe.zrem(f"users:{author_id}:following_timeline", feed_id)
                    pipe.zrem(f"users:{author_id}:user_timeline", feed_id)
                    for follower_id in follower_ids:
                        pipe.zrem(f"users:{follower_id}:following_timeline", feed_id)

                    keys = [f"feeds:{feed_id}:{suffix}" for suffix in ["meta", "comments", "reposts", "quotes", "likes", "views", "bookmarks"]]
                    pipe.delete(*keys)

                    user_engagement_keys = [f"users:{author_id}:{suffix}" for suffix in ["comments", "reposts", "quotes", "likes", "views", "bookmarks"]]
                    pipe.delete(*user_engagement_keys)
                    await pipe.execute()

            else:
                # It was a comment — remove from its parent's comment set
                parent_id = await self.cache_redis.get(f"comments:{feed_id}:parent_id")
                if parent_id:
                    is_parent_feed = await self.cache_redis.exists(f"feeds:{parent_id}:meta") > 0
                    prefix = "feeds" if is_parent_feed else "comments"
                    await self.cache_redis.srem(f"{prefix}:{parent_id}:comments", feed_id)
        except Exception as e:
            my_logger.error(f"Exception while deleting feed: {e}")
            raise ValueError(f"Exception while deleting feed: {e}")

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

            # Convert image_urls field
            if "image_urls" in feed_meta:
                feed_meta["image_urls"] = json.loads(feed_meta["image_urls"])
            else:
                feed_meta["image_urls"] = []

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

    async def create_profile(self, mapping: dict):
        try:
            my_logger.debug(f"mapping in create_profile: {mapping}, type: {type(mapping)}")
            await self.cache_redis.hset(name=f"users:{mapping['id']}:profile", mapping=mapping)
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

    async def get_profile(self, user_id: str) -> Optional[dict]:
        profile: dict = await self.cache_redis.hgetall(f"users:{user_id}:profile")
        return profile if profile else None

    async def delete_profile(self, user_id: str):
        followers: set[str] = await self.get_followers(user_id)
        following: set[str] = await self.get_following(user_id)

        feed_ids: list[str] = await self.cache_redis.lrange(name=f"user:{user_id}:user_timeline", start=0, end=-1)

        async with my_cache_redis.pipeline() as pipe:
            # Remove user profile
            pipe.hdel(f"users:{user_id}:profile")

            # Remove user timelines
            pipe.hdel(f"users:{user_id}:user_timeline")
            pipe.hdel(f"user:{user_id}:following_timeline")

            pipe.hdel(f"users:{user_id}:followers")
            pipe.hdel(f"users:{user_id}:followings")

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
                pipe.delete(f"feeds:{feed_id}:meta", f"feeds:{feed_id}:stats")
            await pipe.execute()

    async def get_profile_avatar_url(self, user_id: str) -> Optional[str]:
        return await self.cache_redis.hget(name=f"users:{user_id}:profile", key="avatar")

        # ******************************************************************** FOLLOW MANAGEMENT ********************************************************************

    async def add_follower(self, user_id: str, following_id: str):
        """Add a follower or multiple followers to the user."""
        async with self.cache_redis.pipeline() as pipe:
            pipe.sadd(f"users:{following_id}:followers", user_id)
            pipe.sadd(f"users:{user_id}:followings", following_id)
            pipe.hincrby(name=f"users:{following_id}:profile", key="followers_count")
            pipe.hincrby(name=f"users:{user_id}:profile", key="followings_count")
            await pipe.execute()

    async def remove_follower(self, user_id: str, following_id: str):
        """Remove a follower relationship."""
        # Get all feeds made by the following
        following_feed_ids: list[str] = await self.cache_redis.lrange(name=f"users:{following_id}:timeline", start=0, end=-1)

        async with self.cache_redis.pipeline() as pipe:
            # Remove the follower relationship
            pipe.srem(f"users:{following_id}:followers", user_id)
            pipe.srem(f"users:{user_id}:followings", following_id)
            pipe.hincrby(name=f"users:{following_id}:profile", key="followers_count", amount=-1)
            pipe.hincrby(name=f"users:{user_id}:profile", key="followings_count", amount=-1)

            if following_feed_ids:
                pipe.zrem(f"users:{user_id}:user_timeline", *following_feed_ids)
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

    async def search_user(self, query: str, user_id: Optional[str] = None, offset: int = 0, limit: int = 20):
        try:
            username = escape_redisearch_special_chars(query)
            results: SearchResult = await self.search_redis.search.search(index=USER_INDEX_NAME, query=f"@username:{username}*", offset=offset, limit=limit)
            my_logger.debug(f"search_user results.documents: {results.documents}, count: {results.total}")

            users = []

            for document in results.documents:
                if user_id is not None:
                    document_id: str = str(document.id)
                    _user_id = document_id.split(":")[1]
                    is_following = await self.cache_redis.sismember(name=f"users:{_user_id}:followers", value=user_id)
                    my_logger.debug(f"is_following: {is_following}")
                    users.append({**document.properties, "is_following": bool(is_following)})
            return users
        except Exception as e:
            my_logger.error(f"Search error: {str(e)}")
            return []

    async def search_feed(self, query: str, offset: int = 0, limit: int = 20):
        results: SearchResult = await self.search_redis.search.search(index=feed_INDEX_NAME, query=f"@body:{query}*", offset=offset, limit=limit)
        my_logger.debug(f"search_feed results.documents: {results.documents}, count: {results.total}")

        return [document.properties for document in results.documents]

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

    async def add_online_users_in_chat(self, user_id):
        await self.cache_redis.sadd("online_users_in_chat", user_id)

    async def remove_online_users_in_chat(self, user_id):
        await self.cache_redis.srem("online_users_in_chat", user_id)

    async def get_online_users_in_chat(self) -> set[str]:
        return await self.cache_redis.smembers("online_users_in_chat")

    async def add_online_users_in_home_timeline(self, user_id):
        await self.cache_redis.sadd("online_users_in_home_timeline", user_id)

    async def remove_online_users_in_home_timeline(self, user_id):
        await self.cache_redis.srem("online_users_in_home_timeline", user_id)

    async def get_online_users_in_home_timeline(self) -> set[str]:
        return await self.cache_redis.smembers("online_users_in_home_timeline")


def _scores_getter(stats: dict) -> tuple[int, int, int, int, int, int]:
    return stats.get("comments", 0), stats.get("reposts", 0), stats.get("quotes", 0), stats.get("likes", 0), stats.get("views", 0), stats.get("bookmarks", 0)


def _calculate_score(stats_dict: dict, created_at: float, half_life: float = 36, boost_factor: int = 12) -> float:
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
