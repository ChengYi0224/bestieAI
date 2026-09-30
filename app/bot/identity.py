"""
identity.py — 將 IG 發送者 (PK) 對應到系統使用者 (users.id)。

  主帳號 PK          → settings.OWNER_USER_ID
  已透過 login 綁定  → users.ig_pk 對應的使用者
  其他               → None（未綁定，僅能使用 help / login / 2fa）
"""
import logging
from typing import Callable, Optional

from app.core.config import settings
from app.storage.repositories.users import UserRepository

logger = logging.getLogger("bestieAI.bot.identity")


class SenderResolver:
    def __init__(
        self,
        owner_pk_getter: Callable[[], Optional[str]],
        user_repo: Optional[UserRepository] = None,
        owner_user_id: Optional[int] = None,
    ):
        self._owner_pk = owner_pk_getter
        self._user_repo = user_repo or UserRepository()
        self._owner_user_id = owner_user_id if owner_user_id is not None else settings.OWNER_USER_ID

    def resolve(self, sender_pk: str) -> Optional[int]:
        pk = str(sender_pk).strip()
        if not pk:
            return None
        owner_pk = self._owner_pk()
        if owner_pk and pk == str(owner_pk):
            return self._owner_user_id
        try:
            user = self._user_repo.get_by_ig_pk(pk)
        except Exception as e:
            logger.warning(f"查詢 ig_pk={pk} 對應使用者失敗，視為未綁定: {e}")
            return None
        return int(user["id"]) if user else None
