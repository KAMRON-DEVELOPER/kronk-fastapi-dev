import asyncio
import json
import math
import time
from datetime import datetime, timedelta, date, timezone
from typing import Any, Optional
from uuid import uuid4

from coredis import PureToken
from coredis import Redis as SearchRedis
from coredis.exceptions import ResponseError
from coredis.modules.response.types import SearchResult
from coredis.modules.search import Field
from redis.asyncio import Redis as CacheRedis
from redis.asyncio.client import PubSub

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
        await my_search_redis.search.create(index=USER_INDEX_NAME, on=PureToken.HASH, schema=[Field("email", PureToken.TEXT), Field("username", PureToken.TEXT)], prefixes=["users:"])
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
        self.tasks: dict[str, asyncio.Task] = {}

    async def publish(self, topic: str, data: dict):
        await self.cache_redis.publish(channel=topic, message=json.dumps(data))

    async def subscribe(self, topic: str) -> PubSub:
        try:
            pubsub: PubSub = self.cache_redis.pubsub()
            await pubsub.subscribe(topic)
            return pubsub
        except Exception as exception:
            raise ValueError(f"🌋 Exception while subscribing: {exception}")

    async def unsubscribe(self, topic: str):
        if topic in self.tasks:
            self.tasks[topic].cancel()
            del self.tasks[topic]


class ChatCacheManager:
    def __init__(self, cache_redis: CacheRedis, search_redis: SearchRedis):
        self.cache_redis = cache_redis
        self.search_redis = search_redis

    async def add_connection_to_room(self, user_id: str):
        await self.cache_redis.sadd(f"chat_home:{user_id}")

    async def remove_connection_to_room(self, user_id: str):
        await self.cache_redis.sadd(f"chat_home:{user_id}")

    async def add_typing(self, user_id: str, chat_room_id: str):
        await self.cache_redis.sadd(f"typing:{chat_room_id}:{user_id}")


class CacheManager:
    def __init__(self, cache_redis: CacheRedis, search_redis: SearchRedis):
        self.cache_redis = cache_redis
        self.search_redis = search_redis

    USER_TIMELINE_KEY = "user:{user_id}:timeline"

    POST_META_KEY = "feed:{feed_id}:meta"
    POST_LIKES_KEY = "feed:{feed_id}:likes"
    POST_VIEWS_KEY = "feed:{feed_id}:views"
    POST_REPOSTS_KEY = "feed:{feed_id}:reposts"
    GLOBAL_TIMELINE_KEY = "global:timeline"

    # ******************************************************************* SEARCHING *******************************************************************

    async def is_username_or_email_taken(self, username: str, email: str) -> tuple[bool, bool]:
        username_query = escape_redisearch_special_chars(username)
        email_query = escape_redisearch_special_chars(email)
        username_results: SearchResult = await self.search_redis.search.search(index=USER_INDEX_NAME, query=f"@username:{username_query}", offset=0, limit=1)
        email_results: SearchResult = await self.search_redis.search.search(index=USER_INDEX_NAME, query=f"@email:{email_query}", offset=0, limit=1)
        return username_results.total > 0, email_results.total > 0

    async def search_user_by_username(self, username_query: str, user_id: Optional[str] = None, offset: int = 0, limit: int = 20):
        try:
            my_logger.debug(f"user_id: {user_id}")
            my_logger.debug(f"username_query: {username_query}")
            username = escape_redisearch_special_chars(username_query)
            my_logger.debug(f"username: {username}")
            results: SearchResult = await self.search_redis.search.search(index=USER_INDEX_NAME, query=f"@username:{username}*", offset=offset, limit=limit)
            my_logger.debug("************************************************************")
            my_logger.debug(f"results: {results}")
            my_logger.debug(f"type: {type(results)}")
            my_logger.debug("************************************************************")

            users = []

            for document in results.documents:
                # my_logger.debug(f"document: {document}")
                # my_logger.debug(f"type: {type(document)}")
                # my_logger.debug("************************************************************")
                # my_logger.debug(f"document.properties: {document.properties}")
                # my_logger.debug(f"type: {type(document.properties)}")
                # my_logger.debug("************************************************************")
                # my_logger.debug(f"document.id: {document.id}")
                # my_logger.debug(f"type: {type(document.id)}")
                # my_logger.debug("************************************************************")

                if user_id is not None:
                    _user_id = document.id.split(":")[1]
                    is_following = await self.cache_redis.sismember(name=f"users:{_user_id}:followers", value=user_id)
                    my_logger.debug(f"is_following: {is_following}")
                    users.append({**document.properties, "is_following": bool(is_following)})

            return users

        except Exception as e:
            my_logger.error(f"Search error: {str(e)}")
            return []

    async def search_feed_by_body(self, body_query: str, offset: int = 0, limit: int = 20):
        results: SearchResult = await self.search_redis.search.search(index=feed_INDEX_NAME, query=f"@body:{body_query}*", offset=offset, limit=limit)
        my_logger.debug(f"search_feed_by_body results: {results}")

        return [document.properties for document in results.documents]

    # ******************************************************************* TIMELINE MANAGEMENT *******************************************************************

    async def get_global_timeline(self, user_id: str, start: int = 0, end: int = 10) -> list[dict]:
        """Get global timeline with feed metadata and statistics."""
        feed_ids: list[str] = await self.cache_redis.zrevrange(name="global:timeline", start=start, end=end)
        return await self._get_feeds(user_id=user_id, feed_ids=feed_ids)

    async def get_home_timeline(self, user_id: str, start: int = 0, end: int = 10) -> list[dict]:
        feed_ids = list(await self.cache_redis.zrange(name=f"users:{user_id}:home_timeline", start=start, end=end))
        # my_logger.debug(f"Initial feed_ids in home_timeline: {feed_ids}")

        if not feed_ids:
            return await self.get_global_timeline(user_id=user_id, start=start, end=end)

        required_count = end - start
        current_count = len(feed_ids)

        if current_count < required_count:
            needed = required_count - current_count
            # Fetch extra feeds to account for possible duplicates
            fetch_count = needed * 2  # Adjust multiplier based on expected duplicates
            feed_ids_from_gt = await self.cache_redis.zrevrange(name="global:timeline", start=0, end=fetch_count - 1)

            # Filter out existing feed IDs using a set for O(1) lookups
            existing_ids = set(feed_ids)
            unique_gt_feeds = [pid for pid in feed_ids_from_gt if pid not in existing_ids]

            # Take only the needed number of unique feeds
            feed_ids.extend(unique_gt_feeds[:needed])

        # my_logger.debug(f"Final feed_ids after merging: {feed_ids}")
        return await self._get_feeds(user_id=user_id, feed_ids=feed_ids)

    async def get_user_timeline(self, user_id: str, start: int = 0, end: int = 10) -> list[dict]:
        """Get user timeline feeds with stats."""
        feed_ids = await self.cache_redis.lrange(name=f"user:{user_id}:timeline", start=start, end=end)
        return await self._get_feeds(user_id=user_id, feed_ids=feed_ids)

    # ***************************************************************** USER ACTIONS MANAGEMENT *****************************************************************

    async def _get_feeds(self, user_id: str, feed_ids: list[str]) -> list[dict]:
        valid_feeds = []

        # Step 1: Fetch feed meta
        async with self.cache_redis.pipeline() as pipe:
            for feed_id in feed_ids:
                pipe.hgetall(f"feeds:{feed_id}:meta")
            metas: list[dict] = await pipe.execute()

        for index, meta in enumerate(metas):
            if not meta:
                continue

            feed_id = feed_ids[index]
            if "images" in meta:
                try:
                    images = json.loads(meta["images"])
                    if isinstance(images, list):
                        meta["images"] = images
                    else:
                        meta["images"] = []

                except json.JSONDecodeError:
                    my_logger.error(f"Failed to deserialize images for feed: {feed_id}")
                    meta["images"] = []

            valid_feeds.append(meta)

        if not valid_feeds:
            return []

        # Step 2: Fetch engagement counts (likes, dislikes, views)
        async with self.cache_redis.pipeline() as pipe:
            for feed in valid_feeds:
                feed_id = feed["id"]
                pipe.scard(f"feeds:{feed_id}:comments")
                pipe.scard(f"feeds:{feed_id}:likes")
                pipe.scard(f"feeds:{feed_id}:dislikes")
                pipe.scard(f"feeds:{feed_id}:views")
            raw_counts = await pipe.execute()

        for idx, feed in enumerate(valid_feeds):
            offset = idx * 4
            feed.update({"comments": raw_counts[offset], "likes": raw_counts[offset + 1], "dislikes": raw_counts[offset + 2], "views": raw_counts[offset + 3]})

        # Step 3: Fetch user engagement per feed
        if user_id:
            async with self.cache_redis.pipeline() as pipe:
                for feed in valid_feeds:
                    feed_id = feed["id"]
                    pipe.sismember(name=f"feeds:{feed_id}:likes", value=user_id)
                    pipe.sismember(name=f"feeds:{feed_id}:dislikes", value=user_id)
                    pipe.sismember(name=f"feeds:{feed_id}:views", value=user_id)
                results = await pipe.execute()

            for idx, feed in enumerate(valid_feeds):
                feed.update({"is_liked": bool(results[idx * 3 + 0]), "is_disliked": bool(results[idx * 3 + 1]), "is_viewed": bool(results[idx * 3 + 2])})

        # Step 4: Fetch author profile
        author_ids = {feed["author_id"] for feed in valid_feeds}
        async with self.cache_redis.pipeline() as pipe:
            for author_id in author_ids:
                pipe.hmget(f"users:{author_id}:profile", "avatar_url", "username", "first_name", "last_name")
            profiles = await pipe.execute()

        user_map = {author_id: {"avatar_url": p[0], "username": p[1], "first_name": p[2], "last_name": p[3]} for author_id, p in zip(author_ids, profiles)}

        for feed in valid_feeds:
            author = user_map.get(feed["author_id"], {})
            feed.update(
                {"author_avatar_url": author.get("avatar_url"), "author_username": author.get("username"), "author_first_name": author.get("first_name"), "author_last_name": author.get("last_name")},
            )

        return valid_feeds

    async def set_user_engagement(self, user_id: str, feed_id: str, action: EngagementType):
        """Add user engagement (like, dislike, view) for a feed."""
        action_value = action.value

        feed_action_key = f"feeds:{feed_id}:{action_value}"
        user_action_key = f"users:{user_id}:{action_value}"
        async with self.cache_redis.pipeline() as pipe:
            pipe.sadd(feed_action_key, user_id)
            pipe.sadd(user_action_key, feed_id)
            await pipe.execute()

    async def remove_user_engagement(self, user_id: str, feed_id: str, action: EngagementType):
        """Remove a specific engagement."""
        action_value = action.value
        feed_action_key = f"feeds:{feed_id}:{action_value}"
        user_action_key = f"users:{user_id}:{action_value}"
        async with self.cache_redis.pipeline() as pipe:
            pipe.srem(feed_action_key, user_id)
            pipe.srem(user_action_key, feed_id)
            await pipe.execute()

    async def get_user_engagement_for_feeds(self, user_id: str, feed_ids: list[str]) -> dict[str, dict[str, bool]]:
        """Check if a user has liked/disliked/viewed each feed."""
        results = {}
        async with self.cache_redis.pipeline() as pipe:
            for feed_id in feed_ids:
                pipe.sismember(name=f"feeds:{feed_id}:likes", value=user_id)
                pipe.sismember(name=f"feeds:{feed_id}:dislikes", value=user_id)
                pipe.sismember(name=f"feeds:{feed_id}:views", value=user_id)

            raw = await pipe.execute()

        iterator = iter(raw)

        for feed_id in feed_ids:
            results[feed_id] = {"is_liked": bool(next(iterator)), "is_disliked": bool(next(iterator)), "is_viewed": bool(next(iterator))}

        return results

    # ******************************************************************** feedS MANAGEMENT ********************************************************************

    async def create_feed(self, author_id: str, mapping: dict, keep_gt: int = 180, keep_ht: int = 60, keep_ut: int = 60):
        try:
            feed_id: str = mapping.get("id", "")

            if "author" in mapping:
                mapping.pop("author")

            # Serialize the 'images' list to a JSON string
            if "images" in mapping and isinstance(mapping["images"], list):
                mapping["images"] = json.dumps(mapping["images"])

            # inject author_id to mapping
            mapping["author_id"] = author_id

            # Retrieve followers outside the pipeline
            followers: set[str] = await self.cache_redis.smembers(f"users:{author_id}:followers")
            my_logger.debug(f"data_dict: {mapping}, followers: {followers}")

            created_at = mapping.get("created_at", time.time())
            initial_score = calculate_score({"comments": 0, "likes": 0, "views": 0}, created_at)

            async with self.cache_redis.pipeline() as pipe:
                # Cache feed metadata
                pipe.hset(name=f"feeds:{feed_id}:meta", mapping=mapping)

                # Add to global timeline
                pipe.zadd(name="global:timeline", mapping={feed_id: initial_score})
                pipe.zremrangebyrank(name="global:timeline", min=0, max=-keep_gt - 1)

                # Add feed to followers home timeline
                for follower_id in followers:
                    pipe.zadd(name=f"users:{follower_id}:home_timeline", mapping={feed_id: initial_score})
                    pipe.zremrangebyrank(name=f"users:{follower_id}:home_timeline", min=0, max=-keep_ht - 1)

                # Add feed to user timeline
                pipe.lpush(f"users:{author_id}:timeline", feed_id)
                pipe.ltrim(name=f"users:{author_id}:timeline", start=0, end=keep_ut - 1)

                await pipe.execute()
        except Exception as e:
            my_logger.error(f"Exceptions while creating feed: {e}")
            raise ValueError(f"Exceptions while creating feed: {e}")

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
        followers: set[str] = await self.get_followers(user_id=author_id)
        my_logger.debug(f"followers: {followers}")

        async with self.cache_redis.pipeline() as pipe:
            # Remove feed from global timeline if exists
            pipe.zrem("global:timeline", feed_id)

            # Remove feed from all user followers home timelines
            for follower_id in followers:
                pipe.zrem(f"users:{follower_id}:home_timeline", feed_id)

            # Remove feed from user own timeline
            pipe.lrem(name=f"users:{author_id}:timeline", count=0, value=feed_id)

            # Delete feed metadata and stats
            pipe.delete(f"feeds:{feed_id}:meta", f"feeds:{feed_id}:comments", f"feeds:{feed_id}:likes", f"feeds:{feed_id}:dislikes", f"feeds:{feed_id}:views")

            await pipe.execute()

    # ***************************************************************** USER PROFILE MANAGEMENT *****************************************************************

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

        feed_ids: list[str] = await self.cache_redis.lrange(name=f"user:{user_id}:timeline", start=0, end=-1)

        async with my_cache_redis.pipeline() as pipe:
            # Remove user profile
            pipe.hdel(f"users:{user_id}:profile")

            # Remove user timelines
            pipe.hdel(f"users:{user_id}:timeline")
            pipe.hdel(f"users:{user_id}:home_timeline")

            pipe.hdel(f"users:{user_id}:followers")
            pipe.hdel(f"users:{user_id}:followings")

            # Remove follow relationships
            for follower_id in followers:
                pipe.srem(f"users:{follower_id}:followings", user_id)
            for following_id in following:
                pipe.srem(f"users:{following_id}:followers", user_id)

            # delete all feeds created by the user
            for feed_id in feed_ids:
                pipe.zrem("global:timeline", feed_id)

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
                pipe.zrem(f"users:{user_id}:timeline", *following_feed_ids)
            await pipe.execute()

    async def get_followers(self, user_id: str) -> set[str]:
        """Get all followers of a user."""
        return await self.cache_redis.smembers(f"users:{user_id}:followers")

    async def get_following(self, user_id: str) -> set[str]:
        """Get all users that a user is following."""
        return await self.cache_redis.smembers(f"users:{user_id}:followings")

    async def is_following(self, user_id: str, follower_id: str) -> bool:
        """Check if a user is following another user."""
        return await self.cache_redis.sismember(name=f"users:{user_id}:followings", value=follower_id)

    # ******************************************************** REGISTRATION & FORGOT PASSWORD MANAGEMENT ********************************************************
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

    async def incr_statistics(self):
        today_date = date.today().isoformat()
        await self.cache_redis.hincrby(name="statistics", key=today_date)

    async def get_statistics(self) -> StatisticsSchema:
        raw_statistics: dict[str, str] = await self.cache_redis.hgetall("statistics")
        statistics: dict[str, int] = {k: int(v) for k, v in raw_statistics.items()}

        return parse_statistics(statistics=statistics)

    # ******************************************************************** HELPER FUNCTIONS ********************************************************************
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

    # ************************************************************** RESTORATION HELPER FUNCTIONS **************************************************************

    async def bulk_set(self, pattern: str, suffix: str, items: list[dict]):
        my_logger.debug(f"pattern: {pattern}, items: {items}")
        for item in items:
            key = f"{pattern}{item['id']}:{suffix}"
            await self.cache_redis.hmset(name=key, mapping=item)

    async def bulk_get(self, pattern: str, offset: int, limit: int) -> list[dict]:
        keys = await self.cache_redis.keys(pattern)
        keys = keys[offset: offset + limit]
        return [await self.cache_redis.hgetall(k) for k in keys]

    async def get_count(self, match: str, scan_count: int = 1000):
        cursor = 0
        total_count = 0

        while True:
            cursor, keys = await self.cache_redis.scan(cursor=cursor, match=match, count=scan_count)
            total_count += len(keys)

            if cursor == 0:
                break

        return total_count

    async def fetch_data_in_batches(self, cursor: int, match: str, limit: int = 1000) -> tuple[int, list[dict]]:
        cursor, keys = await self.cache_redis.scan(cursor=cursor, match=match, count=limit)
        async with self.cache_redis.pipeline() as pipe:
            for key in keys:
                pipe.hgetall(key)
            users = await pipe.execute()

        return cursor, users

    async def update_post_score(self, feed_id: str):
        meta = await self.cache_redis.hgetall(f"feeds:{feed_id}:meta")
        author_id = meta["author_id"]
        created_at = float(meta["created_at"])
        stats_dict = {
            "comments": await self.cache_redis.llen(f"feeds:{feed_id}:comments"),
            "likes": await self.cache_redis.scard(f"feeds:{feed_id}:likes"),
            "dislikes": await self.cache_redis.scard(f"feeds:{feed_id}:dislikes"),
            "views": await self.cache_redis.scard(f"feeds:{feed_id}:views"),
        }
        new_score = calculate_score(stats_dict, created_at)
        followers = await self.cache_redis.smembers(f"users:{author_id}:followers")
        async with self.cache_redis.pipeline() as pipe:
            pipe.zadd("global:timeline_by_score", {feed_id: new_score})
            for follower_id in followers:
                pipe.zadd(f"users:{follower_id}:home_timeline_by_score", {feed_id: new_score})
            await pipe.execute()

    async def update_post_rankings(self, batch_size: int = 100, score_threshold: float = 0.1):
        """Periodically update post rankings in timelines"""
        current_cursor = 0
        while True:
            # Scan through all feed meta keys in batches
            current_cursor, keys = await self.cache_redis.scan(cursor=current_cursor, match="feeds:*:meta", count=batch_size)

            for key in keys:
                feed_id = key.split(":")[1]
                try:
                    # Get current metadata and stats
                    meta_pipe = self.cache_redis.pipeline()
                    meta_pipe.hgetall(key)
                    meta_pipe.zscore("global:timeline", feed_id)
                    meta_pipe.scard(f"feeds:{feed_id}:comments")
                    meta_pipe.scard(f"feeds:{feed_id}:likes")
                    meta_pipe.scard(f"feeds:{feed_id}:views")
                    meta_result = await meta_pipe.execute()

                    meta, old_score, comments, likes, views = meta_result
                    if not meta or old_score is None:
                        continue

                    # Calculate new score
                    created_at = float(meta.get("created_at", time.time()))
                    new_score = calculate_score({"comments": comments, "likes": likes, "views": views}, created_at)

                    # Only update if significant change
                    if abs(new_score - old_score) < score_threshold:
                        continue

                    # Get author's followers
                    author_id = meta.get("author_id")
                    followers = await self.get_followers(author_id) if author_id else []

                    # Update scores in pipeline
                    update_pipe = self.cache_redis.pipeline()
                    # Update global timeline
                    update_pipe.zadd("global:timeline", {feed_id: new_score}, xx=True)
                    # Update followers' timelines
                    for follower_id in followers:
                        update_pipe.zadd(f"users:{follower_id}:home_timeline", {feed_id: new_score}, xx=True)  # Only update existing entries
                    await update_pipe.execute()

                except Exception as e:
                    my_logger.error(f"Error updating ranking for {feed_id}: {str(e)}")

            if current_cursor == 0:
                break


def scores_getter(stats: dict) -> tuple[int, int, int, int]:
    return stats.get("comments", 0), stats.get("likes", 0), stats.get("dislikes", 0), stats.get("views", 0)


def calculate_score(stats_dict: dict, created_at: float, half_life: float = 36, boost_factor: int = 12) -> float:
    """Calculate feed ranking score using weighted metrics and time decay."""
    comments, likes, _, views = scores_getter(stats=stats_dict)
    age_hours = (time.time() - created_at) / 3600

    # Weighted Engagement Score (log-scaled)
    engagement_score = math.log(1 + comments * 5 + likes * 2 + views * 0.5)

    # Exponential Decay (half-life controls decay speed)
    time_decay = math.exp(-age_hours / half_life)

    # Freshness Boost (soft decay instead of sharp drop)
    freshness_boost = 10 * math.exp(-age_hours / boost_factor)

    # Final Score
    return (engagement_score * time_decay) + freshness_boost


'''
class StatisticsSchema(BaseModel):
    weekly: dict[str, int]
    monthly: dict[str, int]
    yearly: dict[str, int]
    total: int
'''


def parse_statistics(statistics: dict[str, int]) -> StatisticsSchema:
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
    monthly_totals = {
        "Jan": 0, "Feb": 0, "Mar": 0, "Apr": 0, "May": 0, "Jun": 0,
        "Jul": 0, "Aug": 0, "Sep": 0, "Oct": 0, "Nov": 0, "Dec": 0
    }
    yearly_totals = {}
    total_count = 0

    # Map month numbers to names
    month_names = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
    }

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


cache_manager = CacheManager(cache_redis=my_cache_redis, search_redis=my_search_redis)
pubsub_manager = RedisPubSubManager(cache_redis=my_cache_redis)
