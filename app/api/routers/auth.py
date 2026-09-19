"""auth.py — 認證 API 路由模組。"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import get_auth_service
from app.api.schemas.auth import TokenRequest, TokenResponse
from app.api.schemas.common import ErrorResponse
from app.services.auth_api_service import AuthApiService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/token",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "認證失敗"}},
    summary="取得 JWT Access Token",
)
async def login_for_access_token(
    payload: TokenRequest,
    auth_service: AuthApiService = Depends(get_auth_service),
) -> TokenResponse:
    """透過帳號與密碼或 API 金鑰驗證身分並取得 JWT Bearer Token。"""
    is_authenticated = auth_service.authenticate_user(payload.username, payload.password)
    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = auth_service.create_access_token(payload.username)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
    )
