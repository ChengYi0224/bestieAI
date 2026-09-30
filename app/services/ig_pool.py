"""
ig_pool.py — 依使用者提供 Instagram 連線（IGClient）的連線池。

- 擁有者 (settings.OWNER_USER_ID)：使用 .env 主帳號的 session（SessionManager.login("main")）
- 其他使用者：使用其透過 Bot `login` 指令綁定、加密存於 users.ig_session 的 session
  → 每位使用者都用「自己的」IG 帳號抓取自己的私訊，不會借用擁有者的收件匣

每位使用者有獨立的鎖 (lock_for)，避免同一個 IG 連線被多執行緒同時操作而觸發風控。
"""
import json
import logging
import threading
from typing import Callable, Dict, Optional

from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from app.core.config import settings
from app.services.ig_service import IGClient
from app.services.session_service import SessionManager
from app.storage.repositories.users import UserRepository

logger = logging.getLogger("bestieAI.ig_pool")


class IGSessionUnavailable(RuntimeError):
    """使用者沒有可用的 IG session（尚未綁定，或 session 已失效需重新 login）。"""


class IGClientPool:
    def __init__(
        self,
        session_manager: SessionManager,
        user_repo: Optional[UserRepository] = None,
        owner_user_id: Optional[int] = None,
        client_factory: Optional[Callable[[Client], IGClient]] = None,
        validate_sessions: bool = True,
    ):
        self.session_manager = session_manager
        self.user_repo = user_repo or UserRepository()
        self.owner_user_id = owner_user_id if owner_user_id is not None else settings.OWNER_USER_ID
        self._wrap = client_factory or IGClient
        self._validate = validate_sessions
        self._clients: Dict[int, IGClient] = {}
        self._create_lock = threading.Lock()
        self._user_locks: Dict[int, threading.Lock] = {}

    def lock_for(self, user_id: int) -> threading.Lock:
        """該使用者 IG 連線的操作鎖。"""
        with self._create_lock:
            return self._user_locks.setdefault(user_id, threading.Lock())

    def prime(self, user_id: int, client: IGClient) -> None:
        """直接指定某使用者的連線（啟動時預載或測試使用）。"""
        with self._create_lock:
            self._clients[user_id] = client

    def invalidate(self, user_id: int) -> None:
        """丟棄快取的連線（例如使用者重新 login 後），下次使用時重新載入。"""
        with self._create_lock:
            self._clients.pop(user_id, None)

    def get(self, user_id: int) -> IGClient:
        with self._create_lock:
            cached = self._clients.get(user_id)
            if cached is not None:
                return cached
            client = self._build(user_id)
            self._clients[user_id] = client
            return client

    def _build(self, user_id: int) -> IGClient:
        if user_id == self.owner_user_id:
            return self._wrap(self.session_manager.login("main"))
        return self._wrap(self._load_user_session(user_id))

    def _load_user_session(self, user_id: int) -> Client:
        row = self.user_repo.get_by_id(user_id)
        encrypted = row["ig_session"] if row is not None else None
        if not encrypted:
            raise IGSessionUnavailable("尚未綁定 IG 帳號，請先私訊：login <IG帳號> <密碼>")
        try:
            raw = self.session_manager.cipher.decrypt(encrypted.encode("utf-8"))
            client = Client()
            client.set_settings(json.loads(raw.decode("utf-8")))
            if self._validate:
                client.get_timeline_feed()  # 確認 session 仍有效
            return client
        except LoginRequired:
            raise IGSessionUnavailable("IG 登入已失效，請重新私訊：login <IG帳號> <密碼>")
        except Exception as e:
            logger.warning(f"載入 user_id={user_id} 的 IG session 失敗: {e}")
            raise IGSessionUnavailable("無法載入你的 IG 登入狀態，請重新私訊：login <IG帳號> <密碼>")
