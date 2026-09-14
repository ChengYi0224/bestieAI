"""
router.py — 宣告式指令路由與訊息調度中心。

功能：
- 宣告式指令註冊 (@command_handler)
- 精簡分組 Help（預設常用核心指令，help all 顯示全量維護指令）
- card 支援全景長文查詢（card 查日常卡，card full 查全景長文）
- 自然語言陪伴陪聊模式
"""
import re
import time
import threading
from typing import Optional, Tuple, Any, Callable, Dict, List

from app.core.config import settings
from app.storage.db import (
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
    set_contact_nickname,
    get_contacts_with_nickname,
)
from app.services.memory_service import MemoryManager
from app.services.llm_service import LLMClient

_COMMAND_REGISTRY: Dict[str, str] = {}


def command_handler(*names: str):
    """Decorator：宣告式註冊指令名稱至所裝飾的處理函式。"""
    def decorator(func: Callable):
        for name in names:
            _COMMAND_REGISTRY[name.lower()] = func.__name__
        return func
    return decorator


class CommandRouter:
    @classmethod
    def get_help_text(cls, show_all: bool = False) -> str:
        if not show_all:
            return (
                "【IG AI 陪聊機器人 指令清單】\n"
                "• track <IG_ID>：首次追蹤對象並匯入近況\n"
                "• select <關鍵字>：切換目前討論對象\n"
                "• card [IG_ID]：檢視目前對象的日常摘要卡\n"
                "• card full [IG_ID]：檢視完整全景深度復盤長文\n"
                "• me <內容>：讓 AI 記住你的喜好與生活近況\n"
                "• status：檢視目前對象與背景進度\n"
                "• 直接傳送訊息：與 AI 討論相處回覆策略\n\n"
                "💡 輸入「help all」可查看全量進階指令（全量抓取、同步、重建等）。"
            )
        return (
            "【IG AI 陪聊機器人 指令清單 - 全量模式】\n"
            "--- 常用對話與設定 ---\n"
            "• track <IG_ID>：首次追蹤對象並匯入近期對話\n"
            "• select <關鍵字>：切換目前作用中的討論對象\n"
            "• nickname <暱稱> [IG_ID]：為對象設定專屬暱稱\n"
            "• card [IG_ID]：檢視日常輕量人物關係摘要卡\n"
            "• card full [IG_ID]：檢視 7 大章節全景深度復盤長文\n"
            "• me <內容>：記錄關於你的生活近況或偏好\n"
            "• list：列出所有已追蹤對象名單\n"
            "• status：檢視目前選定對象與背景爬蟲進度\n\n"
            "--- 深度復盤與維護 ---\n"
            "• summarize_history [IG_ID]：以所有完整歷史對話進行深度全景復盤\n"
            "• sync [IG_ID]：增量同步最新訊息\n"
            f"• track_full [IG_ID] [上限]：慢速防風控全量抓取（預設上限 {settings.TRACK_FULL_DEFAULT_LIMIT} 則）\n"
            "• rebuild_vectors [IG_ID]：從本地 SQLite 重建事件向量庫\n"
            "• refresh_summary [IG_ID]：強制更新日常人物摘要卡\n"
            "• untrack <IG_ID>：停止追蹤該對象\n"
            "• help：返回精簡核心指令"
        )

    @property
    def HELP_TEXT(self) -> str:
        return self.get_help_text(show_all=False)

    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        llm_client: Optional[LLMClient] = None,
        db_path: Optional[Any] = None
    ):
        self.memory_manager = memory_manager or MemoryManager()
        self.llm_client = llm_client or LLMClient()
        self.db_path = db_path

    def _resolve_target(self, parts: List[str], index: int = 1) -> Optional[str]:
        if len(parts) > index and not parts[index].isdigit():
            return parts[index]
        active = get_active_contact(db_path=self.db_path)
        return active["ig_account_id"] if active else None

    # ==================== 指令處理器 ====================

    @command_handler("help", "h", "?", "指令")
    def handle_help(self, parts: List[str], raw_text: str) -> str:
        show_all = len(parts) >= 2 and parts[1].lower() in ("all", "full", "全部", "詳細")
        return self.get_help_text(show_all=show_all)

    @command_handler("track")
    def handle_track(self, parts: List[str], raw_text: str) -> str:
        if len(parts) < 2:
            return "格式錯誤！請提供要追蹤的帳號：track <IG_ID>\n（輸入 help 可查看常用指令）"
        return f"TRACK_REQUEST:{parts[1]}"

    @command_handler("track_full")
    def handle_track_full(self, parts: List[str], raw_text: str) -> str:
        target = None
        max_amount = settings.TRACK_FULL_DEFAULT_LIMIT
        if len(parts) >= 2:
            if parts[1].isdigit():
                max_amount = int(parts[1])
            else:
                target = parts[1]
                if len(parts) >= 3 and parts[2].isdigit():
                    max_amount = int(parts[2])

        if not target:
            target = self._resolve_target(parts, index=1)

        if not target:
            return "請指定要全量抓取的帳號：track_full <IG_ID> [最大訊息數]，或先使用 select 切換對象。"

        return f"TRACK_FULL_REQUEST:{target}:{max_amount}"

    @command_handler("select")
    def handle_select(self, parts: List[str], raw_text: str) -> str:
        if len(parts) < 2:
            return "格式錯誤！請提供要切換的帳號或名稱關鍵字：select <關鍵字>"
        query_key = parts[1]

        matches = search_contacts_fuzzy(query_key, db_path=self.db_path)
        if not matches:
            return f"找不到符合「{query_key}」的已追蹤對象。\n請先執行 track <IG_ID> 追蹤該帳號，或輸入 list 查看現有名單。"

        exact = next((m for m in matches if m["ig_account_id"].lower() == query_key.lower()), None)
        target_match = exact or (matches[0] if len(matches) == 1 else None)
        if target_match:
            set_active_contact_by_id(target_match["id"], db_path=self.db_path)
            return f"目前作用對象已切換為：{target_match['ig_account_id']}（{target_match['display_name'] or '未設定名稱'}）"

        candidate_ids = [m["id"] for m in matches]
        set_pending_selection(candidate_ids, db_path=self.db_path)

        lines = [f"找到 {len(matches)} 個符合「{query_key}」的對象，請回傳數字選擇："]
        for idx, m in enumerate(matches, 1):
            name_str = f"（{m['display_name']}）" if m["display_name"] else ""
            lines.append(f"{idx}. {m['ig_account_id']}{name_str}")
        lines.append("（直接回傳數字如 1 即可完成切換）")
        return "\n".join(lines)

    @command_handler("nickname", "nick", "暱稱")
    def handle_nickname(self, parts: List[str], raw_text: str) -> str:
        if len(parts) < 2:
            return "格式錯誤！請提供暱稱：nickname <暱稱> [IG_ID]"
        nick = parts[1]
        target_account = parts[2] if len(parts) >= 3 else None

        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        if target_account:
            cursor.execute("SELECT id, ig_account_id, display_name FROM contacts WHERE ig_account_id = ?", (target_account,))
            target = cursor.fetchone()
        else:
            target = get_active_contact(db_path=self.db_path)
        conn.close()

        if not target:
            return "尚未指定對象，請在指令後附帶帳號或先使用 select 切換對象。"

        set_contact_nickname(target["id"], nick, db_path=self.db_path)
        return f"已為 {target['ig_account_id']} 設定暱稱為「{nick}」。"

    @command_handler("me", "我")
    def handle_me(self, parts: List[str], raw_text: str) -> str:
        if len(parts) < 2:
            return "格式錯誤！請提供要記錄的內容：me <內容>"
        content = " ".join(parts[1:])
        try:
            self.memory_manager.add_self_memory(content)
            return "好，我記下了。"
        except Exception as e:
            return f"記錄失敗: {e}"

    @command_handler("status", "query", "進度", "狀態")
    def handle_status(self, parts: List[str], raw_text: str) -> str:
        w_status = get_worker_status(db_path=self.db_path)
        worker_section = ""
        if w_status and w_status.get("running"):
            elapsed_min = int((time.time() - w_status.get("start_time", time.time())) // 60)
            queue_str = f"\n排隊中: {', '.join(w_status.get('queue', []))}" if w_status.get('queue') else ""
            worker_section = (
                f"【背景抓取中】\n"
                f"對象: {w_status.get('target')}\n"
                f"進度: 第 {w_status.get('pages', 0)} 頁 ({w_status.get('count', 0)} 則)\n"
                f"耗時: 約 {elapsed_min} 分鐘"
                f"{queue_str}\n\n"
            )
        elif w_status and not w_status.get("running"):
            worker_section = "【背景任務】無執行中任務\n\n"

        contact = get_active_contact(db_path=self.db_path)
        if not contact:
            if worker_section:
                return f"{worker_section}尚未選定作用對象，請使用 select <關鍵字> 切換。"
            return "尚未選定作用對象，請使用 select <IG_ID> 切換。"

        nick_str = f" [暱稱: {contact['nickname']}]" if ("nickname" in contact.keys() and contact["nickname"]) else ""
        return (
            f"{worker_section}"
            f"【目前對象】\n"
            f"帳號: {contact['ig_account_id']} ({contact['display_name'] or '未設定'}){nick_str}\n"
            f"狀態: {contact['status']}\n"
            f"上次同步: {contact['last_synced_at'] or '無'}\n"
            f"摘要更新: {contact['summary_updated_at'] or '無'}\n"
            f"累積未摘要: {contact['new_messages_since_summary']} 則"
        )

    @command_handler("list")
    def handle_list(self, parts: List[str], raw_text: str) -> str:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT ig_account_id, display_name, nickname, status, last_synced_at FROM contacts")
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return "目前尚未追蹤任何對象，請使用 track <IG_ID> 開始追蹤。"
        lines = ["【已追蹤對象清單】"]
        for r in rows:
            nick_str = f" [暱稱: {r['nickname']}]" if ("nickname" in r.keys() and r["nickname"]) else ""
            lines.append(f"- {r['ig_account_id']} ({r['display_name']}){nick_str} [{r['status']}]")
        return "\n".join(lines)

    @command_handler("card", "summary", "摘要", "摘要卡")
    def handle_card(self, parts: List[str], raw_text: str) -> str:
        # 解析是否要求全景長文模式 (card full 或 card -f)
        is_full_request = False
        target_account = None

        clean_parts = parts[1:]
        if clean_parts and clean_parts[0].lower() in ("full", "-f", "--full", "全景", "長文"):
            is_full_request = True
            clean_parts = clean_parts[1:]

        if clean_parts:
            target_account = clean_parts[0]

        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        if target_account:
            cursor.execute("""
                SELECT * FROM contacts
                WHERE LOWER(ig_account_id) = LOWER(?) OR LOWER(display_name) = LOWER(?) OR LOWER(nickname) = LOWER(?)
            """, (target_account, target_account, target_account))
            contact = cursor.fetchone()
        else:
            contact = get_active_contact(db_path=self.db_path)
        conn.close()

        if not contact:
            if target_account:
                return f"找不到符合「{target_account}」的對象，請確認帳號或暱稱是否正確。"
            return "尚未選定作用對象，請使用 card <IG_ID> 或先使用 select 切換對象。"

        nick_str = f" [暱稱: {contact['nickname']}]" if ("nickname" in contact.keys() and contact["nickname"]) else ""
        name_str = f"（{contact['display_name']}）" if contact["display_name"] else ""

        # 全景長文模式
        if is_full_request:
            full_summary = contact["full_history_summary"] if "full_history_summary" in contact.keys() else None
            updated_at = (contact["full_history_updated_at"] if "full_history_updated_at" in contact.keys() else None) or "尚未復盤過"
            if not full_summary:
                return (
                    f"【{contact['ig_account_id']}{name_str}{nick_str} 全景深度復盤長文】\n"
                    f"目前尚未生成全景復盤長文。\n"
                    f"可輸入「summarize_history」立即對完整歷史對話進行 7 大章節深度分析！"
                )
            return (
                f"【{contact['ig_account_id']}{name_str}{nick_str} 全景深度復盤長文】\n"
                f"（復盤時間：{updated_at}）\n\n"
                f"{full_summary.strip()}"
            )

        # 日常輕量卡模式
        summary = contact["summary_card"]
        updated_at = contact["summary_updated_at"] or "尚未更新過"

        if not summary or summary.strip() == "尚未建立摘要卡":
            return (
                f"【{contact['ig_account_id']}{name_str}{nick_str} 日常摘要卡】\n"
                f"目前尚未建立摘要卡。\n"
                f"可使用 summarize_history 或 refresh_summary 指令立即生成。"
            )

        return (
            f"【{contact['ig_account_id']}{name_str}{nick_str} 人物關係日常摘要卡】\n"
            f"（上次更新時間：{updated_at}）\n\n"
            f"{summary.strip()}\n\n"
            f"💡 輸入「card full」可查閱 7 大章節全景長篇復盤。"
        )

    @command_handler("refresh_summary")
    def handle_refresh_summary(self, parts: List[str], raw_text: str) -> str:
        target = self._resolve_target(parts)
        if not target:
            return "請指定對象：refresh_summary <IG_ID>，或先使用 select 切換對象。"
        return f"REFRESH_SUMMARY_REQUEST:{target}"

    @command_handler("summarize_history")
    def handle_summarize_history(self, parts: List[str], raw_text: str) -> str:
        target = self._resolve_target(parts)
        if not target:
            return "請指定對象：summarize_history <IG_ID>，或先使用 select 切換對象。"
        return f"SUMMARIZE_HISTORY_REQUEST:{target}"

    @command_handler("sync")
    def handle_sync(self, parts: List[str], raw_text: str) -> str:
        target = self._resolve_target(parts)
        if not target:
            return "請指定要同步的對象：sync <IG_ID>，或先使用 select 切換對象。"
        return f"SYNC_REQUEST:{target}"

    @command_handler("untrack")
    def handle_untrack(self, parts: List[str], raw_text: str) -> str:
        if len(parts) < 2:
            return "格式錯誤！請指定對象：untrack <IG_ID>"
        target = parts[1]
        conn = get_connection(self.db_path)
        with conn:
            conn.execute("UPDATE contacts SET status = 'untracked' WHERE ig_account_id = ?", (target,))
        conn.close()
        return f"已將 {target} 標記為停止追蹤。"

    @command_handler("rebuild_vectors")
    def handle_rebuild_vectors(self, parts: List[str], raw_text: str) -> str:
        target = self._resolve_target(parts)
        if not target:
            return "請指定對象：rebuild_vectors <IG_ID>，或先使用 select 切換對象。"
        return f"REBUILD_VECTORS_REQUEST:{target}"

    # ==================== 主調度入口 ====================

    def handle_message(self, raw_text: str) -> str:
        text = raw_text.strip()
        parts = text.split()
        if not parts:
            return "收到空白訊息。"

        # 1. 處理純數字選擇（多重候選確認）
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
                return f"數字超出範圍，請輸入 1 到 {len(pending_ids)} 之間的數字選擇對象。"

        # 2. 查表分發指令
        command = parts[0].lower()
        handler_name = _COMMAND_REGISTRY.get(command)
        if handler_name:
            handler = getattr(self, handler_name, None)
            if handler:
                return handler(parts, text)

        # 3. 預設退回 AI 聊天陪伴模式
        return self._handle_chat_mode(text)

    def _handle_chat_mode(self, user_text: str) -> str:
        ctx = self.memory_manager.get_full_context(user_text)
        if not ctx or not ctx[0]:
            return "目前尚未選擇討論對象！請先傳送指令：select <IG_ID> 切換對象。"

        contact, summary_card, rag_chunks, recent_context, chat_history, self_context = ctx
        contact_id = contact["id"]
        add_bot_conversation(role="user", content=user_text, contact_id=contact_id)

        # 暱稱掃描：若提及其他已設定暱稱的朋友，進行跨對象 RAG 查詢
        cross_rag_list = []
        try:
            query_emb = getattr(self.memory_manager, "last_query_embedding", None)
            contacts_with_nick = get_contacts_with_nickname(db_path=self.db_path)
            for c in contacts_with_nick:
                nick = c["nickname"]
                if nick and (nick.lower() in user_text.lower()) and c["id"] != contact_id:
                    nick_results = self.memory_manager.vector_store.query(
                        contact_id=c["id"],
                        query_text=user_text,
                        query_embedding=query_emb,
                        n_results=settings.CROSS_RAG_RESULTS
                    )
                    if nick_results:
                        snippets = "\n".join([r["text"] for r in nick_results])
                        cross_rag_list.append(f"【關於 {nick} ({c['ig_account_id']}) 的紀錄】\n{snippets}")
        except Exception:
            pass

        cross_rag_str = "\n\n---\n\n".join(cross_rag_list) if cross_rag_list else ""

        reply = self.llm_client.generate_reply(
            display_name=contact["display_name"] or contact["ig_account_id"],
            summary_card=summary_card,
            rag_chunks=rag_chunks,
            recent_context=recent_context,
            chat_history=chat_history,
            self_context=self_context,
            cross_rag=cross_rag_str,
            user_query=user_text
        )

        add_bot_conversation(role="assistant", content=reply, contact_id=contact_id)

        # 背景非同步萃取使用者自身相關資訊並寫入記憶
        def _async_extract():
            try:
                extracted = self.llm_client.extract_self_info(user_text)
                if extracted:
                    self.memory_manager.add_self_memory(extracted)
            except Exception:
                pass

        threading.Thread(target=_async_extract, daemon=True).start()

        return reply
