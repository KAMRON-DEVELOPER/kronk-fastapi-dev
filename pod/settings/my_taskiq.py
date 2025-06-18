
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend, RedisScheduleSource
from settings.my_config import get_settings
import taskiq_fastapi

settings = get_settings()

redis_schedule_source = RedisScheduleSource(url=settings.TASKIQ_REDIS_SCHEDULE_SOURCE_URL)

broker = ListQueueBroker(
    url=settings.TASKIQ_WORKER_URL,
).with_result_backend(result_backend=RedisAsyncResultBackend(redis_url=settings.TASKIQ_SCHEDULER_URL, result_ex_time=600))


scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker=broker), redis_schedule_source],
)

taskiq_fastapi.init(broker, "pod:main:app")