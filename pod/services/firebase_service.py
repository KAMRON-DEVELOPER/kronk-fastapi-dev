import asyncio
from functools import partial

from firebase_admin import auth, credentials, initialize_app
from firebase_admin.auth import UserRecord

from settings.my_config import get_settings
from settings.my_exceptions import NotFoundException, ValidationException
from utility.my_logger import my_logger

settings = get_settings()


def initialize_firebase():
    try:
        cred = credentials.Certificate(cert="/run/secrets/FIREBASE_ADMINSDK_PROD" if not settings.DEBUG else settings.firebase_adminsdk_dev)
        default_app = initialize_app(credential=cred)
        my_logger.debug(f"firebase default_app.project_id: {default_app.project_id}, default_app.name: {default_app.name}")
    except Exception as e:
        my_logger.exception(f"initialization error: {e}")


async def validate_firebase_token(firebase_id_token: str) -> UserRecord:
    """
    Validate the Firebase ID token and return the Firebase user object if valid.
    """
    try:
        # Verify the token asynchronously
        decoded_token: dict = await asyncio.to_thread(partial(auth.verify_id_token, firebase_id_token))
        print(f"🔨 decoded_token in validate_firebase_token: {decoded_token}")

        # Retrieve user information from Firebase
        user = await asyncio.to_thread(partial(auth.get_user, decoded_token.get("uid")))
        return user
    except auth.InvalidIdTokenError:
        raise ValidationException("🔥 Invalid Firebase ID token.")
    except auth.UserNotFoundError:
        raise NotFoundException("🔥 User not found in Firebase.")
    except Exception as exception:
        raise ValidationException(f"🔥 Firebase token validation failed: {exception}")
