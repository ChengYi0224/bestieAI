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
)

logger = logging.getLogger("bestieAI.pipelines.summarization")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CONCISE_SUMMARY_PROMPT_PATH = PROMPTS_DIR / "concise_summary.txt"
SUMMARY_PROMPT_PATH = PROMPTS_DIR / "summary.txt"
FULL_SUMMARY_PROMPT_PATH = PROMPTS_DIR / "full_summary.txt"
EXTRACT_SELF_PROMPT_PATH = PROMPTS_DIR / "extract_self.txt"


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

        if "無" in raw_output:
            if raw_output == "無" or "無新增事實" in raw_output:
                return []

        memories = []
        for line in raw_output.splitlines():
            line = line.strip()
            if line.startswith(("- ", "• ", "* ")):
                line = line[2:].strip()
            if line and line != "無":
                memories.append(line)
        return memories

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

        recent_msgs = get_recent_messages(contact_id=contact_id, limit=200, db_path=db_path)
        formatted = "\n".join(f"[{m['sent_at']}] {m['sender']}: {m['content']}" for m in recent_msgs)
        summary = self.generate_concise_summary(formatted)
        if summary:
            newest_id = max(m["id"] for m in all_msgs)
            update_contact_summary(contact_id, summary, newest_id, db_path=db_path)
            logger.info(f"成功更新 contact_id={contact_id} 之人物摘要卡 (最新訊息 ID: {newest_id})")
            return True
        return False
