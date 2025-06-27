from fastapi import APIRouter

from apps.chats_app.schemas import ChatTileResponseSchema
from apps.users_app.schemas import ResultSchema
from settings.my_database import DBSession
from settings.my_dependency import strictJwtDependency
from settings.my_exceptions import ApiException
from settings.my_redis import chat_cache_manager
from utility.my_logger import my_logger

chats_router = APIRouter()


@chats_router.post(path="/tile/create", response_model=ResultSchema, status_code=200)
async def create_chat_tile_route(jwt: strictJwtDependency, session: DBSession):
    try:
        # todo

        return {"ok": True}
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")


@chats_router.post(path="/tile/delete", response_model=ResultSchema, status_code=200)
async def delete_chat_tile_route(jwt: strictJwtDependency):
    try:
        # todo

        return {"ok": True}
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")


@chats_router.get(path="/tiles", response_model=ChatTileResponseSchema, status_code=200)
async def get_chat_tiles_route(jwt: strictJwtDependency):
    try:
        response: ChatTileResponseSchema = await chat_cache_manager.get_chat_tiles(user_id=jwt.user_id.hex)
        my_logger.debug(f"length of response.chat_tiles: {len(response.chat_tiles)}, response.end: {response.end}")
        return response
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")
