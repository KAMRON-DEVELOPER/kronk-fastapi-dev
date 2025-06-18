from contextlib import asynccontextmanager

import taskiq_fastapi
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from firebase_admin import credentials, initialize_app
from prometheus_fastapi_instrumentator import Instrumentator

from apps.admin_app.routes import admin_router
from apps.admin_app.ws import admin_ws_router
from apps.chats_app.routes import chats_router
from apps.chats_app.ws import chat_ws_router
from apps.feeds_app.routes import feed_router
from apps.feeds_app.ws import feed_ws_router
from apps.users_app.routes import users_router
from settings.my_config import get_settings
from settings.my_database import initialize_db
from settings.my_exceptions import ApiException
from settings.my_redis import initialize_redis_indexes
from settings.my_taskiq import broker
from utility.my_logger import my_logger

settings = get_settings()


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    await initialize_redis_indexes()
    await initialize_db()
    instrumentator.expose(_app)
    if not broker.is_worker_process:
        print("Starting broker")
        await broker.startup()
    yield
    if not broker.is_worker_process:
        print("Shutting down broker")
        await broker.shutdown()


app: FastAPI = FastAPI(lifespan=app_lifespan)
instrumentator = Instrumentator().instrument(app)

taskiq_fastapi.init(broker=broker, app_or_path=app)


@app.exception_handler(ApiException)
async def api_exception_handler(request: Request, exception: ApiException):
    my_logger.exception(f"HTTP {exception.status_code} error {request.url.path} detail: {exception.detail}")
    return JSONResponse(status_code=exception.status_code, content={"details": exception.detail}, headers=exception.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exception: RequestValidationError):
    details = []

    for error in exception.errors():
        my_logger.critical(f"error: {error}")
        ctx = error.get("ctx", {})
        if "error" in ctx:
            details.append(str(ctx["error"]))
        else:
            loc = error.get("loc", [])
            msg = error.get("msg", "")
            if len(loc) > 1:
                field = str(loc[1]).capitalize()
                details.append(f"{field} {msg.lower()}")

    my_logger.warning(f"HTTP validation error during {request.method} {request.url.path}, details: {details}")
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"details": details})


try:
    cred = credentials.Certificate(cert="/run/secrets/FIREBASE_ADMINSDK_PROD" if settings.DEBUG else settings.FIREBASE_ADMINSDK_DEV)
    default_app = initialize_app(credential=cred)
    my_logger.debug(f"default_app.project_id: {default_app.project_id}")
    my_logger.debug(f"default_app.project_id: {default_app.name}")
except Exception as e:
    print(f"initialization error: {e}")


@app.get(path="/", tags=["root"])
async def root() -> dict:
    return {"status": "ok"}


# HTTP Routes
app.include_router(router=users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(router=feed_router, prefix="/api/v1/feeds", tags=["feeds"])
app.include_router(router=chats_router, prefix="/api/v1/chats", tags=["chats"])
app.include_router(router=admin_router, prefix="/api/v1/admin", tags=["admin"])

# Websocket Routes
app.include_router(router=admin_ws_router, prefix="/api/v1/admin", tags=["admin ws"])
app.include_router(router=feed_ws_router, prefix="/api/v1/feeds", tags=["feeds ws"])
app.include_router(router=chat_ws_router, prefix="/api/v1/chats", tags=["chat ws"])
