from pathlib import Path
from typing import Optional
from google import genai
from app.config import settings

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "system.txt"


class LLMClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self._client = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set in environment or .env")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate_reply(
        self,
        display_name: str,
        summary_card: str,
        rag_chunks: str,
        recent_context: str,
        user_query: str,
        model: str = "gemini-3.8-flash"
    ) -> str:
        template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        prompt = template.format(
            display_name=display_name or "對方",
            summary_card=summary_card or "尚無摘要卡紀錄",
            rag_chunks=rag_chunks or "無特定相關紀錄",
            recent_context=recent_context or "無近期訊息",
            user_query=user_query
        )

        response = self.client.models.generate_content(
            model=model,
            contents=prompt
        )
        return response.text

    def generate_summary(self, conversations_text: str, model: str = "gemini-3.8-flash") -> str:
        prompt = (
            "你是一位細心且深刻洞察人際關係的分析助理。請分析以下這段對話歷史，"
            "萃取並整理出一份精簡的「人物關係摘要卡」：\n\n"
            "包含：\n"
            "1. 人物個性與特質\n"
            "2. 兩人的主要互動模式與聊天頻率風格\n"
            "3. 提及的重要事件、回憶或關鍵話題\n"
            "4. 目前關係的可能狀態或潛在張力\n\n"
            f"對話歷史：\n{conversations_text}"
        )
        response = self.client.models.generate_content(
            model=model,
            contents=prompt
        )
        return response.text
