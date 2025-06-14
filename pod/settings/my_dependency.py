from datetime import UTC, datetime, timedelta
from typing import Annotated, Optional
from uuid import UUID

from authlib.jose import JWTClaims, jwt
from authlib.jose.errors import BadSignatureError, DecodeError, ExpiredTokenError, InvalidTokenError, KeyMismatchError
from fastapi import Depends, Header, WebSocket, WebSocketException, status

from settings.my_config import get_settings
from settings.my_exceptions import ApiException, JWTDecodeException, JWTExpiredException, JWTSignatureException, UnauthorizedException

settings = get_settings()


class HeaderTokensCredential:
    def __init__(self, verify_token: Optional[str], forgot_password_token: Optional[str], firebase_id_token: Optional[str]):
        self.verify_token: Optional[str] = verify_token
        self.forgot_password_token: Optional[str] = forgot_password_token
        self.firebase_id_token: Optional[str] = firebase_id_token


class JWTCredential:
    def __init__(self, user_id: UUID):
        self.user_id = user_id


class WebsocketCredential:
    def __init__(self, user_id: UUID, websocket: WebSocket):
        self.user_id = user_id
        self.websocket = websocket


def header_tokens_resolver(
    verify_token: Optional[str] = Header(default=None),
    forgot_password_token: Optional[str] = Header(default=None),
    firebase_id_token: Optional[str] = Header(default=None),
):
    return HeaderTokensCredential(verify_token=verify_token, forgot_password_token=forgot_password_token, firebase_id_token=firebase_id_token)


def jwt_resolver(authorization: str = Header(default=None)) -> JWTCredential:
    """FastAPI Security Dependency to verify JWT token."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Invalid or missing token.")

    token = authorization.split(" ")[1]
    return verify_jwt_token(token)


async def websocket_resolver(websocket: WebSocket) -> WebsocketCredential:
    """Extract and verify JWT from WebSocket headers."""
    token = websocket.headers.get("Authorization")

    if not token or not token.startswith("Bearer "):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    jwt_credential = verify_jwt_token(token=token.split(" ")[1])
    return WebsocketCredential(user_id=jwt_credential.user_id, websocket=websocket)


def create_jwt_token(subject: dict, for_refresh: bool = False) -> str:
    """Generate a JWT token using Authlib."""
    header = {"alg": settings.ALGORITHM}

    access_exp = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_TIME)
    refresh_exp = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_TIME)

    exp = refresh_exp if for_refresh else access_exp

    payload = {"exp": exp, "sub": subject}
    return jwt.encode(header=header, payload=payload, key=settings.SECRET_KEY.encode(encoding="utf-8")).decode("utf-8")


def verify_jwt_token(token: str) -> JWTCredential:
    """Verify and decode a JWT token."""
    try:
        decoded: JWTClaims = jwt.decode(s=token, key=settings.SECRET_KEY.encode(encoding="utf-8"))
        decoded.validate()

        # my_logger.debug(f"decoded: {decoded}")

        subject: dict | None = decoded.get("sub")
        if not subject:
            raise ValueError("Missing subject in token.")

        user_id: str | None = subject.get("id")
        if not user_id:
            raise ValueError("Missing user ID in token subject.")

        return JWTCredential(user_id=UUID(user_id))

    except KeyError:
        raise JWTDecodeException("Malformed token payload")
    except BadSignatureError:
        raise JWTSignatureException()
    except ExpiredTokenError:
        raise JWTExpiredException()
    except (DecodeError, InvalidTokenError, KeyMismatchError) as e:
        raise JWTDecodeException(detail=str(e))
    except Exception as e:
        raise ApiException(status_code=401, detail=f"Unknown JWT error, {e}")


headerTokenDependency = Annotated[HeaderTokensCredential, Depends(dependency=header_tokens_resolver)]
jwtDependency = Annotated[JWTCredential, Depends(dependency=jwt_resolver)]
websocketDependency = Annotated[WebsocketCredential, Depends(dependency=websocket_resolver)]
