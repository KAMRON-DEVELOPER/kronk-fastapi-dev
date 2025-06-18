from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend, RedisScheduleSource

from settings.my_config import get_settings

settings = get_settings()

broker = ListQueueBroker(
    url=settings.TASKIQ_WORKER_URL,
).with_result_backend(result_backend=RedisAsyncResultBackend(redis_url=settings.TASKIQ_RESULT_BACKEND_URL, result_ex_time=600))

redis_schedule_source = RedisScheduleSource(url=settings.TASKIQ_REDIS_SCHEDULE_SOURCE_URL)

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker=broker), redis_schedule_source],
)
