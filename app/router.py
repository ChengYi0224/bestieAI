import re
from typing import Optional, Tuple, Any
from app.db import (
    set_active_contact,
    get_active_contact,
    get_connection,
    add_bot_conversation
)
from app.memory import MemoryManager
from app.llm import LLMClient


class CommandRouter:
    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        llm_client: Optional[LLMClient] = None,
        db_path: Optional[Any] = None
    ):
        self.memory_manager = memory_manager or MemoryManager()
        self.llm_client = llm_client or LLMClient()
        self.db_path = db_path

    def handle_message(self, raw_text: str) -> str:
        text = raw_text.strip()
        parts = text.split()
        if not parts:
            return "收到空白訊息。"

        command = parts[0].lower()

        HELP_TEXT = (
            "【IG AI 陪聊機器人 指令清單】\n"
            "• track <IG_ID>：首次追蹤對象並匯入近一個月聊天紀錄\n"
            "• select <IG_ID>：切換目前作用中的討論對象\n"
            "• sync [IG_ID]：增量同步最新訊息（滿 50 則自動更新摘要卡）\n"
            "• refresh_summary [IG_ID]：手動強制更新人物關係摘要卡\n"
            "• status：檢視目前對象的追蹤狀態與同步時間\n"
            "• list：列出所有已追蹤對象\n"
            "• untrack <IG_ID>：停止追蹤該對象（保留紀錄）\n"
            "• help：查詢指令說明\n"
            "• 直接輸入文字：與 AI 討論回覆策略（需先 select 對象）"
        )

        if command in ("help", "h", "?", "指令"):
            return HELP_TEXT

        elif command == "track":
            if len(parts) < 2:
                return "格式錯誤！請提供要追蹤的帳號：track <IG_ID>\n（輸入 help 可查看所有指令）"
            target = parts[1]
            return f"TRACK_REQUEST:{target}"

        elif command == "select":
            if len(parts) < 2:
                return "格式錯誤！請提供要切換的帳號：select <IG_ID>\n（輸入 help 可查看所有指令）"
            target = parts[1]
            success = set_active_contact(target, db_path=self.db_path)
            if success:
                return f"目前作用對象已切換為 {target}"
            else:
                return f"找不到已追蹤的對象 {target}，請先執行 track {target}\n（輸入 help 可查看所有指令）"

        elif command == "status":
            contact = get_active_contact(db_path=self.db_path)
            if not contact:
                return "目前尚未選定任何作用對象，請使用 select <IG_ID> 切換。\n（輸入 help 可查看所有指令）"
            return (
                f"【目前對話對象狀態】\n"
                f"帳號：{contact['ig_account_id']}\n"
                f"稱呼：{contact['display_name'] or '未設定'}\n"
                f"追蹤狀態：{contact['status']}\n"
                f"上次同步：{contact['last_synced_at'] or '無'}\n"
                f"摘要更新時間：{contact['summary_updated_at'] or '無'}\n"
                f"累積未摘要訊息數：{contact['new_messages_since_summary']}"
            )

        elif command == "list":
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT ig_account_id, display_name, status, last_synced_at FROM contacts")
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return "目前尚未追蹤任何對象，請使用 track <IG_ID> 開始追蹤。\n（輸入 help 可查看所有指令）"
            lines = ["【已追蹤對象清單】"]
            for r in rows:
                lines.append(f"- {r['ig_account_id']} ({r['display_name']}) [{r['status']}]")
            return "\n".join(lines)

        elif command == "refresh_summary":
            if len(parts) > 1:
                target = parts[1]
            else:
                active = get_active_contact(db_path=self.db_path)
                target = active["ig_account_id"] if active else None
            if not target:
                return "請指定對象：refresh_summary <IG_ID>，或先使用 select 切換對象。\n（輸入 help 可查看所有指令）"
            return f"REFRESH_SUMMARY_REQUEST:{target}"

        elif command == "sync":
            if len(parts) > 1:
                target = parts[1]
            else:
                active = get_active_contact(db_path=self.db_path)
                target = active["ig_account_id"] if active else None
            if not target:
                return "請指定要同步的對象：sync <IG_ID>，或先使用 select 切換對象。\n（輸入 help 可查看所有指令）"
            return f"SYNC_REQUEST:{target}"

        elif command == "untrack":
            if len(parts) < 2:
                return "格式錯誤！請指定對象：untrack <IG_ID>\n（輸入 help 可查看所有指令）"
            target = parts[1]
            conn = get_connection(self.db_path)
            with conn:
                conn.execute("UPDATE contacts SET status = 'untracked' WHERE ig_account_id = ?", (target,))
            conn.close()
            return f"已將 {target} 標記為停止追蹤。"

        else:
            return self._handle_chat_mode(text)

    def _handle_chat_mode(self, user_text: str) -> str:
        contact, summary_card, rag_chunks, recent_context = self.memory_manager.get_full_context(user_text)
        if not contact:
            return "目前尚未選擇討論對象！請先傳送指令：select <IG_ID> 切換對象。\n（輸入 help 可查看所有可用指令）"

        contact_id = contact["id"]
        add_bot_conversation(role="user", content=user_text, contact_id=contact_id)

        reply = self.llm_client.generate_reply(
            display_name=contact["display_name"] or contact["ig_account_id"],
            summary_card=summary_card,
            rag_chunks=rag_chunks,
            recent_context=recent_context,
            user_query=user_text
        )

        add_bot_conversation(role="assistant", content=reply, contact_id=contact_id)
        return reply
