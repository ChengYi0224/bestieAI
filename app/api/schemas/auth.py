"""auth.py — 認證相關 Pydantic Schema 定義。"""
from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    """認證 Token 請求模型。"""
    username: str = Field(description="使用者名稱或 IG 帳號")
    password: str = Field(description="密碼或 API 金鑰")


class TokenResponse(BaseModel):
    """認證 Token 回應模型。"""
    access_token: str = Field(description="JWT Access Token")
    token_type: str = Field(default="bearer", description="Token 類型")
    expires_in: int = Field(description="Token 有效秒數")


class RegisterRequest(BaseModel):
    """原生帳號註冊請求模型。"""
    username: str = Field(min_length=3, max_length=50, description="使用者名稱")
    password: str = Field(min_length=6, description="密碼")
    email: str | None = Field(default=None, description="電子郵件信箱（可選）")
    display_name: str | None = Field(default=None, description="顯示名稱（可選）")


class GoogleAuthRequest(BaseModel):
    """Google ID Token 登入請求模型。"""
    id_token: str = Field(description="Google 簽發之 ID Token 字串")


class UserResponse(BaseModel):
    """使用者基本資訊回應模型。"""
    id: int = Field(description="系統使用者流水號 user_id")
    username: str = Field(description="使用者名稱")
    email: str | None = Field(default=None, description="電子郵件信箱")
    display_name: str | None = Field(default=None, description="顯示名稱")
    avatar_url: str | None = Field(default=None, description="頭像連結")
    created_at: str | None = Field(default=None, description="建立時間")

    model_config = {"from_attributes": True, "extra": "ignore"}
