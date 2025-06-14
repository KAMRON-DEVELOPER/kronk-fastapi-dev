from fastapi.exceptions import HTTPException


class ApiException(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


class NotFoundException(ApiException):
    def __init__(self, detail: str):
        super().__init__(status_code=404, detail=detail)


class AlreadyExistException(ApiException):
    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)


class ValidationException(ApiException):
    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)


class UnauthorizedException(ApiException):
    def __init__(self, detail: str):
        super().__init__(status_code=401, detail=detail)


class JWTDecodeException(ApiException):
    def __init__(self, detail="Invalid JWT token"):
        super().__init__(status_code=401, detail=detail)


class JWTExpiredException(ApiException):
    def __init__(self, detail="Token expired"):
        super().__init__(status_code=401, detail=detail)


class JWTSignatureException(ApiException):
    def __init__(self, detail="Invalid token signature"):
        super().__init__(status_code=401, detail=detail)


class HeaderTokenException(ApiException):
    def __init__(self, detail: str):
        super().__init__(status_code=401, detail=detail)
