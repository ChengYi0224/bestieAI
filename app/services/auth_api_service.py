"""auth_api_service.py — API 認證與 JWT Token 業務邏輯服務。"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from app.core.config import settings


class AuthApiService:
    """提供 REST API 認證與 JWT Bearer Token 生成與驗證服務。"""

    def __init__(self, secret_key: Optional[str] = None, expire_hours: Optional[int] = None):
        self.secret_key = secret_key or settings.API_SECRET
        self.expire_hours = expire_hours if expire_hours is not None else settings.API_TOKEN_EXPIRE_HOURS
        self.algorithm = "HS256"

    def authenticate_user(self, username: str, password: str) -> bool:
        """
        驗證使用者身分。
        在 MVP 階段比對傳入密碼是否與 API_SECRET 或主帳號密碼相符。
        若有設定主帳號使用者名稱，則須一致。
        """
        if not username or not password:
            return False

        # 若設定了主帳號名稱，且傳入的使用者名稱不符則拒絕
        if settings.MAIN_ACCOUNT_USERNAME and username.strip() != settings.MAIN_ACCOUNT_USERNAME.strip():
            return False

        # 比對 API_SECRET 或主帳號密碼
        valid_secrets = [s for s in [self.secret_key, settings.MAIN_ACCOUNT_PASSWORD] if s]
        return password in valid_secrets

    def create_access_token(self, subject: str) -> tuple[str, int]:
        """
        簽發 JWT Access Token。
        回傳 (access_token, expires_in_seconds)。
        """
        expires_delta = timedelta(hours=self.expire_hours)
        expire_time = datetime.now(timezone.utc) + expires_delta
        expires_in = int(expires_delta.total_seconds())

        payload = {
            "sub": subject,
            "exp": expire_time,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token, expires_in

    def verify_token(self, token: str) -> Optional[str]:
        """
        驗證 JWT Access Token 並取得 subject (username)。
        若 Token 無效或已過期則回傳 None。
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            username: Optional[str] = payload.get("sub")
            return username
        except JWTError:
            return None
