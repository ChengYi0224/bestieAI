import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from google import genai
from app.config import settings
from app.rate_limit import gemini_retry, _is_gemini_retryable_error

logger = logging.getLogger("bestieAI.llm")

PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.txt"
SUMMARY_PROMPT_PATH = PROMPTS_DIR / "summary.txt"
FULL_SUMMARY_PROMPT_PATH = PROMPTS_DIR / "full_summary.txt"
EXTRACT_SELF_PROMPT_PATH = PROMPTS_DIR / "extract_self.txt"
PROMPT_TEMPLATE_PATH = SYSTEM_PROMPT_PATH  # 相容舊常數名稱

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
    """將每次 LLM 的 input 與 output / error 結構化記錄到 llm.log（受 settings.ENABLE_LLM_LOG 控制）"""
    if not settings.ENABLE_LLM_LOG:
        return
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


def log_llm_execution(func):
    """Decorator：自動計算耗時並在執行成功或拋出異常時寫入 llm.log。"""
    import functools
    @functools.wraps(func)
    def wrapper(self, model: str, prompt: str, *args, **kwargs):
        start_t = time.time()
        try:
            output = func(self, model, prompt, *args, **kwargs)
            log_llm_call(model=model, prompt=prompt, output=output, duration_sec=time.time() - start_t, log_path=self.log_path)
            return output
        except Exception as e:
            log_llm_call(model=model, prompt=prompt, error=e, duration_sec=time.time() - start_t, log_path=self.log_path)
            raise
    return wrapper


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
    @log_llm_execution
    def _call_model(self, model: str, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=model,
            contents=prompt
        )
        return response.text

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
        self_context: str = "",
        cross_rag: str = "",
        model: Optional[str] = None
    ) -> str:
        template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        prompt = template.format(
            display_name=display_name or "對方",
            summary_card=summary_card or "尚無摘要卡紀錄",
            self_context=self_context or "無相關使用者背景",
            cross_rag=cross_rag or "無提及特定對象之紀錄",
            rag_chunks=rag_chunks or "無特定相關紀錄",
            recent_context=recent_context or "無近期訊息",
            chat_history=chat_history or "（本輪尚無對話歷史）",
            user_query=user_query
        )
        return self._generate_with_fallback(prompt, preferred_model=model)

    def extract_self_info(self, user_query: str, model: Optional[str] = None) -> str:
        """從使用者提問中萃取自身生活近況、事實、習慣或偏好。若無則回傳空字串。"""
        template = EXTRACT_SELF_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.format(user_query=user_query)
        result = self._generate_with_fallback(prompt, preferred_model=model).strip()
        if not result or result == "無" or result.startswith("無。") or result.startswith("無\n"):
            return ""
        return result

    def generate_summary(self, conversations_text: str, model: Optional[str] = None) -> str:
        template = SUMMARY_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.format(conversations_text=conversations_text)
        return self._generate_with_fallback(prompt, preferred_model=model)

    def generate_full_history_summary(
        self,
        display_name: str,
        full_conversations_text: str,
        model: Optional[str] = None
    ) -> str:
        """
        利用 Gemini 百萬級上下文能力，對雙方自始至終的完整歷史對話進行深度關係復盤與人物全景剖析。
        預設採用 gemini-3.5-flash-lite 輕量穩定生成。
        """
        template = FULL_SUMMARY_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = template.format(
            display_name=display_name or "對方",
            full_conversations_text=full_conversations_text
        )
        target_model = model or settings.GEMINI_FULL_SUMMARY_MODEL
        return self._generate_with_fallback(prompt, preferred_model=target_model)
