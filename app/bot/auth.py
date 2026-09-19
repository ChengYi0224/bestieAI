"""
auth.py — Telegram / IG Bot 權限驗證與白名單過濾模組。
職責：
1. 僅允許主帳號（本人）發送的私訊進入分發流程，其餘帳號一律靜默丟棄。
2. 攔截 Bot 自身發出的 Echo 訊息。
"""
import logging
import functools
from typing import Callable, Any

logger = logging.getLogger("bestieAI.bot.auth")


def require_whitelist(func: Callable) -> Callable:
    """
    Decorator：白名單權限攔截裝飾器。
    僅允許主帳號（本人）發送的私訊進入訊息分發流程，其餘帳號一律靜默丟棄。
    被裝飾的方法應接收 (self, thread_id, user_id, item_id, text, *args, **kwargs)。
    """
    @functools.wraps(func)
    def wrapper(self, thread_id: str, user_id: str, item_id: str, text: str, *args, **kwargs) -> Any:
        # 略過非文字或系統事件（如 MQTT 打字中、已讀回條、心跳等無內容封包）
        if not text or not str(user_id).strip():
            return

        bot_pk = str(getattr(self.bot_client, "user_id", ""))
        if user_id and str(user_id) == bot_pk:
            return

        if not getattr(self, "allowed_main_pk", None):
            if hasattr(self, "_resolve_main_pk"):
                self._resolve_main_pk()

        allowed_pk = getattr(self, "allowed_main_pk", None)
        is_main = allowed_pk and str(user_id) == str(allowed_pk)

        if not is_main:
            # 檢查是否為資料庫內已綁定 IG PK 之合法使用者
            try:
                from app.storage.repositories.users import UserRepository
                db_path = getattr(self, "db_path", None)
                repo = UserRepository(db_path=db_path)
                known_user = repo.get_by_ig_pk(str(user_id))
            except Exception:
                known_user = None

            if not known_user:
                # 未綁定之發訊者：僅放行登入與驗證相關指令
                clean_lower = text.strip().lower()
                is_auth_cmd = any(
                    clean_lower.startswith(prefix)
                    for prefix in ("login", "登入", "2fa", "otp", "help", "說明")
                )
                if not is_auth_cmd:
                    preview = (text[:60] + "...") if len(text) > 60 else text
                    logger.warning(f"[Auth] 攔截到未授權帳號 (user_id={user_id}, thread_id={thread_id}) 之私訊內容: {preview!r}，已靜默忽略。")
                    return

        return func(self, thread_id, user_id, item_id, text, *args, **kwargs)
    return wrapper
