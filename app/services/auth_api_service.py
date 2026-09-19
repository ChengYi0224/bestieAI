"""auth_api_service.py — API 認證與 JWT Token 業務邏輯服務。"""
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import bcrypt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from jose import JWTError, jwt

from app.core.config import settings
from app.storage.repositories.users import UserRepository


class AuthApiService:
    """提供 REST API 雙軌認證（Google OAuth + 原生帳密）與 JWT Bearer Token 生成與驗證服務。"""

    def __init__(
        self,
        user_repo: Optional[UserRepository] = None,
        secret_key: Optional[str] = None,
        expire_hours: Optional[int] = None,
    ):
        self.user_repo = user_repo or UserRepository()
        self.secret_key = secret_key or settings.API_SECRET
        self.expire_hours = expire_hours if expire_hours is not None else settings.API_TOKEN_EXPIRE_HOURS
        self.algorithm = "HS256"

    @staticmethod
    def hash_password(password: str) -> str:
        """使用 bcrypt 對密碼進行加鹽雜湊。"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """比對密碼與 bcrypt 雜湊值。"""
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except Exception:
            return False

    def register(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> sqlite3.Row:
        """註冊原生新帳號。"""
        clean_user = username.strip()
        if self.user_repo.get_by_username(clean_user):
            raise ValueError("此使用者名稱已被註冊")

        clean_email = email.strip() if email and email.strip() else None
        if clean_email and self.user_repo.get_by_email(clean_email):
            raise ValueError("此電子郵件已被註冊")

        pw_hash = self.hash_password(password)
        user_id = self.user_repo.create_user(
            username=clean_user,
            email=clean_email,
            password_hash=pw_hash,
            display_name=display_name or clean_user,
        )
        created = self.user_repo.get_by_id(user_id)
        if not created:
            raise RuntimeError("建立使用者失敗")
        return created

    def authenticate_with_password(self, username_or_email: str, password: str) -> Optional[sqlite3.Row]:
        """使用原生帳號或信箱搭配密碼進行身分驗證。"""
        if not username_or_email or not password:
            return False

        clean_id = username_or_email.strip()
        user = self.user_repo.get_by_username(clean_id) or self.user_repo.get_by_email(clean_id)

        if user and user["password_hash"]:
            if self.verify_password(password, user["password_hash"]):
                return user

        # 向後相容：比對 API_SECRET 或主帳號密碼（預設管理者身分）
        valid_secrets = [s for s in [self.secret_key, settings.MAIN_ACCOUNT_PASSWORD] if s]
        for secret in valid_secrets:
            if secrets.compare_digest(password, secret):
                admin_user = self.user_repo.get_by_id(1)
                if admin_user:
                    return admin_user

        return None

    def authenticate_user(self, username: str, password: str) -> bool:
        """向後相容判斷：驗證使用者帳密是否合法。"""
        return self.authenticate_with_password(username, password) is not None

    def authenticate_with_google(self, id_token_str: str) -> sqlite3.Row:
        """驗證 Google ID Token 並依優先序綁定管理者、現有用戶或自動註冊新帳號。"""
        audiences = settings.google_client_ids_list
        try:
            id_info = google_id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                audience=audiences if audiences else None,
            )
        except Exception as e:
            raise ValueError(f"Google Token 驗證失敗: {e}")

        google_sub = str(id_info.get("sub", "")).strip()
        email = str(id_info.get("email", "")).strip() if id_info.get("email") else None
        name = str(id_info.get("name", "")).strip() if id_info.get("name") else None
        avatar_url = str(id_info.get("picture", "")).strip() if id_info.get("picture") else None

        if not google_sub:
            raise ValueError("無效的 Google Token：遺失 sub 識別碼")

        # 1. 若該 Google sub 已綁定，直接回傳
        existing_sub = self.user_repo.get_by_google_sub(google_sub)
        if existing_sub:
            return existing_sub

        # 2. 若登入之信箱符合 ADMIN_EMAIL，自動綁定至管理者帳號 (user_id = 1)
        admin_email = settings.ADMIN_EMAIL.strip().lower() if settings.ADMIN_EMAIL else None
        if email and admin_email and email.lower() == admin_email:
            self.user_repo.link_google_sub(1, google_sub, avatar_url=avatar_url, email=email)
            admin_user = self.user_repo.get_by_id(1)
            if admin_user:
                return admin_user

        # 3. 若同信箱之用戶已存在，綁定至該用戶
        if email:
            existing_email_user = self.user_repo.get_by_email(email)
            if existing_email_user:
                self.user_repo.link_google_sub(
                    existing_email_user["id"],
                    google_sub,
                    avatar_url=avatar_url,
                    email=email,
                )
                return self.user_repo.get_by_id(existing_email_user["id"])

        # 4. 全新 Google 使用者：自動建立新帳號
        base_username = email.split("@")[0] if email else f"google_user_{google_sub[:6]}"
        candidate_username = base_username
        suffix = 1
        while self.user_repo.get_by_username(candidate_username):
            candidate_username = f"{base_username}_{suffix}"
            suffix += 1

        new_user_id = self.user_repo.create_user(
            username=candidate_username,
            email=email,
            google_sub=google_sub,
            display_name=name or candidate_username,
            avatar_url=avatar_url,
        )
        new_user = self.user_repo.get_by_id(new_user_id)
        if not new_user:
            raise RuntimeError("建立 Google 使用者失敗")
        return new_user

    def create_access_token(self, user_id: int, username: str) -> Tuple[str, int]:
        """簽發 JWT Access Token，payload 內含 sub (user_id) 與 username。"""
        expires_delta = timedelta(hours=self.expire_hours)
        expire_time = datetime.now(timezone.utc) + expires_delta
        expires_in = int(expires_delta.total_seconds())

        payload = {
            "sub": str(user_id),
            "username": username,
            "exp": expire_time,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token, expires_in

    def verify_token(self, token: str) -> Optional[Tuple[int, str]]:
        """驗證 JWT Access Token 並取得 (user_id, username)。"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            sub_raw = payload.get("sub")
            if not sub_raw:
                return None

            try:
                user_id = int(sub_raw)
            except ValueError:
                # 相容舊版 subject 為 username 的 Token
                user_id = 1

            username = payload.get("username", "")
            return user_id, username
        except JWTError:
            return None
