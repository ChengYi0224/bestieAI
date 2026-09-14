"""
rate_limit.py — 統一的速率限制與重試工具。

支援：
- IG API：ClientThrottledError、PleaseWaitFewMinutes → 30 分鐘等待後繼續
- Gemini API：ClientError 429 → 短指數退避（最多 3 次），超過則 30 分鐘等待
- 分頁請求間：每頁強制插入 jitter 延遲
"""
import time
import random
import logging
import functools
from typing import Callable, TypeVar, Any

from instagrapi.exceptions import (
    ClientThrottledError,
    PleaseWaitFewMinutes,
    ClientForbiddenError,
    RateLimitError,
)
from google.genai.errors import ClientError

logger = logging.getLogger("bestieAI.rate_limit")

F = TypeVar("F", bound=Callable[..., Any])

# 觸發「長等待」的冷卻時間（秒）
LONG_WAIT_SECONDS = 30 * 60  # 30 分鐘

# IG 觸發限速的例外類型
_IG_THROTTLE_EXCEPTIONS = (
    ClientThrottledError,
    PleaseWaitFewMinutes,
    ClientForbiddenError,
    RateLimitError,
)


from google.genai.errors import ClientError, ServerError, APIError

def _is_gemini_retryable_error(exc: Exception) -> bool:
    """判斷是否為 Gemini 可重試錯誤（429 頻率限制、503 伺服器過載、500/502/504 暫時中斷）。"""
    if isinstance(exc, (ClientError, ServerError, APIError)):
        code = getattr(exc, "code", None)
        if code in (429, 500, 502, 503, 504):
            return True
        msg = str(exc).lower()
        if "high demand" in msg or "unavailable" in msg or "quota" in msg or "resource_exhausted" in msg:
            return True
    # 相容 google.api_core
    try:
        from google.api_core.exceptions import ResourceExhausted, TooManyRequests, ServiceUnavailable
        if isinstance(exc, (ResourceExhausted, TooManyRequests, ServiceUnavailable)):
            return True
    except ImportError:
        pass
    return False


def wait_with_log(seconds: float, reason: str = "") -> None:
    """記錄 log 後等待指定秒數，每分鐘印一次進度。"""
    minutes = seconds / 60
    logger.warning(f"速率限制觸發 ({reason})，等待 {minutes:.1f} 分鐘後繼續...")
    elapsed = 0.0
    interval = 60.0  # 每分鐘報告一次
    while elapsed < seconds:
        sleep_chunk = min(interval, seconds - elapsed)
        time.sleep(sleep_chunk)
        elapsed += sleep_chunk
        remaining = seconds - elapsed
        if remaining > 0:
            logger.info(f"  ⏳ 還剩 {remaining / 60:.1f} 分鐘...")
    logger.info("等待結束，繼續執行。")


def ig_retry(max_retries: int = 1) -> Callable[[F], F]:
    """
    裝飾器：捕捉 IG 限速例外，等待 LONG_WAIT_SECONDS 後重試。
    max_retries=1 代表最多重試 1 次（共執行 2 次）。
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except _IG_THROTTLE_EXCEPTIONS as e:
                    if attempt < max_retries:
                        wait_with_log(LONG_WAIT_SECONDS, reason=f"IG {type(e).__name__}")
                    else:
                        logger.error(f"IG 限速，已重試 {max_retries} 次仍失敗，拋出例外。")
                        raise
        return wrapper  # type: ignore
    return decorator


def gemini_retry(max_short_retries: int = 2, base_delay: float = 1.5) -> Callable[[F], F]:
    """
    裝飾器：捕捉 Gemini 429/503 等短暫尖峰異常，以 1.5s~3s 快速重試 2 次。
    若該模型依然失敗，立即拋出異常，交由外層 _generate_with_fallback 自動切換下一個候選模型，
    絕不在單一模型上長等待。
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(max_short_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if _is_gemini_retryable_error(e) and attempt < max_short_retries - 1:
                        delay = base_delay * (attempt + 1) + random.uniform(0.5, 1.0)
                        logger.warning(f"Gemini API 暫時繁忙 ({e})，等待 {delay:.1f} 秒後重試...")
                        time.sleep(delay)
                    else:
                        raise
        return wrapper  # type: ignore
    return decorator


def paged_jitter(min_delay: float = 1.5, max_delay: float = 4.0) -> None:
    """分頁請求之間的隨機延遲，供手動插入迴圈中使用。"""
    time.sleep(random.uniform(min_delay, max_delay))
