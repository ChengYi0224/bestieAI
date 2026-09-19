"""
base.py — Repository 基礎類別與連線裝飾器。
"""
import functools
import sqlite3
from pathlib import Path
from typing import Optional, Callable

from app.storage.db import get_connection


def with_connection(readonly: bool = False):
    """
    Decorator 語法糖：自動為 Repository 方法注入 connection 與 cursor，並在寫入時自動 commit。
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            conn = self.get_conn()
            try:
                if readonly:
                    return func(self, conn, *args, **kwargs)
                else:
                    with conn:
                        return func(self, conn, *args, **kwargs)
            finally:
                conn.close()
        return wrapper
    return decorator


class BaseRepository:
    """資料庫存取庫基礎類別，持有 db_path 並提供連線工廠。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def get_conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)
