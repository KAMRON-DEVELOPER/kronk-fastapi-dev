from settings.my_redis import pubsub_manager


async def broadcast_updated_statistics() -> None:
    await pubsub_manager.publish(topic="statistics", data={})
