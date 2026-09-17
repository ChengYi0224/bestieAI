"""
memory.py — 記憶庫與摘要 Command Handler。

PIPELINE (L2):
  MemoryHandler.handle_*()
       │
       ├── handle_me              → MemoryManager.add_self_memory()
       ├── handle_card            → SQLite 取摘要卡 / 全景長文
       ├── handle_refresh_summary → CommandResult(action_type="REFRESH_SUMMARY_REQUEST")
       ├── handle_summarize_history→ CommandResult(action_type="SUMMARIZE_HISTORY_REQUEST")
       ├── handle_sync            → CommandResult(action_type="SYNC_REQUEST")
       └── handle_rebuild_vectors → CommandResult(action_type="REBUILD_VECTORS_REQUEST")
"""
from typing import Any, Optional

from app.commands.base import CommandResult
from app.commands.commands import (
    MeCommand, CardCommand, RefreshSummaryCommand,
    SummarizeHistoryCommand, SyncCommand, RebuildVectorsCommand,
)
from app.storage.db import get_active_contact, get_connection
from app.services.memory_service import MemoryManager


class MemoryHandler:
    """記憶庫與摘要 Handler。依賴 MemoryManager 與 db_path。"""

    def __init__(self, memory_manager: MemoryManager, db_path: Optional[Any] = None):
        self.memory_manager = memory_manager
        self.db_path = db_path

    def handle_me(self, cmd: MeCommand) -> CommandResult:
        if not cmd.content.strip():
            return CommandResult(success=False, message="格式錯誤！請提供要記錄的內容：me <內容>")
        try:
            self.memory_manager.add_self_memory(cmd.content)
            return CommandResult(success=True, message="好，我記下了。", data={"content": cmd.content})
        except Exception as e:
            return CommandResult(success=False, message=f"記錄失敗: {e}")

    def handle_card(self, cmd: CardCommand) -> CommandResult:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
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
            return CommandResult(success=False, message="尚未選定作用對象，請使用 card <IG_ID> 或先使用 select 切換對象。")

        nick_str = f" [暱稱: {contact['nickname']}]" if ("nickname" in contact.keys() and contact["nickname"]) else ""
        name_str = f"（{contact['display_name']}）" if contact["display_name"] else ""

        if cmd.is_full:
            full_summary = contact["full_history_summary"] if "full_history_summary" in contact.keys() else None
            updated_at = (contact["full_history_updated_at"] if "full_history_updated_at" in contact.keys() else None) or "尚未復盤過"
            if not full_summary:
                msg = (
                    f"【{contact['ig_account_id']}{name_str}{nick_str} 全景深度復盤長文】\n"
                    f"目前尚未生成全景復盤長文。\n"
                    f"可輸入「summarize_history」立即對完整歷史對話進行 7 大章節深度分析！"
                )
            else:
                msg = (
                    f"【{contact['ig_account_id']}{name_str}{nick_str} 全景深度復盤長文】\n"
                    f"（復盤時間：{updated_at}）\n\n"
                    f"{full_summary.strip()}"
                )
            return CommandResult(
                success=True,
                message=msg,
                data={"type": "full", "contact": dict(contact), "content": full_summary, "updated_at": updated_at}
            )

        summary = contact["summary_card"]
        updated_at = contact["summary_updated_at"] or "尚未更新過"
        if not summary or summary.strip() == "尚未建立摘要卡":
            msg = (
                f"【{contact['ig_account_id']}{name_str}{nick_str} 日常摘要卡】\n"
                f"目前尚未建立摘要卡。\n"
                f"可使用 summarize_history 或 refresh_summary 指令立即生成。"
            )
        else:
            msg = (
                f"【{contact['ig_account_id']}{name_str}{nick_str} 人物關係日常摘要卡】\n"
                f"（上次更新時間：{updated_at}）\n\n"
                f"{summary.strip()}\n\n"
                f"💡 輸入「card full」可查閱 7 大章節全景長篇復盤。"
            )
        return CommandResult(
            success=True,
            message=msg,
            data={"type": "daily", "contact": dict(contact), "content": summary, "updated_at": updated_at}
        )

    def handle_refresh_summary(self, cmd: RefreshSummaryCommand) -> CommandResult:
        if not cmd.target:
            return CommandResult(success=False, message="請指定對象：refresh_summary <IG_ID>，或先使用 select 切換對象。")
        return CommandResult(
            success=True,
            message=f"正在重新分析並更新 {cmd.target} 的人物關係摘要卡...",
            action_type="REFRESH_SUMMARY_REQUEST",
            data={"target": cmd.target}
        )

    def handle_summarize_history(self, cmd: SummarizeHistoryCommand) -> CommandResult:
        if not cmd.target:
            return CommandResult(success=False, message="請指定對象：summarize_history <IG_ID>，或先使用 select 切換對象。")
        return CommandResult(
            success=True,
            message=f"正在對 {cmd.target} 進行全景深度復盤分析...",
            action_type="SUMMARIZE_HISTORY_REQUEST",
            data={"target": cmd.target}
        )

    def handle_sync(self, cmd: SyncCommand) -> CommandResult:
        if not cmd.target:
            return CommandResult(success=False, message="請指定要同步的對象：sync <IG_ID>，或先使用 select 切換對象。")
        return CommandResult(
            success=True,
            message=f"同步 {cmd.target} 最新訊息中...",
            action_type="SYNC_REQUEST",
            data={"target": cmd.target}
        )

    def handle_rebuild_vectors(self, cmd: RebuildVectorsCommand) -> CommandResult:
        if not cmd.target:
            return CommandResult(success=False, message="請指定對象：rebuild_vectors <IG_ID>，或先使用 select 切換對象。")
        return CommandResult(
            success=True,
            message=f"已在背景啟動 {cmd.target} 向量庫重建...",
            action_type="REBUILD_VECTORS_REQUEST",
            data={"target": cmd.target}
        )
