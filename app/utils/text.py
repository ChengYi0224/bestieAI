"""
text.py — 文字清理與字串處理通用工具。
"""
import re
from typing import Optional, List, Tuple, Dict

# 預編譯正則表示式
_BULLET_PREFIX_RE = re.compile(r"^(?:[-*•]\s*|\d+[\.\)]\s*)")
_DATE_HEADER_RE = re.compile(r"^(\d{4})[/\.-](\d{1,2})[/\.-](\d{1,2})")
_CHAT_LINE_RE = re.compile(r"^(\d{1,2}:\d{2})\s+([^\s]+)\s+(.+)$")
_LEADING_DATE_RE = re.compile(r"^\[?(\d{4})[/\.-](\d{1,2})[/\.-](\d{1,2})")

DEFAULT_IGNORE_PATTERNS = ("無", "無。", "無新增事實", "無重要事件")


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


def strip_bullet_prefix(line: str) -> str:
    """
    移除字串開頭的無序清單符號（'- ', '* ', '• '）或有序編號（如 '1. ', '01. ', '1) '）。
    """
    cleaned = line.strip()
    return _BULLET_PREFIX_RE.sub("", cleaned).strip()


def parse_bullet_list(
    text: str,
    ignore_patterns: Tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
) -> List[str]:
    """
    解析 Markdown 或條列文字。
    自動過濾空行、無效佔位詞，並剝除清單符號與有序編號前綴。
    """
    if not text or not text.strip():
        return []

    items: List[str] = []
    for line in text.strip().splitlines():
        cleaned = line.strip()
        if not cleaned or any(cleaned == p or cleaned.startswith(p) for p in ignore_patterns):
            continue
        cleaned = strip_bullet_prefix(cleaned)
        if cleaned and not any(cleaned == p or cleaned.startswith(p) for p in ignore_patterns):
            items.append(cleaned)
    return items


def normalize_to_bullet_lines(
    text: str,
    marker: str = "- ",
    ignore_patterns: Tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
) -> str:
    """
    將文字正規化為逐行以 marker 開頭的條列格式。若無有效條目則回傳空字串。
    """
    items = parse_bullet_list(text, ignore_patterns=ignore_patterns)
    if not items:
        return ""
    return "\n".join(f"{marker}{item}" for item in items)


def extract_tagged_blocks(text: str, tag: str) -> List[Tuple[str, str]]:
    """
    從字串中萃取具備 id 屬性的標籤區塊，例如 <tag id="...">內容</tag>。
    回傳 List of (id, content)。
    """
    if not text:
        return []
    pattern = re.compile(rf'<{re.escape(tag)}\s+id="([^"]+)">([\s\S]*?)</{re.escape(tag)}>')
    return pattern.findall(text)


def parse_cluster_results(text: str, tag: str = "cluster_result") -> Dict[str, List[str]]:
    """
    解析批次群組融合結果標籤區塊，轉化為群組 ID 對應有效條目清單之字典。
    """
    matches = extract_tagged_blocks(text, tag=tag)
    results: Dict[str, List[str]] = {}
    for cid, block in matches:
        lines = parse_bullet_list(block)
        if lines:
            results[cid] = lines
    return results


def extract_leading_date(text: str) -> Optional[str]:
    """
    從字串開頭提取 YYYY-MM-DD 日期（支援中括號包裹與常見斜線/破折號分隔）。
    """
    if not text:
        return None
    m = _LEADING_DATE_RE.match(text.strip())
    if not m:
        return None
    year, month, day = m.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def parse_line_chat_date_header(line: str) -> Optional[str]:
    """
    解析 LINE 匯出文字中的日期分界標頭行（例如 '2023/05/12 星期五'）。
    成功時回傳標準化 'YYYY-MM-DD'，否則回傳 None。
    """
    cleaned = line.strip()
    if not cleaned:
        return None
    m = _DATE_HEADER_RE.match(cleaned)
    if m and ("星期" in cleaned or len(cleaned) <= 15):
        year, month, day = m.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None


def parse_line_chat_message(line: str) -> Optional[Tuple[str, str, str]]:
    """
    解析 LINE 匯出文字的對話訊息行（例如 '14:20 小明 嗨你好'）。
    成功時回傳 (time_str, sender_raw, content)，否則回傳 None。
    """
    cleaned = line.strip()
    if not cleaned:
        return None
    m = _CHAT_LINE_RE.match(cleaned)
    if not m:
        return None
    time_str, sender_raw, content = m.groups()
    return time_str, sender_raw, content
