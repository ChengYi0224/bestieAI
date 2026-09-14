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
        bot_pk = str(getattr(self.bot_client, "user_id", ""))
        if user_id and user_id == bot_pk:
            return

        if not getattr(self, "allowed_main_pk", None):
            if hasattr(self, "_resolve_main_pk"):
                self._resolve_main_pk()

        allowed_pk = getattr(self, "allowed_main_pk", None)
        if allowed_pk and str(user_id) != str(allowed_pk):
            logger.warning(f"[Auth] 攔截到非主帳號 ({user_id}) 之私訊，已靜默忽略。")
            return

        return func(self, thread_id, user_id, item_id, text, *args, **kwargs)
    return wrapper
