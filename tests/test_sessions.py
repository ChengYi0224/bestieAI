import pytest
from pathlib import Path
from cryptography.fernet import Fernet
from unittest.mock import MagicMock
from app.sessions import SessionManager

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
