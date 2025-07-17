from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend, RedisScheduleSource

from settings.my_config import get_settings

settings = get_settings()

broker = ListQueueBroker(
    url=settings.REDIS_URL,
).with_result_backend(result_backend=RedisAsyncResultBackend(redis_url=settings.REDIS_URL, result_ex_time=600))

redis_schedule_source = RedisScheduleSource(url=settings.REDIS_URL)

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker=broker), redis_schedule_source],
)
