"""
activity.py — 追蹤「正在使用 IG 連線進行長時間抓取」的活動，供背景補抓判斷是否該讓出連線。
"""
import threading
from contextlib import contextmanager
from typing import Iterator


class ActivityTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0

    @contextmanager
    def track(self) -> Iterator[None]:
        with self._lock:
            self._count += 1
        try:
            yield
        finally:
            with self._lock:
                self._count -= 1

    def active(self) -> bool:
        with self._lock:
            return self._count > 0
