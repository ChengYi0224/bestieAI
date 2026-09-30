"""
scope.py — 租戶範圍（user scope）標記，供 Repository 與相容轉接層共用。
"""
from typing import Tuple, Union


class _AllUsers:
    """跨租戶查詢的明確標記。僅限內部管線 / 背景排程等本來就不屬於單一登入使用者的呼叫端使用。"""

    def __repr__(self) -> str:
        return "ALL_USERS"


ALL_USERS = _AllUsers()
UserScope = Union[int, _AllUsers]


def scope_clause(user_id: UserScope) -> Tuple[str, tuple]:
    """回傳 (SQL 條件片段, 參數)。user_id 必須明確指定為整數或 ALL_USERS，不接受 None 以免漏傳時靜默跨租戶。"""
    if user_id is ALL_USERS:
        return "1 = 1", ()
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise TypeError(f"user_id 必須為 int 或 ALL_USERS，收到 {user_id!r}")
    return "user_id = ?", (user_id,)
