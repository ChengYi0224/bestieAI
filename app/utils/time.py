"""
time.py — 時間解析與格式化通用工具。
"""
from datetime import datetime, timezone
from typing import Optional


def parse_time_str(time_str: Optional[str]) -> Optional[datetime]:
    """安全解析時間字串，支援 ISO 8601、UTC 結尾 'Z' 與 YYYY-MM-DD 格式。"""
    if not time_str or not str(time_str).strip():
        return None
    cleaned = str(time_str).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except Exception:
        pass
    try:
        return datetime.strptime(cleaned[:10], "%Y-%m-%d")
    except Exception:
        return None


def format_time(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化 datetime 物件為字串，若傳入 None 則回傳空字串。"""
    if not dt:
        return ""
    return dt.strftime(fmt)


def now_utc_iso() -> str:
    """取得當前 UTC 時間之標準 ISO 8601 字串。"""
    return datetime.now(timezone.utc).isoformat()
