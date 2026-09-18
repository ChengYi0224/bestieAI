"""
summarization.py — 人物摘要卡與全景復盤管線（Persona Summarization Pipeline）。
職責：
1. 自行讀取 summary.txt、full_summary.txt、extract_self.txt 提示詞。
2. 自行組裝對話歷史內容，呼叫 GeminiClient 產生：
   - 300~500 字日常人物精簡摘要卡
   - 長篇全景復盤分析
   - 使用者自身偏好與事實記憶
3. 檢查訊息累積數量與天數門檻，決定是否觸發自動更新。
"""
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.clients.gemini import GeminiClient
from app.storage.db import (
    get_recent_messages,
    get_messages,
    update_contact_summary,
    get_active_contact,
    get_contact_events,
)

logger = logging.getLogger("bestieAI.pipelines.summarization")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CONCISE_SUMMARY_PROMPT_PATH = PROMPTS_DIR / "summary" / "concise.txt"
SUMMARY_PROMPT_PATH = PROMPTS_DIR / "summary" / "summary.txt"
FULL_SUMMARY_PROMPT_PATH = PROMPTS_DIR / "summary" / "full.txt"
EXTRACT_SELF_PROMPT_PATH = PROMPTS_DIR / "events" / "extract_self.txt"


class Summarizer:
    """人物摘要與全景復盤分析器。"""

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self.gemini_client = gemini_client or GeminiClient()

    def generate_concise_summary(self, conversations_text: str) -> str:
        """生成 300~500 字日常人物摘要卡。"""
        template = CONCISE_SUMMARY_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.format(content=conversations_text)
        return self.gemini_client.generate_text(
            prompt,
            preferred_model="gemini-3.8-flash",
            candidate_models=["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"]
        ).strip()

    def generate_full_summary(self, conversations_text: str, display_name: str = "對方") -> str:
        """生成深度全景復盤長文。"""
        template = FULL_SUMMARY_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.format(display_name=display_name, full_conversations_text=conversations_text)
        return self.gemini_client.generate_text(
            prompt,
            preferred_model="gemini-3.8-flash",
            candidate_models=["gemini-3.8-flash", "gemini-3.7-flash"]
        ).strip()

    def extract_self_memories(self, conversations_text: str) -> List[str]:
        """從對話中提煉使用者自身的偏好與背景事實。"""
        template = EXTRACT_SELF_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.format(user_query=conversations_text)
        raw_output = self.gemini_client.generate_text(
            prompt,
            preferred_model="gemini-3.5-flash-lite",
            candidate_models=["gemini-3.5-flash-lite", "gemini-3.8-flash"]
        ).strip()

        from app.utils import parse_bullet_list
        return parse_bullet_list(raw_output)

    def check_and_update_summary(
        self,
        contact_id: int,
        force: bool = False,
        message_threshold: int = 50,
        db_path: Optional[Any] = None
    ) -> bool:
        """檢查特定聯絡人累積未彙總訊息數，達標或強制時更新人物摘要卡。"""
        contact = get_active_contact(contact_id=contact_id, db_path=db_path)
        if not contact:
            return False

        last_id = contact.get("last_summarized_msg_id") or 0
        all_msgs = get_messages(contact_id=contact_id, db_path=db_path)
        if not all_msgs:
            return False

        new_msgs = [m for m in all_msgs if m["id"] > last_id]
        if not force and len(new_msgs) < message_threshold:
            return False

        # 優先取用已提煉的 consolidated 事件記憶 + 最近 20 則最新互動溫度
        consolidated_events = get_contact_events(contact_id, status="consolidated", db_path=db_path)
        recent_msgs = get_recent_messages(contact_id=contact_id, limit=20, db_path=db_path)

        if consolidated_events:
            sections = []
            ev_lines = []
            for ev in consolidated_events:
                t_str = f"[{ev['start_time']}] " if ev["start_time"] else ""
                ev_lines.append(f"- {t_str}{ev['content']}")
            sections.append("【過往重要事件記憶（Consolidated Events）】:\n" + "\n".join(ev_lines))

            if recent_msgs:
                msg_lines = []
                for m in recent_msgs:
                    sender_label = "我" if m["sender"] == "me" else "對方"
                    time_prefix = f"[{m['sent_at']}] " if m["sent_at"] else ""
                    msg_lines.append(f"{time_prefix}{sender_label}: {m['content']}")
                sections.append("【最近 20 則最新互動紀錄（即時氛圍與溫度）】:\n" + "\n".join(msg_lines))

            payload = "\n\n".join(sections)
        elif recent_msgs:
            payload = "\n".join(f"[{m['sent_at']}] {m['sender']}: {m['content']}" for m in recent_msgs)
        else:
            return False

        summary = self.generate_concise_summary(payload)
        if summary:
            newest_id = max(m["id"] for m in all_msgs)
            update_contact_summary(contact_id, summary, newest_id, db_path=db_path)
            logger.info(f"成功更新 contact_id={contact_id} 之人物摘要卡 (最新訊息 ID: {newest_id})")
            return True
        return False
