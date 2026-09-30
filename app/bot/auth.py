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
    主帳號與已綁定 IG 帳號的使用者可進入訊息分發流程；其餘帳號僅放行登入 / 驗證 / 說明指令，其餘一律靜默丟棄。
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

        # 發送者身分：主帳號 → 擁有者；已綁定 IG PK → 對應使用者；其他 → 未綁定
        resolved = self.resolver.resolve(str(user_id))
        if resolved is None:
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
