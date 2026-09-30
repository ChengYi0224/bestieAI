"""
export.py — 最新私訊對話紀錄匯出 Handler。

PIPELINE (L2):
  ExportHandler.handle_export(cmd)
       │
       ├─ (未指定且無 active contact) ──► 提示使用 select
       │
       ├─ (not immediate 且有 sync_callback) ──► 呼叫同步至最新
       │
       ▼
  get_recent_messages(contact_id, limit)
       │
       ▼
  格式化輸出時間、發送者與訊息內文
       │
       ▼
  CommandResult(success=True, message=formatted_text)
"""
import logging
from typing import Any, Optional, Callable

from app.commands.base import CommandResult, SYNC_FAILED, need_user
from app.commands.commands import ExportCommand
from app.storage.repositories import ContactRepository, MessageRepository
from app.utils.db import row_to_dict, get_row_field
from app.utils.text import format_chat_messages


logger = logging.getLogger("bestieAI.export_handler")


class ExportHandler:
    """私訊對話匯出 Handler。支援 Auto-Sync 與 Immediate 本地模式。"""

    def __init__(
        self,
        contact_repo: Optional[ContactRepository] = None,
        message_repo: Optional[MessageRepository] = None,
        sync_callback: Optional[Callable[[str], Any]] = None,
        db_path: Optional[Any] = None,
    ):
        self.contact_repo = contact_repo or ContactRepository(db_path)
        self.message_repo = message_repo or MessageRepository(db_path)
        self.sync_callback = sync_callback

    def handle_export(self, cmd: ExportCommand) -> CommandResult:
        uid = need_user(cmd)
        contact = (
            self.contact_repo.find_by_identifier(cmd.target, user_id=uid)
            if cmd.target
            else self.contact_repo.get_active(user_id=uid)
        )


        if not contact:
            if cmd.target:
                return CommandResult(success=False, message=f"找不到符合「{cmd.target}」的對象，請確認帳號或暱稱是否正確。")
            return CommandResult(success=False, message="尚未選定作用對象，請使用 exp <num> <IG_ID> 或先使用 select 切換對象。")

        target_id = get_row_field(contact, "ig_account_id")
        target_label = (
            get_row_field(contact, "nickname")
            or get_row_field(contact, "display_name")
            or target_id
            or "對方"
        )
        contact_id = get_row_field(contact, "id")

        limit = max(1, cmd.limit)

        # 預設先執行增量同步（Auto-Sync），除非指定 -I / immediate；只需同步 limit 則，抓夠即停
        sync_failed = False
        if not cmd.immediate and self.sync_callback and target_id:
            try:
                sync_failed = self.sync_callback(target_id, amount=limit, user_id=uid) == SYNC_FAILED
            except Exception as e:
                sync_failed = True
                logger.warning(f"自動同步訊息失敗，Fallback 使用本地既有紀錄: {e}")

        # 從本地 SQLite 取得最新對話
        messages = self.message_repo.get_recent(contact_id=contact_id, limit=limit)

        if not messages:
            return CommandResult(
                success=True,
                message=f"目前查無與 {target_label} 的對話紀錄。" + ("（同步最新私訊失敗）" if sync_failed else ""),
                data={"messages": [], "contact": row_to_dict(contact), "sync_failed": sync_failed}
            )

        # 格式化輸出
        header = f"【與 {target_label} 的最新 {len(messages)} 則對話紀錄】"
        formatted_messages = format_chat_messages(messages, other_label=target_label)
        formatted_text = f"{header}\n\n{formatted_messages}" if formatted_messages else header
        if sync_failed:
            formatted_text = f"⚠️ 同步最新私訊失敗，以下為本地既有紀錄（可能不是最新）。\n\n{formatted_text}"
        return CommandResult(
            success=True,
            message=formatted_text,
            data={
                "messages": [row_to_dict(m) for m in messages],
                "contact": row_to_dict(contact),
                "count": len(messages),
                "sync_failed": sync_failed,
            }
        )
