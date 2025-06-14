import time
from typing import Any, Awaitable, Callable


async def measure_time(callback: Callable[[], Awaitable[Any]]) -> Any:
    starting_time = time.perf_counter()
    result = await callback()
    ending_time = time.perf_counter()

    time_taken = ending_time - starting_time
    print(f"⌛️ Result: {result}, Time Taken: {time_taken:.2f} seconds")

    return result
