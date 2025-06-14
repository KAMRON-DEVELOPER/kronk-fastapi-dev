import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from utility.my_logger import my_logger


class RequestCountMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.request_count = 0

    async def dispatch(self, request: Request, call_next):
        # Define routes to exclude from logging
        excluded_routes = ["/", "/health"]
        if request.url.path in excluded_routes:
            return await call_next(request)

        self.request_count += 1

        try:
            start_time = time.perf_counter()
            response = await call_next(request)
            stop_time = time.perf_counter()

            status_code = response.status_code
            message = f"{request.method} - {request.url} - Status: {status_code} - Time: {round((stop_time - start_time) * 1000)} ms - request count: {self.request_count}"
            print(f"📡 {message}")

            if 500 <= status_code < 600:
                my_logger.critical(message)
            elif 400 <= status_code < 500:
                my_logger.error(message)
            else:
                my_logger.info(message)

                return response
        except Exception as e:
            my_logger.error(f"Error processing request: {e}")
