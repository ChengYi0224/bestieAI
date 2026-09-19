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

from app.commands.base import CommandResult
from app.commands.commands import ExportCommand
from app.storage.db import get_active_contact, get_recent_messages, get_connection
from app.utils.db import row_to_dict, get_row_field

logger = logging.getLogger("bestieAI.export_handler")


class ExportHandler:
    """私訊對話匯出 Handler。支援 Auto-Sync 與 Immediate 本地模式。"""

    def __init__(
        self,
        db_path: Optional[Any] = None,
        sync_callback: Optional[Callable[[str], Any]] = None,
    ):
        self.db_path = db_path
        self.sync_callback = sync_callback

    def handle_export(self, cmd: ExportCommand) -> CommandResult:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        contact = None

        if cmd.target:
            cursor.execute("""
                SELECT * FROM contacts
                WHERE LOWER(ig_account_id) = LOWER(?) OR LOWER(display_name) = LOWER(?) OR LOWER(nickname) = LOWER(?)
            """, (cmd.target, cmd.target, cmd.target))
            contact = cursor.fetchone()
        else:
            contact = get_active_contact(db_path=self.db_path)
        conn.close()

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

        # 預設先執行增量同步（Auto-Sync），除非指定 -I / immediate
        if not cmd.immediate and self.sync_callback and target_id:
            try:
                self.sync_callback(target_id)
            except Exception as e:
                logger.warning(f"自動同步訊息失敗，Fallback 使用本地既有紀錄: {e}")

        # 從本地 SQLite 取得最新對話
        limit = max(1, cmd.limit)
        messages = get_recent_messages(contact_id=contact_id, limit=limit, db_path=self.db_path)
        if not messages:
            return CommandResult(
                success=True,
                message=f"目前查無與 {target_label} 的對話紀錄。",
                data={"messages": [], "contact": row_to_dict(contact)}
            )

        # 格式化輸出
        lines = [f"【與 {target_label} 的最新 {len(messages)} 則對話紀錄】"]
        for m in messages:
            sent_at = get_row_field(m, "sent_at") or ""
            sender_type = get_row_field(m, "sender")
            sender_label = "我" if sender_type == "me" else target_label
            content = get_row_field(m, "content") or ""
            time_prefix = f"[{sent_at}] " if sent_at else ""
            lines.append(f"{time_prefix}{sender_label}: {content}")

        formatted_text = "\n".join(lines)
        return CommandResult(
            success=True,
            message=formatted_text,
            data={
                "messages": [row_to_dict(m) for m in messages],
                "contact": row_to_dict(contact),
                "count": len(messages),
            }
        )
