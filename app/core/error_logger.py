"""
error_logger.py — 集中式錯誤日誌模組。

提供應用程式全域統一的 error.log 記錄機制：
- get_error_logger() 取得帶 RotatingFileHandler 的 logger
- log_error(e, context) 快速記錄例外，附帶呼叫位置與脈絡資訊
"""
import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.core.config import settings

_error_file_handler: Optional[RotatingFileHandler] = None


def get_error_logger() -> logging.Logger:
    """
    取得集中式 error logger（單例）。
    輸出至 logs/error.log，最大 5MB × 保留 3 份 rotate。
    """
    global _error_file_handler

    logger = logging.getLogger("bestieAI.error")
    logger.setLevel(logging.ERROR)
    logger.propagate = True  # 仍會傳至 root logger（console）

    log_path: Path = settings.ERROR_LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if _error_file_handler is None or _error_file_handler.baseFilename != str(log_path.resolve()):
        if _error_file_handler is not None:
            logger.removeHandler(_error_file_handler)

        _error_file_handler = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        _error_file_handler.setLevel(logging.ERROR)
        _error_file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(_error_file_handler)

    return logger


def log_error(
    e: Exception,
    context: str = "",
    logger_name: Optional[str] = None,
) -> None:
    """
    快速記錄例外至 error.log。

    Args:
        e: 捕捉到的例外物件。
        context: 呼叫情境描述（例如函式名稱、操作說明）。
        logger_name: 可選，指定子模組名稱（預設使用 bestieAI.error）。
    """
    err_logger = get_error_logger()
    name = logger_name or "bestieAI.error"
    child = err_logger.getChild(name) if logger_name else err_logger

    tb = traceback.format_exc()
    msg = f"[{context}] {type(e).__name__}: {e}"
    if tb and tb.strip() != "NoneType: None":
        child.error("%s\n%s", msg, tb)
    else:
        child.error(msg)
