import pytest
from pathlib import Path
from cryptography.fernet import Fernet
from unittest.mock import MagicMock
from app.services.session_service import SessionManager

def test_session_encrypt_decrypt(tmp_path):
    key = Fernet.generate_key().decode("utf-8")
    sm = SessionManager(session_dir=tmp_path, encryption_key=key)

    mock_client = MagicMock()
    mock_client.get_settings.return_value = {"authorization_data": {"token": "secret_token_123"}}

    sm._save_session("bot", mock_client)
    session_file = tmp_path / "bot_account.json"
    assert session_file.exists()

    encrypted_bytes = session_file.read_bytes()
    assert b"secret_token_123" not in encrypted_bytes

    decrypted_bytes = sm.cipher.decrypt(encrypted_bytes)
    assert b"secret_token_123" in decrypted_bytes


def test_session_key_persistence_file(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "SESSION_ENCRYPTION_KEY", "")

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    # 首次初始化（未給 key 且環境變數為空）：自動生成 .session_key 檔案
    sm1 = SessionManager(session_dir=session_dir, encryption_key="")
    key_file = tmp_path / ".session_key"
    assert key_file.exists()
    saved_key = key_file.read_text(encoding="utf-8").strip()
    assert len(saved_key) > 20

    # 再次初始化：自動從 .session_key 載入相同金鑰
    sm2 = SessionManager(session_dir=session_dir, encryption_key=None)

    # 驗證兩者加密互通
    test_data = b"hello_bestie"
    enc = sm1.cipher.encrypt(test_data)
    dec = sm2.cipher.decrypt(enc)
    assert dec == test_data
