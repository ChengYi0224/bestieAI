"""test_bot_auth_commands.py — Bot login / 2fa 指令與白名單放行單元測試。"""
from unittest.mock import MagicMock, patch
import pytest
from instagrapi.exceptions import TwoFactorRequired, BadPassword

from app.bot.auth import require_whitelist
from app.commands.commands import LoginCommand, TwoFactorCommand
from app.commands.handlers.auth import AuthHandler
from app.commands.parsers import CommandParserRegistry
from app.storage.db import init_db
from app.storage.repositories.users import UserRepository


@pytest.fixture
def user_repo(tmp_path):
    db_path = tmp_path / "test_bot_auth.db"
    init_db(db_path)
    return UserRepository(db_path=db_path)


def test_login_and_2fa_parsers():
    """驗證 login 與 2fa 文字指令能正確被解析為 Command 物件。"""
    cmd1 = CommandParserRegistry.parse("login my_account my_password")
    assert isinstance(cmd1, LoginCommand)
    assert cmd1.ig_username == "my_account"
    assert cmd1.ig_password == "my_password"

    cmd2 = CommandParserRegistry.parse("2fa 987654")
    assert isinstance(cmd2, TwoFactorCommand)
    assert cmd2.code == "987654"

    cmd3 = CommandParserRegistry.parse("登入 test_user pass123")
    assert isinstance(cmd3, LoginCommand)
    assert cmd3.ig_username == "test_user"


def test_auth_handler_two_factor_flow(user_repo):
    """驗證遇到 2FA 挑戰時引導使用者輸入驗證碼並接續完成登入與綁定。"""
    handler = AuthHandler(user_repo=user_repo)

    # 1. 模擬第一次登入拋出 TwoFactorRequired
    with patch("app.commands.handlers.auth.Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.login.side_effect = TwoFactorRequired("2FA required")
        MockClient.return_value = mock_instance

        cmd = LoginCommand(ig_username="target_ig", ig_password="pwd", sender_pk="sender_pk_123")
        res = handler.handle_login(cmd)
        assert res.success is True
        assert "2fa" in res.message.lower()
        assert "sender_pk_123" in handler._pending_2fa

    # 2. 模擬使用者輸入 2fa 驗證碼接續完成登入
    mock_instance.user_id = 99887766
    mock_instance.get_settings.return_value = {"cookies": "test"}

    cmd_2fa = TwoFactorCommand(code="123456", sender_pk="sender_pk_123")
    res_2fa = handler.handle_two_factor(cmd_2fa)
    assert res_2fa.success is True
    assert "成功" in res_2fa.message

    # 驗證資料庫使用者已被綁定
    user = user_repo.get_by_ig_pk("sender_pk_123")
    assert user is not None
    assert user["ig_username"] == "target_ig"


def test_auth_handler_bad_password(user_repo):
    """驗證密碼錯誤時回傳清晰錯誤訊息。"""
    handler = AuthHandler(user_repo=user_repo)

    with patch("app.commands.handlers.auth.Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.login.side_effect = BadPassword("Bad password")
        MockClient.return_value = mock_instance

        cmd = LoginCommand(ig_username="bad_user", ig_password="wrong", sender_pk="pk_1")
        res = handler.handle_login(cmd)
        assert res.success is False
        assert "密碼錯誤" in res.message


def test_require_whitelist_behavior(tmp_path):
    """驗證白名單攔截與登入指令放行行為。"""
    db_path = tmp_path / "test_auth_guard.db"
    init_db(db_path)
    user_repo = UserRepository(db_path=db_path)

    # 建立已綁定使用者
    user_id = user_repo.create_user("known_user")
    user_repo.bind_ig_account(user_id=user_id, ig_pk="known_pk", ig_username="known_user")

    class DummyPoller:
        def __init__(self):
            self.allowed_main_pk = "main_pk"
            self.bot_client = MagicMock(user_id="bot_pk")
            self.db_path = db_path

        @require_whitelist
        def process(self, thread_id, user_id, item_id, text):
            return f"PROCESSED: {text}"

    poller = DummyPoller()

    # 1. 主帳號發送任何文字 -> 放行
    assert poller.process("t1", "main_pk", "m1", "任意私訊") == "PROCESSED: 任意私訊"

    # 2. 已登記綁定 IG PK 的使用者發送訊息 -> 放行
    assert poller.process("t2", "known_pk", "m2", "嗨我已登入") == "PROCESSED: 嗨我已登入"

    # 3. 未登記之新朋友發送一般私訊 -> 靜默攔截 (None)
    assert poller.process("t3", "stranger_pk", "m3", "未註冊隨意對話") is None

    # 4. 未登記之新朋友發送 login 或 2fa 指令 -> 放行以利登入
    assert poller.process("t3", "stranger_pk", "m4", "login user pass") == "PROCESSED: login user pass"
    assert poller.process("t3", "stranger_pk", "m5", "2fa 123456") == "PROCESSED: 2fa 123456"
