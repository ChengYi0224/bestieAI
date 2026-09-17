"""
follower.py — Follower 監控 Command Handler（預留介面）。
"""
from app.commands.base import CommandResult
from app.commands.commands import FollowerSnapshotCommand, CheckUnfollowersCommand


class FollowerHandler:
    """Follower 監控 Handler（介面已預留，待實作）。"""

    def handle_follower_snapshot(self, cmd: FollowerSnapshotCommand) -> CommandResult:
        """預留：抓取目前 follower 快照並入庫。"""
        return CommandResult(
            success=True,
            message="【Follower 監控】此功能已預留介面，即將支援快照與退追檢測。",
            data={"status": "not_implemented"}
        )

    def handle_check_unfollowers(self, cmd: CheckUnfollowersCommand) -> CommandResult:
        """預留：比對最近兩次 follower 快照，抓出退追名單。"""
        return CommandResult(
            success=True,
            message="【退追檢測】此功能已預留介面，即將支援退追比對。",
            data={"status": "not_implemented"}
        )
