"""
progress.py — 進度回報輔助。進度回報失敗不應中斷主流程，但需留下紀錄以便排查。
"""
import logging
from typing import Callable, Optional

logger = logging.getLogger("bestieAI.progress")


def notify_progress(callback: Optional[Callable[..., None]], *args) -> None:
    """安全呼叫 progress_callback；callback 為 None 時略過，發生例外時記錄警告而不拋出。"""
    if not callback:
        return
    try:
        callback(*args)
    except Exception as e:
        logger.warning(f"progress_callback 執行失敗（已忽略）: {e}")
