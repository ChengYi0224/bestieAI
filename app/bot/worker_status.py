"""
worker_status.py — 將背景任務進度寫入該使用者自己的 bot_user_state.worker_status。
"""
from datetime import datetime, timezone
from typing import Any

from app.storage.db import set_worker_status


def report(user_id: int, **fields: Any) -> None:
    """寫入（覆寫）指定使用者的背景任務狀態，並自動附上 last_update。"""
    set_worker_status({**fields, "last_update": datetime.now(timezone.utc).isoformat()}, user_id)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
