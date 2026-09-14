"""
security.py — 系統安全模組。

提供：
- Session 金鑰生成與對稱加解密 (Fernet)
- 白名單發話者驗證裝飾器 (@require_whitelist)
"""
import logging
import functools
from pathlib import Path
from typing import Optional, Callable, Any
from cryptography.fernet import Fernet
from app.core.config import settings

logger = logging.getLogger("bestieAI.security")


class SessionCipher:
    """封裝 Fernet 金鑰生成、讀取與資料加解密。"""

    def __init__(self, session_dir: Optional[Path] = None, encryption_key: Optional[str] = None):
        self.session_dir = session_dir or settings.SESSION_DIR
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.key = self._resolve_key(encryption_key)
        self.cipher = Fernet(self.key.encode("utf-8"))

    def _resolve_key(self, explicit_key: Optional[str]) -> str:
        key = explicit_key or settings.SESSION_ENCRYPTION_KEY
        if not key:
            key_file = self.session_dir.parent / ".session_key"
            if key_file.exists():
                key = key_file.read_text(encoding="utf-8").strip()
            else:
                key = Fernet.generate_key().decode("utf-8")
                try:
                    key_file.write_text(key, encoding="utf-8")
                except Exception as e:
                    logger.warning(f"無法寫入 .session_key 檔案: {e}")
        return key

    def encrypt(self, raw_bytes: bytes) -> bytes:
        return self.cipher.encrypt(raw_bytes)

    def decrypt(self, encrypted_bytes: bytes) -> bytes:
        return self.cipher.decrypt(encrypted_bytes)


def require_whitelist(func: Callable) -> Callable:
    """
    Decorator：白名單權限攔截裝飾器。
    僅允許主帳號（本人）發送的私訊進入訊息分發流程，其餘帳號一律靜默丟棄。
    被裝飾的方法應接收 (self, thread_id, user_id, item_id, text, *args, **kwargs)。
    """
    @functools.wraps(func)
    def wrapper(self, thread_id: str, user_id: str, item_id: str, text: str, *args, **kwargs) -> Any:
        # 若發送者是小帳（Bot 本人），直接忽略
        bot_pk = str(getattr(self.bot_client, "user_id", ""))
        if user_id and user_id == bot_pk:
            return

        # 若白名單 PK 尚未設定，嘗試動態解析一次
        if not getattr(self, "allowed_main_pk", None):
            if hasattr(self, "_resolve_main_pk"):
                self._resolve_main_pk()

        # 白名單校驗：若確認不是主帳號，靜默攔截
        allowed_pk = getattr(self, "allowed_main_pk", None)
        if allowed_pk and str(user_id) != str(allowed_pk):
            logger.warning(f"[Security] 攔截到非主帳號 ({user_id}) 之私訊，已靜默忽略。")
            return

        return func(self, thread_id, user_id, item_id, text, *args, **kwargs)
    return wrapper
