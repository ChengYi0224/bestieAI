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
