from random import randint
from typing import Optional, Annotated
from uuid import UUID

from bcrypt import checkpw, gensalt, hashpw
from fastapi import APIRouter, HTTPException, UploadFile, Form, File
from firebase_admin.auth import UserRecord
from sqlalchemy import select, exists

from apps.users_app.models import UserModel, FollowModel
from apps.users_app.schemas import (
    ForgotPasswordTokenSchema,
    LoginSchema,
    ProfileSchema,
    RegisterSchema,
    RegistrationTokenSchema,
    RequestForgotPasswordSchema,
    ResetPasswordSchema,
    ResultSchema,
    TokenSchema,
    VerifySchema, ProfileTokenSchema, UserSearchResponseSchema, ProfileSearchSchema, ProfileUpdateSchema,
)
from apps.users_app.tasks import add_follow_to_db, delete_follow_from_db, notify_settings_stats, send_email_task
from services.firebase_service import validate_firebase_token
from settings.my_database import DBSession
from settings.my_dependency import create_jwt_token, headerTokenDependency, strictJwtDependency, jwtDependency
from settings.my_exceptions import AlreadyExistException, HeaderTokenException, NotFoundException, ValidationException
from settings.my_minio import put_object_to_minio, remove_objects_from_minio, wipe_objects_from_minio
from settings.my_redis import cache_manager
from utility.my_enums import FollowStatus, FollowPolicy
from utility.my_logger import my_logger
from utility.utility import generate_avatar_url, generate_password_string, generate_unique_username
from utility.validators import allowed_image_extension, get_file_extension, get_image_dimensions

users_router = APIRouter()


@users_router.post(path="/auth/register", response_model=RegistrationTokenSchema, status_code=201)
async def register_route(schema: RegisterSchema, htd: headerTokenDependency) -> dict[str, str]:
    if htd.verify_token is not None:
        if await cache_manager.exists(name=f"tokens:registration:{htd.verify_token}"):
            raise HeaderTokenException(detail="Check your email! Your verification token is on its way.")

    is_username_pending, is_email_pending = await cache_manager.is_username_or_email_pending(username=schema.username, email=schema.email)
    if is_username_pending:
        raise ValueError("Someone is already registering with this username.")
    if is_email_pending:
        raise ValueError("Someone is already registering with this email.")

    is_username_taken, is_email_taken = await cache_manager.is_username_or_email_taken(username=schema.username, email=schema.email)
    if is_username_taken:
        raise AlreadyExistException(detail="Username already exists.")
    if is_email_taken:
        raise AlreadyExistException(detail="Email already exists.")

    code = "".join([str(randint(a=0, b=9)) for _ in range(4)])
    mapping = {**schema.model_dump(), "code": code}
    verify_token, verify_token_expiration_date = await cache_manager.set_registration_credentials(mapping=mapping)

    await send_email_task.kiq(to_email=schema.email, username=schema.name, code=code)

    return {"verify_token": verify_token, "verify_token_expiration_date": verify_token_expiration_date}


@users_router.post(path="/auth/verify", response_model=ProfileTokenSchema, status_code=200)
async def verify_route(htd: headerTokenDependency, schema: VerifySchema, session: DBSession):
    if htd.verify_token is None:
        raise HeaderTokenException(detail="Your verification token is missing.")

    cache: Optional[dict] = await cache_manager.get_registration_credentials(verify_token=htd.verify_token)
    if cache is None:
        raise NotFoundException(detail="Your verify token was not found.")

    if schema.code != cache.get("code"):
        raise ValidationException(detail="Your verification code is incorrect.")

    user = UserModel(name=cache.get("name"), username=cache.get("username"), email=cache.get("email"),
                     password=hashpw(password=cache.get("password", "").encode(), salt=gensalt(rounds=8)).decode())
    session.add(instance=user)
    await session.commit()
    await session.refresh(instance=user)

    await cache_manager.remove_registration_credentials(verify_token=htd.verify_token)

    await cache_manager.incr_statistics()

    await notify_settings_stats.kiq()
    await send_email_task.kiq(to_email=cache.get("email", ""), username=cache.get("username", ""), for_thanks_signing_up=True)

    return await cache_profile(user=user)


@users_router.post(path="/auth/login", response_model=ProfileTokenSchema, status_code=200)
async def login_route(schema: LoginSchema, session: DBSession):
    # 1. Try from cache
    search_results = await cache_manager.search_user(query=schema.username, limit=1)
    my_logger.debug(f"user_search_results: {search_results}")
    if len(search_results) > 0:
        user_data: dict = search_results.pop()
        user_id = user_data.get("id", "")
        user_password = user_data.get("password", "")
        if not checkpw(schema.password.encode(), user_password.encode()):
            raise ValidationException("password is not match.")
        token = generate_token(user_id=user_id)
        my_logger.debug(f"token: {token}")
        return token

    # 2. Fallback to DB
    stmt = select(UserModel).where(UserModel.username == schema.username)
    result = await session.execute(stmt)
    user: Optional[UserModel] = result.scalar_one_or_none()

    if not user:
        raise NotFoundException("User not found.")

    if not checkpw(schema.password.encode(), user.password.encode()):
        raise ValidationException("password is not match.")

    return await cache_profile(user=user)


@users_router.post(path="/auth/logout", response_model=ResultSchema, status_code=200)
async def logout_route(jwt: strictJwtDependency, session: DBSession):
    db_user: Optional[UserModel] = await session.get(UserModel, jwt.user_id)
    if not db_user:
        return {"ok": False}
    return {"ok": True}


@users_router.post(path="/auth/request-forgot-password", response_model=ForgotPasswordTokenSchema, status_code=200)
async def request_forgot_password_route(schema: RequestForgotPasswordSchema, session: DBSession):
    stmt = select(UserModel).where(UserModel.email == schema.email)
    result = await session.execute(stmt)
    user: Optional[UserModel] = result.scalar_one_or_none()

    if not user:
        raise NotFoundException(detail="No user found with this email.")

    code: str = "".join([str(randint(a=0, b=9)) for _ in range(4)])
    forgot_password_token, forgot_password_token_expiration_date = await cache_manager.set_forgot_password_credentials(mapping={"email": schema.email, "code": code})

    await send_email_task.kiq(to_email=schema.email, username=user.username, for_forgot_password=True, code=code)

    return {"forgot_password_token": forgot_password_token, "forgot_password_token_expiration_date": forgot_password_token_expiration_date}


@users_router.post(path="/auth/forgot-password", response_model=ProfileTokenSchema, status_code=200)
async def forgot_password_route(schema: ResetPasswordSchema, htd: headerTokenDependency, session: DBSession):
    if not htd.forgot_password_token:
        raise HeaderTokenException(detail="Reset password token is missing in the headers.")

    cache: Optional[dict] = await cache_manager.get_forgot_password_credentials(forgot_password_token=htd.forgot_password_token)
    if cache is None:
        raise HeaderTokenException("Your reset password token has expired. Please request a new one.")

    if schema.code != cache.get("code"):
        raise ValidationException("Your code is incorrect.")

    stmt = select(UserModel).where(UserModel.email == cache.get("email"))
    result = await session.execute(stmt)
    user: Optional[UserModel] = result.scalar_one_or_none()

    if user is None:
        raise NotFoundException("User not found with this email.")

    if checkpw(password=schema.new_password.encode(), hashed_password=user.password.encode()):
        raise ValidationException("Your new password must be different from the previous one.")

    new_hashed_password = hashpw(password=schema.new_password.encode(), salt=gensalt(rounds=8))

    user.password = new_hashed_password.decode()
    await session.commit()
    await session.refresh(instance=user)

    await cache_manager.remove_forgot_password_credentials(forgot_password_token=htd.forgot_password_token)

    return await cache_profile(user=user)


@users_router.post(path="/auth/social/google", response_model=ProfileTokenSchema, status_code=200)
async def google_auth_route(htd: headerTokenDependency, session: DBSession):
    if not htd.firebase_id_token:
        raise HeaderTokenException("Firebase ID token is missing in the headers.")

    firebase_user: UserRecord = await validate_firebase_token(htd.firebase_id_token)

    stmt = select(UserModel).where(UserModel.email == firebase_user.email)
    result = await session.execute(stmt)
    user: Optional[UserModel] = result.scalar_one_or_none()

    if user is not None:
        return await cache_profile(user=user)

    username: str = generate_unique_username(base_name=f"{firebase_user.display_name}")
    password_string: str = generate_password_string()

    new_user = UserModel(username=username, email=firebase_user.email, password=hashpw(password=password_string.encode(), salt=gensalt(rounds=8)).decode())
    session.add(instance=new_user)
    await session.commit()
    await session.refresh(instance=new_user)

    if firebase_user.photo_url:
        avatar_url: Optional[str] = await generate_avatar_url(image_url=firebase_user.photo_url, user_id=new_user.id)
        if avatar_url:
            new_user.avatar_url = avatar_url
            await session.commit()
            await session.refresh(instance=new_user)

    await cache_manager.incr_statistics()
    await notify_settings_stats.kiq()
    await send_email_task.kiq(to_email=new_user.email, username=new_user.username, for_thanks_signing_up=True)

    return await cache_profile(user=new_user)


@users_router.get(path="/profile", response_model=ProfileSearchSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def get_profile_route(jwt: strictJwtDependency, session: DBSession, target_user_id: Optional[str] = None):
    my_logger.info(f"target_user_id: {target_user_id}, type: {type(target_user_id)}")
    cached_user: Optional[dict] = await cache_manager.get_profile(user_id=jwt.user_id.hex, target_user_id=target_user_id)

    my_logger.debug(f"user in redis(cached_user): {cached_user}")
    if cached_user:
        return cached_user

    user_id = target_user_id or jwt.user_id
    user: Optional[UserModel] = await session.get(UserModel, user_id)
    is_following: Optional[bool] = None
    if target_user_id is not None:
        exists_stmt = select(FollowModel.id).where(FollowModel.follower_id == jwt.user_id, FollowModel.following_id == target_user_id,
                                                   FollowModel.follow_status == FollowStatus.accepted)
        is_following = await session.scalar(select(exists(exists_stmt)))

    if not user:
        raise ValueError("User not found")

    return await cache_profile(user=user, user_id=jwt.user_id.hex, is_following=is_following)


@users_router.patch(path="/profile/update", response_model=ResultSchema, status_code=200)
async def update_profile_route(jwt: strictJwtDependency, session: DBSession,
                               name: Annotated[Optional[str], Form()] = None,
                               username: Annotated[Optional[str], Form()] = None,
                               email: Annotated[Optional[str], Form()] = None,
                               password: Annotated[Optional[str], Form()] = None,
                               birthdate: Annotated[Optional[str], Form()] = None,
                               bio: Annotated[Optional[str], Form()] = None,
                               country: Annotated[Optional[str], Form()] = None,
                               city: Annotated[Optional[str], Form()] = None,
                               follow_policy: Annotated[Optional[FollowPolicy], Form()] = None,
                               avatar_file: Annotated[Optional[UploadFile], File()] = None,
                               banner_file: Annotated[Optional[UploadFile], File()] = None,
                               remove_avatar: Annotated[bool, Form()] = False,
                               remove_banner: Annotated[bool, Form()] = False):
    try:
        user: Optional[UserModel] = await session.get(UserModel, jwt.user_id)
        if not user:
            raise NotFoundException("User not found.")

        ''' Remove Avatar & Banner image'''
        if remove_avatar:
            if user.avatar_url is not None:
                await remove_objects_from_minio(object_names=[user.avatar_url])
            # user.avatar_url = None
            # await cache_manager.update_profile(user_id=user.id.hex, key="avatar_url", value=None)
            my_logger.info("avatar removed successfully")
        if remove_banner:
            if user.banner_url is not None:
                await remove_objects_from_minio(object_names=[user.banner_url])
            # user.banner_url = None
            # await cache_manager.update_profile(user_id=user.id.hex, key="banner_url", value=None)
            my_logger.info("banner removed successfully")

        ''' Set Avatar & Banner image'''
        if avatar_file is not None:
            avatar_file_extension = get_file_extension(file=avatar_file)
            if avatar_file_extension not in allowed_image_extension:
                raise ValidationException(detail="Only PNG, JPG, and JPEG formats are allowed for avatar")

            avatar_bytes: bytes = await avatar_file.read()

            avatar_image_width, avatar_image_height = get_image_dimensions(image_bytes=avatar_bytes)
            if avatar_image_width != avatar_image_height:
                raise ValidationException(detail="Width and height of the avatar image must be equal.")
            if avatar_image_width > 1024:
                raise ValidationException(detail="Avatar image dimensions exceeded limit 400x400px.")
            if len(avatar_bytes) > 2 * 1024 * 1024:
                raise ValidationException(detail="Avatar image size exceeded limit 2MB.")

            avatar_object_name = f"users/{jwt.user_id.hex}/avatar.{avatar_file_extension}"
            avatar_url: str = await put_object_to_minio(object_name=avatar_object_name, data=avatar_bytes)
            # user.avatar_url = avatar_url
            # await cache_manager.update_profile(user_id=user.id.hex, key="avatar_url", value=avatar_url)
            my_logger.info("avatar updated successfully")

        if banner_file is not None:
            banner_file_extension = get_file_extension(file=banner_file)
            if banner_file_extension not in allowed_image_extension:
                raise ValidationException(detail="Only PNG, JPG, and JPEG formats are allowed for banner")

            banner_bytes = await banner_file.read()

            banner_image_width, banner_image_height = get_image_dimensions(image_bytes=banner_bytes)
            if banner_image_width / banner_image_height == 16 / 9:
                raise ValidationException(detail="Width and height of the banner image must be equal.")
            if len(banner_bytes) > 2 * 1024 * 1024:
                raise ValidationException(detail="Banner image size exceeded limit 2MB.")

            banner_object_name = f"users/{jwt.user_id.hex}/banner.{banner_file_extension}"
            banner_url: str = await put_object_to_minio(object_name=banner_object_name, data=banner_bytes)
            # user.banner_url = banner_url
            # await cache_manager.update_profile(user_id=user.id.hex, key="banner_url", value=banner_url)
            my_logger.info("banner updated successfully")

        ''' Field updating '''
        profile_schema = ProfileSchema.model_validate(obj=user)

        profile_dict = profile_schema.model_dump()
        update_dict = ProfileUpdateSchema(
            name=name,
            username=username,
            email=email,
            password=password,
            birthdate=birthdate,
            bio=bio,
            country=country,
            city=city,
            follow_policy=follow_policy
        ).model_dump()

        must_not_be_null_fields = ["username", "email", "password", "follow_policy"]

        for field in must_not_be_null_fields:
            if field in update_dict and update_dict[field] is None:
                raise ValidationException(detail=f"Field '{field}' must not be null.")

        if "password" in update_dict:
            if checkpw(update_dict["password"].encode(), user.password.encode()):
                update_dict.pop("password", None)
            else:
                update_dict["password"] = hashpw(update_dict["password"].encode(), gensalt(8)).decode()

        my_logger.info(f"profile_dict: {profile_dict}")
        my_logger.info(f"update_dict: {update_dict}")

        update_data = {key: value for key, value in update_dict.items() if profile_dict.get(key) != value}

        my_logger.info(f"must update data: {update_data}")

        # if update_data:
        #     for key, value in update_data.items():
        #         user.__setattr__(key, value)
        #         await cache_manager.update_profile(user_id=user.id.hex, key=key, value=value)

        # session.add(user)

        # await session.commit()
        return {"ok": True}
    except Exception as e:
        my_logger.debug(f"Exception e: {e}")
        return {"ok": False}


@users_router.delete(path="/profile/delete", response_model=ResultSchema, status_code=200)
async def delete_profile_route(jwt: strictJwtDependency, session: DBSession):
    user: Optional[UserModel] = await session.get(UserModel, jwt.user_id)

    if user is None:
        return {"ok": False}

    # delete all media files
    await wipe_objects_from_minio(user_id=jwt.user_id.hex)

    # delete from redis
    await cache_manager.delete_profile(user_id=jwt.user_id.hex)

    # delete from database
    await session.delete(instance=user)
    await session.commit()

    return {"ok": True}


@users_router.post(path="/follow", response_model=ResultSchema, status_code=200)
async def follow_route(jwt: strictJwtDependency, following_id: UUID):
    if jwt.user_id == following_id:
        raise ValidationException(detail="Are you piece of human shit! Cannot follow yourself")

    await cache_manager.add_follower(user_id=jwt.user_id.hex, following_id=following_id.hex)

    await add_follow_to_db.kiq(user_id=jwt.user_id, following_id=following_id)

    return {"ok": True}


@users_router.post(path="/unfollow", response_model=ResultSchema, status_code=200)
async def unfollow_route(jwt: strictJwtDependency, following_id: UUID):
    if jwt.user_id == following_id:
        raise ValidationException(detail="Are you piece of human shit! Cannot follow yourself")

    await cache_manager.remove_follower(user_id=jwt.user_id.hex, following_id=following_id.hex)

    await delete_follow_from_db.kiq(user_id=jwt.user_id, following_id=following_id)
    return {"ok": True}


@users_router.get(path="/followers", status_code=200)
async def get_followers_route(jwt: strictJwtDependency):
    return await cache_manager.get_followers(user_id=jwt.user_id.hex)


@users_router.get(path="/followings", status_code=200)
async def get_followings_route(jwt: strictJwtDependency):
    return await cache_manager.get_following(user_id=jwt.user_id.hex)


@users_router.post(path="/auth/access", response_model=TokenSchema, status_code=200)
async def refresh_access_token_route(jwt: strictJwtDependency):
    access_token: str = create_jwt_token(subject={"id": jwt.user_id.hex})
    return {"access_token": access_token}


@users_router.post(path="/auth/refresh", response_model=TokenSchema, status_code=200)
async def refresh_refresh_token_route(jwt: strictJwtDependency):
    subject = {"id": jwt.user_id.hex}
    access_token = create_jwt_token(subject=subject)
    refresh_token = create_jwt_token(subject=subject, for_refresh=True)
    return {"access_token": access_token, "refresh_token": refresh_token}


@users_router.get(path="/search", response_model=UserSearchResponseSchema, response_model_exclude_none=True, response_model_exclude_defaults=True, status_code=200)
async def user_search(jwt: jwtDependency, query: str, offset: int = 0, limit: int = 10):
    try:
        users = await cache_manager.search_user(query=query, user_id=jwt.user_id.hex if jwt is not None else None, offset=offset, limit=limit)
        schm = UserSearchResponseSchema(**users)
        my_logger.debug(f"schm.model_dump(): {schm.model_dump(exclude_defaults=True, exclude_none=True)}")
        return users
    except Exception as exception:
        my_logger.critical(f"Exception in user_search: {exception}")
        raise HTTPException(status_code=500, detail="🤯 WTF? Something just exploded on our end. Try again later!")


def generate_token(user_id: str) -> dict:
    subject = {"id": user_id}
    return {"access_token": create_jwt_token(subject=subject), "refresh_token": create_jwt_token(subject=subject, for_refresh=True)}


async def cache_profile(user: UserModel, user_id: Optional[str] = None, is_following: Optional[bool] = None) -> dict:
    profile_schema = ProfileSchema.model_validate(obj=user)
    mapping = profile_schema.model_dump(exclude_unset=True, exclude_defaults=True, exclude_none=True, mode="json")

    await cache_manager.create_profile(mapping=mapping, user_id=user_id, is_following=is_following)

    if is_following is not None:
        mapping.update({"is_following": is_following})

    my_logger.debug("profile caching to redis...")
    my_logger.debug(f"mapping: {mapping}")

    return {"user": mapping, "tokens": generate_token(user_id=user.id.hex)}
