import re
import time
from typing import Optional, Tuple, Any
from app.db import (
    set_active_contact,
    set_active_contact_by_id,
    get_active_contact,
    get_connection,
    add_bot_conversation,
    search_contacts_fuzzy,
    set_pending_selection,
    get_pending_selection,
    get_contact_by_id,
    get_worker_status,
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

        # 檢查是否為針對多重候選清單的數字回覆 (例如 "1", "2")
        if text.isdigit():
            pending_ids = get_pending_selection(db_path=self.db_path)
            if pending_ids:
                choice_idx = int(text) - 1
                if 0 <= choice_idx < len(pending_ids):
                    selected_id = pending_ids[choice_idx]
                    set_active_contact_by_id(selected_id, db_path=self.db_path)
                    target = get_contact_by_id(selected_id, db_path=self.db_path)
                    name_str = f"（{target['display_name']}）" if target and target["display_name"] else ""
                    return f"已確認！目前作用對象切換為：{target['ig_account_id']}{name_str}"
                else:
                    return f"數字超出範圍，請輸入 1 到 {len(pending_ids)} 之間的數字選擇對象。"

        HELP_TEXT = (
            "【IG AI 陪聊機器人 指令清單】\n"
            "• track <IG_ID>：首次追蹤對象並匯入近一個月聊天紀錄\n"
            "• track_full [IG_ID] [上限]：安全慢速全量抓取所有歷史訊息（防風控、自動去重、重建向量庫）\n"
            "• select <關鍵字>：切換目前作用中的討論對象（支援模糊搜尋與數字回覆）\n"
            "• summarize_history [IG_ID]：以本地所有完整歷史對話（非僅近期）深度復盤關係與人物全貌\n"
            "• sync [IG_ID]：增量同步最新訊息（滿 50 則自動更新摘要卡）\n"
            "• rebuild_vectors [IG_ID]：從本地資料庫重建向量庫（embedding 失敗後修復用，不需重新爬 IG）\n"
            "• refresh_summary [IG_ID]：手動強制更新人物關係摘要卡\n"
            "• status（或 query）：檢視目前對話對象狀態與背景爬蟲即時進度\n"
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

        elif command == "track_full":
            # 支援 track_full [IG_ID] [max_amount] 或 track_full [max_amount]
            target = None
            max_amount = 5000
            if len(parts) >= 2:
                if parts[1].isdigit():
                    max_amount = int(parts[1])
                else:
                    target = parts[1]
                    if len(parts) >= 3 and parts[2].isdigit():
                        max_amount = int(parts[2])

            if not target:
                active = get_active_contact(db_path=self.db_path)
                target = active["ig_account_id"] if active else None

            if not target:
                return "請指定要全量抓取的帳號：track_full <IG_ID> [最大訊息數]，或先使用 select 切換對象。\n（輸入 help 可查看所有指令）"

            return f"TRACK_FULL_REQUEST:{target}:{max_amount}"

        elif command == "select":
            if len(parts) < 2:
                return "格式錯誤！請提供要切換的帳號或名稱關鍵字：select <關鍵字>\n（輸入 help 可查看所有指令）"
            query_key = parts[1]

            matches = search_contacts_fuzzy(query_key, db_path=self.db_path)
            if not matches:
                return f"找不到符合「{query_key}」的已追蹤對象。\n請先執行 track <IG_ID> 追蹤該帳號，或輸入 list 查看現有名單。"

            # 若完全吻合（忽略大小寫），或者只有唯一一筆結果，直接切換
            exact_match = next((m for m in matches if m["ig_account_id"].lower() == query_key.lower()), None)
            if exact_match:
                set_active_contact_by_id(exact_match["id"], db_path=self.db_path)
                return f"目前作用對象已切換為：{exact_match['ig_account_id']}（{exact_match['display_name'] or '未設定名稱'}）"

            if len(matches) == 1:
                target_contact = matches[0]
                set_active_contact_by_id(target_contact["id"], db_path=self.db_path)
                return f"目前作用對象已切換為：{target_contact['ig_account_id']}（{target_contact['display_name'] or '未設定名稱'}）"

            # 多重搜尋結果，暫存候選清單並提示使用者回傳數字序號
            candidate_ids = [m["id"] for m in matches]
            set_pending_selection(candidate_ids, db_path=self.db_path)

            lines = [f"找到 {len(matches)} 個符合「{query_key}」的對象，請回傳數字選擇："]
            for idx, m in enumerate(matches, 1):
                name_str = f"（{m['display_name']}）" if m["display_name"] else ""
                lines.append(f"{idx}. {m['ig_account_id']}{name_str}")
            lines.append("（直接回傳數字如 1 即可完成切換）")
            return "\n".join(lines)

        elif command in ("status", "query", "進度", "狀態"):
            w_status = get_worker_status(db_path=self.db_path)
            worker_section = ""
            if w_status and w_status.get("running"):
                elapsed_min = int((time.time() - w_status.get("start_time", time.time())) // 60)
                worker_section = (
                    f"【背景抓取中】\n"
                    f"對象: {w_status.get('target')}\n"
                    f"進度: 第 {w_status.get('pages', 0)} 頁 ({w_status.get('count', 0)} 則)\n"
                    f"耗時: 約 {elapsed_min} 分鐘\n\n"
                )
            elif w_status and not w_status.get("running"):
                worker_section = f"【背景任務】無執行中任務\n\n"

            contact = get_active_contact(db_path=self.db_path)
            if not contact:
                if worker_section:
                    return f"{worker_section}尚未選定作用對象，請使用 select <關鍵字> 切換。"
                return "尚未選定作用對象，請使用 select <IG_ID> 切換。"

            return (
                f"{worker_section}"
                f"【目前對象】\n"
                f"帳號: {contact['ig_account_id']} ({contact['display_name'] or '未設定'})\n"
                f"狀態: {contact['status']}\n"
                f"上次同步: {contact['last_synced_at'] or '無'}\n"
                f"摘要更新: {contact['summary_updated_at'] or '無'}\n"
                f"累積未摘要: {contact['new_messages_since_summary']} 則"
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

        elif command == "summarize_history":
            if len(parts) > 1:
                target = parts[1]
            else:
                active = get_active_contact(db_path=self.db_path)
                target = active["ig_account_id"] if active else None
            if not target:
                return "請指定對象：summarize_history <IG_ID>，或先使用 select 切換對象。\n（輸入 help 可查看所有指令）"
            return f"SUMMARIZE_HISTORY_REQUEST:{target}"

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

        elif command == "rebuild_vectors":
            if len(parts) > 1:
                target = parts[1]
            else:
                active = get_active_contact(db_path=self.db_path)
                target = active["ig_account_id"] if active else None
            if not target:
                return "請指定對象：rebuild_vectors <IG_ID>，或先使用 select 切換對象。\n（輸入 help 可查看所有指令）"
            return f"REBUILD_VECTORS_REQUEST:{target}"

        else:
            return self._handle_chat_mode(text)

    def _handle_chat_mode(self, user_text: str) -> str:
        contact, summary_card, rag_chunks, recent_context, chat_history = self.memory_manager.get_full_context(user_text)
        if not contact:
            return "目前尚未選擇討論對象！請先傳送指令：select <IG_ID> 切換對象。"

        contact_id = contact["id"]
        add_bot_conversation(role="user", content=user_text, contact_id=contact_id)

        reply = self.llm_client.generate_reply(
            display_name=contact["display_name"] or contact["ig_account_id"],
            summary_card=summary_card,
            rag_chunks=rag_chunks,
            recent_context=recent_context,
            chat_history=chat_history,
            user_query=user_text
        )

        add_bot_conversation(role="assistant", content=reply, contact_id=contact_id)
        return reply
