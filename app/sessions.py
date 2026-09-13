import json
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, TwoFactorRequired, ChallengeRequired
from app.config import settings


class SessionManager:
    def __init__(self, session_dir: Optional[Path] = None, encryption_key: Optional[str] = None):
        self.session_dir = session_dir or settings.SESSION_DIR
        self.session_dir.mkdir(parents=True, exist_ok=True)
        key = encryption_key or settings.SESSION_ENCRYPTION_KEY
        if not key:
            generated_key = Fernet.generate_key().decode("utf-8")
            self.cipher = Fernet(generated_key.encode("utf-8"))
        else:
            self.cipher = Fernet(key.encode("utf-8"))

    def _get_session_path(self, account_type: str) -> Path:
        return self.session_dir / f"{account_type}_account.json"

    def _save_session(self, account_type: str, client: Client) -> None:
        settings_dict = client.get_settings()
        raw_data = json.dumps(settings_dict).encode("utf-8")
        encrypted_data = self.cipher.encrypt(raw_data)
        path = self._get_session_path(account_type)
        path.write_bytes(encrypted_data)

    def _load_session(self, account_type: str) -> Optional[Client]:
        path = self._get_session_path(account_type)
        if not path.exists():
            return None
        try:
            encrypted_data = path.read_bytes()
            raw_data = self.cipher.decrypt(encrypted_data)
            settings_dict = json.loads(raw_data.decode("utf-8"))
            client = Client()
            client.set_settings(settings_dict)
            client.get_timeline_feed()
            return client
        except Exception:
            if path.exists():
                path.unlink(missing_ok=True)
            return None

    def login(self, account_type: str) -> Client:
        client = self._load_session(account_type)
        if client:
            return client

        client = Client()
        if account_type == "main":
            username = settings.MAIN_ACCOUNT_USERNAME
            password = settings.MAIN_ACCOUNT_PASSWORD
        else:
            username = settings.BOT_ACCOUNT_USERNAME
            password = settings.BOT_ACCOUNT_PASSWORD

        if not username or not password:
            raise ValueError(f"Credentials for {account_type} account are not set in .env")

        try:
            client.login(username, password)
        except TwoFactorRequired:
            code = input(f"[2FA] 請輸入 {account_type} 帳號 ({username}) 的 2FA 驗證碼: ")
            client.login(username, password, verification_code=code)
        except ChallengeRequired:
            code = input(f"[Challenge] 請輸入 {account_type} 帳號 ({username}) 的安全驗證碼: ")
            client.login(username, password, verification_code=code)

        self._save_session(account_type, client)
        return client
