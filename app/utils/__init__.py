"""
utils — 通用輔助工具模組。
提供時間、數學向量、文字清理與資料庫結構之底層輔助實作。
"""
from app.utils.time import parse_time_str, format_time, now_utc_iso
from app.utils.math import cosine_similarity, cosine_distance
from app.utils.text import (
    clean_message_text,
    truncate_text,
    strip_bullet_prefix,
    parse_bullet_list,
    normalize_to_bullet_lines,
    extract_tagged_blocks,
    parse_cluster_results,
    extract_leading_date,
    parse_line_chat_date_header,
    parse_line_chat_message,
    extract_date_and_time,
    format_chat_messages,
)
from app.utils.db import row_to_dict, get_row_field

__all__ = [
    "parse_time_str",
    "format_time",
    "now_utc_iso",
    "cosine_similarity",
    "cosine_distance",
    "clean_message_text",
    "truncate_text",
    "strip_bullet_prefix",
    "parse_bullet_list",
    "normalize_to_bullet_lines",
    "extract_tagged_blocks",
    "parse_cluster_results",
    "extract_leading_date",
    "parse_line_chat_date_header",
    "parse_line_chat_message",
    "extract_date_and_time",
    "format_chat_messages",
    "row_to_dict",
    "get_row_field",
]

