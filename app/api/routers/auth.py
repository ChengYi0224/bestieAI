"""auth.py — 認證 API 路由模組。"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import get_auth_service, get_current_user
from app.api.schemas.auth import (
    GoogleAuthRequest,
    RegisterRequest,
    TokenRequest,
    TokenResponse,
    UserResponse,
)
from app.api.schemas.common import ErrorResponse
from app.services.auth_api_service import AuthApiService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse, "description": "註冊資料重複或無效"}},
    summary="原生帳號註冊",
)
async def register(
    payload: RegisterRequest,
    auth_service: AuthApiService = Depends(get_auth_service),
) -> UserResponse:
    """建立新的原生使用者帳號。"""
    try:
        user = auth_service.register(
            username=payload.username,
            password=payload.password,
            email=payload.email,
            display_name=payload.display_name,
        )
        return UserResponse.model_validate(dict(user))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/token",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "認證失敗"}},
    summary="帳號密碼登入取得 JWT Access Token",
)
async def login_for_access_token(
    payload: TokenRequest,
    auth_service: AuthApiService = Depends(get_auth_service),
) -> TokenResponse:
    """透過帳號或信箱搭配密碼驗證身分並取得 JWT Bearer Token。"""
    user = auth_service.authenticate_with_password(payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = auth_service.create_access_token(user_id=user["id"], username=user["username"])
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/google",
    response_model=TokenResponse,
    responses={400: {"model": ErrorResponse, "description": "Google Token 無效"}},
    summary="Google ID Token 登入或註冊",
)
async def login_with_google(
    payload: GoogleAuthRequest,
    auth_service: AuthApiService = Depends(get_auth_service),
) -> TokenResponse:
    """接收前端 Google ID Token 進行簽章驗證，自動查找/綁定/註冊使用者並回傳 JWT。"""
    try:
        user = auth_service.authenticate_with_google(payload.id_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    token, expires_in = auth_service.create_access_token(user_id=user["id"], username=user["username"])
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="取得目前登入使用者個人資料",
)
async def get_current_user_profile(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> UserResponse:
    """取得當前 Bearer Token 授權之使用者個人資訊。"""
    return UserResponse.model_validate(current_user)
