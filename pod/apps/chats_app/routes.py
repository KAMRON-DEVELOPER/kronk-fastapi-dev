from fastapi import APIRouter

from apps.chats_app.schemas import ChatTileSchema
from apps.users_app.schemas import ResultSchema
from settings.my_database import DBSession
from settings.my_dependency import jwtDependency
from settings.my_exceptions import ApiException
from settings.my_redis import cache_manager
from utility.my_logger import my_logger

chats_router = APIRouter()


@chats_router.post(path="/tile/create", response_model=ResultSchema, status_code=200)
async def create_chat_tile_route(jwt: jwtDependency, session: DBSession):
    try:
        # todo

        return {"ok": True}
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")


@chats_router.post(path="/tile/delete", response_model=ResultSchema, status_code=200)
async def delete_chat_tile_route(jwt: jwtDependency):
    try:
        # todo

        return {"ok": True}
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")


@chats_router.get(path="/tiles", response_model=list[ChatTileSchema], status_code=200)
async def get_chats_tiles_route(jwt: jwtDependency):
    try:
        chat_tiles: list[ChatTileSchema] = await cache_manager.get_chat_tiles(user_id=jwt.user_id.hex)

        my_logger.debug(f"length of chat_tiles: {len(chat_tiles)}")

        return chat_tiles
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")
