"""auth.py — Bot 使用者 IG 登入與 2FA 綁定 Command Handler。"""
import json
import logging
from typing import Optional, Dict, Tuple
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, BadPassword

from app.commands.base import CommandResult
from app.commands.commands import LoginCommand, TwoFactorCommand
from app.services.session_service import SessionManager
from app.storage.repositories.users import UserRepository

logger = logging.getLogger("bestieAI.command.auth")


class AuthHandler:
    """處理 IG login 與 2fa 驗證指令。"""

    def __init__(
        self,
        session_manager: Optional[SessionManager] = None,
        user_repo: Optional[UserRepository] = None,
    ):
        self.session_manager = session_manager or SessionManager()
        self.user_repo = user_repo or UserRepository()
        self._pending_2fa: Dict[str, Tuple[Client, str, str]] = {}

    def handle_login(self, cmd: LoginCommand) -> CommandResult:
        if not cmd.ig_username or not cmd.ig_password:
            return CommandResult(
                success=False,
                message="格式錯誤，請輸入：login <IG帳號> <密碼>",
            )

        sender_pk = str(cmd.sender_pk or "").strip()
        client = Client()

        try:
            client.login(cmd.ig_username, cmd.ig_password)
        except TwoFactorRequired:
            if sender_pk:
                self._pending_2fa[sender_pk] = (client, cmd.ig_username, cmd.ig_password)
            return CommandResult(
                success=True,
                message="🔒 偵測到雙重驗證 (2FA)，請於私訊回覆：2fa <6位數驗證碼>",
            )
        except BadPassword:
            return CommandResult(
                success=False,
                message="❌ 登入失敗：密碼錯誤，請重新確認。",
            )
        except Exception as e:
            logger.error(f"IG 登入發生異常: {e}", exc_info=True)
            return CommandResult(
                success=False,
                message=f"❌ 登入失敗: {e}",
            )

        return self._finish_login(client, cmd.ig_username, sender_pk)

    def handle_two_factor(self, cmd: TwoFactorCommand) -> CommandResult:
        sender_pk = str(cmd.sender_pk or "").strip()
        if not sender_pk or sender_pk not in self._pending_2fa:
            return CommandResult(
                success=False,
                message="❌ 目前沒有等待中的 2FA 登入請求，請先輸入：login <IG帳號> <密碼>",
            )

        client, ig_username, _ = self._pending_2fa.pop(sender_pk)
        try:
            client.two_factor_login(cmd.code.strip())
        except Exception as e:
            logger.error(f"2FA 驗證失敗: {e}", exc_info=True)
            return CommandResult(
                success=False,
                message=f"❌ 2FA 驗證失敗: {e}，請重新輸入：login <IG帳號> <密碼>",
            )

        return self._finish_login(client, ig_username, sender_pk)

    def _finish_login(self, client: Client, ig_username: str, sender_pk: str) -> CommandResult:
        try:
            ig_pk = str(client.user_id)
            settings_dict = client.get_settings()
            raw_bytes = json.dumps(settings_dict).encode("utf-8")
            encrypted_b64 = self.session_manager.cipher.encrypt(raw_bytes).decode("utf-8")

            target_pk = sender_pk if sender_pk else ig_pk
            user = self.user_repo.get_by_ig_pk(target_pk)
            if not user:
                user_id = self.user_repo.create_user(
                    username=f"ig_{ig_username}",
                    display_name=ig_username,
                )
            else:
                user_id = user["id"]

            self.user_repo.bind_ig_account(
                user_id=user_id,
                ig_pk=target_pk,
                ig_username=ig_username,
                encrypted_session=encrypted_b64,
            )

            return CommandResult(
                success=True,
                message=f"✅ IG 帳號 @{ig_username} 登入成功！已完成身分綁定。",
                data={"user_id": user_id, "ig_username": ig_username, "ig_pk": target_pk},
            )
        except Exception as e:
            logger.error(f"完成登入持久化失敗: {e}", exc_info=True)
            return CommandResult(
                success=False,
                message=f"❌ 登入成功但資料持久化失敗: {e}",
            )
