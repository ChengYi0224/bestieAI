"""
throttle.py — 記憶體內的滑動視窗失敗計數器，用於登入 / 註冊等端點的暴力嘗試防護。

單一行程內有效（重啟即清空）；若日後多行程部署，需改用共享儲存。
"""
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class AttemptThrottle:
    """在 window_seconds 內，同一 key 累積 max_attempts 次失敗即視為被鎖定。"""

    def __init__(self, max_attempts: int, window_seconds: float):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
        return q

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            now = time.monotonic()
            return len(self._prune(key, now)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now)
            self._failures[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()
