"""
db.py — 資料庫與資料結構輔助工具。
"""
import sqlite3
from typing import Any, Dict, Optional


def row_to_dict(row: Any) -> Dict[str, Any]:
    """
    安全將資料列物件（sqlite3.Row、dict 或其他 Mapping）轉換為標準 Python dict。
    若傳入 None 則回傳空字典。
    """
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, sqlite3.Row):
        return {key: row[key] for key in row.keys()}
    if hasattr(row, "keys") and hasattr(row, "__getitem__"):
        try:
            return {k: row[k] for k in row.keys()}
        except Exception:
            pass
    if hasattr(row, "__dict__"):
        return dict(row.__dict__)
    return {}


def get_row_field(row: Any, field_name: str, default: Any = None) -> Any:
    """
    安全讀取資料列欄位，相容 sqlite3.Row 與一般 dict。
    """
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(field_name, default)
    if isinstance(row, sqlite3.Row):
        try:
            return row[field_name]
        except (IndexError, KeyError):
            return default
    if hasattr(row, field_name):
        return getattr(row, field_name, default)
    return default
