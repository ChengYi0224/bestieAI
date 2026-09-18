"""
text.py — 文字清理與字串處理通用工具。
"""
from typing import Optional, List


def clean_message_text(raw_text: Optional[str], default: str = "[非文字訊息]") -> str:
    """清理訊息字串，若為空或僅包含空白字元則回傳預設佔位符。"""
    if not raw_text:
        return default
    cleaned = raw_text.strip()
    return cleaned if cleaned else default


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """安全截斷長字串，長度超出時附加後綴。"""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length] + suffix


def parse_bullet_list(text: str) -> List[str]:
    """
    解析 Markdown 或符號清單文字（支援 '- ', '* ', '• ' 前綴）。
    過濾空行與無效佔位符（如 '無' 或 '無新增事實'）。
    """
    if not text or not text.strip():
        return []

    lines = text.strip().splitlines()
    items: List[str] = []
    for line in lines:
        cleaned = line.strip()
        if cleaned.startswith(("- ", "* ", "• ")):
            cleaned = cleaned[2:].strip()
        if cleaned and cleaned not in ("無", "無新增事實"):
            items.append(cleaned)
    return items
