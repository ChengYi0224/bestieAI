import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from google import genai
from app.config import settings
from app.rate_limit import gemini_retry, _is_gemini_retryable_error

logger = logging.getLogger("bestieAI.llm")

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "system.txt"

# 依優先順序嘗試的模型陣列
CANDIDATE_MODELS: List[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]

_llm_file_handler: Optional[logging.FileHandler] = None


def get_llm_recorder(log_path: Optional[Path] = None) -> logging.Logger:
    global _llm_file_handler
    recorder = logging.getLogger("bestieAI.llm_recorder")
    recorder.setLevel(logging.INFO)
    recorder.propagate = False

    target_path = log_path or settings.LLM_LOG_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if _llm_file_handler is None or _llm_file_handler.baseFilename != str(target_path.resolve()):
        if _llm_file_handler:
            recorder.removeHandler(_llm_file_handler)
        _llm_file_handler = logging.FileHandler(str(target_path), encoding="utf-8")
        _llm_file_handler.setFormatter(logging.Formatter("%(message)s"))
        recorder.addHandler(_llm_file_handler)

    return recorder


def log_llm_call(
    model: str,
    prompt: str,
    output: Optional[str] = None,
    error: Optional[Exception] = None,
    duration_sec: float = 0.0,
    log_path: Optional[Path] = None
) -> None:
    """將每次 LLM 的 input 與 output / error 結構化記錄到 llm.log"""
    try:
        recorder = get_llm_recorder(log_path)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "SUCCESS" if error is None else "FAILED"

        lines = [
            "=" * 80,
            f"[{now_str}] [MODEL: {model}] [STATUS: {status}] (耗時: {duration_sec:.2f}s)",
            "-" * 34 + " [INPUT] " + "-" * 37,
            prompt.strip(),
        ]
        if error is not None:
            lines.extend([
                "-" * 34 + " [ERROR] " + "-" * 37,
                str(error).strip(),
            ])
        else:
            lines.extend([
                "-" * 33 + " [OUTPUT] " + "-" * 38,
                (output or "").strip(),
            ])
        lines.append("=" * 80 + "\n")

        recorder.info("\n".join(lines))
    except Exception as e:
        logger.error(f"寫入 llm.log 失敗: {e}")


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        candidate_models: Optional[List[str]] = None,
        log_path: Optional[Path] = None
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.candidate_models = candidate_models or settings.candidate_models_list
        self.log_path = log_path or settings.LLM_LOG_PATH
        self._client = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set in environment or .env")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @gemini_retry(max_short_retries=2, base_delay=1.5)
    def _call_model(self, model: str, prompt: str) -> str:
        start_t = time.time()
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt
            )
            output_text = response.text
            duration = time.time() - start_t
            log_llm_call(
                model=model,
                prompt=prompt,
                output=output_text,
                duration_sec=duration,
                log_path=self.log_path
            )
            return output_text
        except Exception as e:
            duration = time.time() - start_t
            log_llm_call(
                model=model,
                prompt=prompt,
                error=e,
                duration_sec=duration,
                log_path=self.log_path
            )
            raise

    def _generate_with_fallback(self, prompt: str, preferred_model: Optional[str] = None) -> str:
        """
        依序嘗試候選模型陣列，若遇到 503 過載、404 不支援或速率限制，自動依序切換降級至下一個模型。
        """
        models_to_try = list(self.candidate_models)
        if preferred_model:
            if preferred_model in models_to_try:
                models_to_try.remove(preferred_model)
            models_to_try.insert(0, preferred_model)

        last_error = None
        for model_name in models_to_try:
            try:
                logger.info(f"嘗試使用模型: {model_name}")
                return self._call_model(model_name, prompt)
            except Exception as e:
                last_error = e
                logger.warning(f"模型 {model_name} 呼叫失敗 ({e})，嘗試下一個候選模型...")

        raise RuntimeError(f"所有候選模型皆嘗試失敗: {models_to_try}，最後錯誤: {last_error}")

    def generate_reply(
        self,
        display_name: str,
        summary_card: str,
        rag_chunks: str,
        recent_context: str,
        user_query: str,
        chat_history: str = "",
        model: Optional[str] = None
    ) -> str:
        template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        prompt = template.format(
            display_name=display_name or "對方",
            summary_card=summary_card or "尚無摘要卡紀錄",
            rag_chunks=rag_chunks or "無特定相關紀錄",
            recent_context=recent_context or "無近期訊息",
            chat_history=chat_history or "（本輪尚無對話歷史）",
            user_query=user_query
        )
        return self._generate_with_fallback(prompt, preferred_model=model)

    def generate_summary(self, conversations_text: str, model: Optional[str] = None) -> str:
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
        return self._generate_with_fallback(prompt, preferred_model=model)

    def generate_full_history_summary(
        self,
        display_name: str,
        full_conversations_text: str,
        model: Optional[str] = None
    ) -> str:
        """
        利用 Gemini 百萬級上下文能力，對雙方自始至終的完整歷史對話進行深度關係復盤與人物全景剖析。
        """
        prompt = (
            f"你是一位細膩、洞察深刻且具備心理分析專業的好朋友兼人際顧問。"
            f"請通讀使用者與「{display_name}」自始至終的完整歷史對話紀錄，"
            f"為使用者整理出一份客觀、深刻且極具參考價值的「完整人物關係全景復盤卡」：\n\n"
            f"請包含以下核心維度：\n"
            f"1. 【人物畫像與行為特質】：\n"
            f"   - {display_name} 的個性、情感需求、防衛機制（如逃避、忽冷忽熱、需索認同等）。\n"
            f"   - 他在對話中展現的溝通習慣與情緒爆發/冷卻特徵。\n\n"
            f"2. 【關係演變時間線與溫度曲線】：\n"
            f"   - 萌芽/熱絡期：當初是怎麼聊起來的？被彼此哪些特質吸引？熱絡時的互動節奏。\n"
            f"   - 關鍵轉折點：在哪個事件或時間點開始出現態度冷淡、回覆變慢、話不投機或衝突？\n"
            f"   - 冷卻/疏離期：走向結束前的互動徵兆（敷衍、單方面付出、隔閡）。\n\n"
            f"3. 【核心矛盾與相處盲點】：\n"
            f"   - 兩人在價值觀、情緒表達或步調上的根本落差。\n"
            f"   - 造成關係無法走下去的主因，以及互動中反覆出現的卡關模式。\n\n"
            f"4. 【重大回憶與標誌性事件】：\n"
            f"   - 共同約定、承諾過的事情、深入分享過的情感秘密或有特殊意義的時刻。\n\n"
            f"5. 【當前定調與互動指引】：\n"
            f"   - 總結這段關係對使用者的本質（例如：這是一段不對等的消耗、或純屬價值觀不合的遺憾等）。\n"
            f"   - 面對未來的互動建議與心態界線。\n\n"
            f"【完整歷史對話紀錄】：\n{full_conversations_text}"
        )
        return self._generate_with_fallback(prompt, preferred_model=model)
