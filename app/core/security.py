"""
security.py — 系統安全模組。

提供：
- Session 金鑰生成與對稱加解密 (Fernet)
- 白名單發話者驗證裝飾器 (@require_whitelist)
"""
import logging
from pathlib import Path
from typing import Optional
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


# 向後相容轉發（實際職責已拆至 app.bot.auth）
from app.bot.auth import require_whitelist

__all__ = ["SessionCipher", "require_whitelist"]
