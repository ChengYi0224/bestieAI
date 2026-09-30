"""
sync_service.py — 私訊增量同步與背景補抓（依使用者使用自己的 IG 連線）。

PIPELINE:
  sync(target, amount, user_id)
       │  前景：用該使用者的 IG 連線抓最新 amount 則（0 = 一路抓到接上本地紀錄）並存入 SQLite
       ▼
  (amount > 0 且尚未接上本地既有紀錄)
       ▼
  背景執行緒 _backfill_worker：從 cursor 往更早歷史續抓，每輪存檔，直到接上或抓完
  （前景有任務時讓出連線，避免同一個 IG 帳號被同時打 API）
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.commands.base import SYNC_FAILED
from app.core.error_logger import log_error
from app.services.ig_pool import IGClientPool
from app.sources.factory import SourceAdapterFactory

logger = logging.getLogger("bestieAI.bot.sync")


class MessageSyncService:
    BACKFILL_CHUNK = 100  # 背景補抓每輪抓取則數（每輪之間會釋放 IG 鎖並檢查前景任務）
    BUSY_POLL_SECONDS = 5.0

    def __init__(self, ig_pool: IGClientPool, is_busy: Callable[[], bool]):
        self._pool = ig_pool
        self._is_busy = is_busy
        self._guard = threading.Lock()
        self._backfilling: Set[Tuple[int, str]] = set()

    @staticmethod
    def _to_db_rows(normalized_msgs) -> List[Dict[str, Any]]:
        return [
            {"ig_item_id": m.external_id, "sender": m.sender, "content": m.content, "sent_at": m.sent_at}
            for m in normalized_msgs
        ]

    def sync(self, target: str, amount: int = 0, *, user_id: int) -> int:
        """
        同步指定對象的最新私訊。回傳新增則數；失敗回傳 SYNC_FAILED（已 fallback 使用本地紀錄）。
        amount > 0：前景只抓最新 amount 則即回傳，其餘歷史交由背景續抓。
        """
        if not target:
            return 0
        try:
            from app.storage.db import get_or_create_contact, save_messages, get_latest_item_ids
            ig = self._pool.get(user_id)
            contact_id = get_or_create_contact(ig_account_id=target, display_name=target, user_id=user_id)
            existing_ids = get_latest_item_ids(contact_id=contact_id, limit=50)
            adapter = SourceAdapterFactory.create("instagram", ig_client=ig)
            fetch_kwargs: Dict[str, Any] = {"target": target, "amount": amount, "stop_item_ids": existing_ids}
            if amount:
                fetch_kwargs["truncate"] = False  # 保留整頁結果，避免與背景續抓的 cursor 之間出現斷層
            with self._pool.lock_for(user_id):
                normalized_msgs = adapter.fetch_messages(**fetch_kwargs)
            inserted = save_messages(contact_id=contact_id, messages=self._to_db_rows(normalized_msgs))
            logger.info(f"Auto-Sync 完成：user={user_id} {target} 獲取 {len(normalized_msgs)} 則，新增 {inserted} 則私訊。")

            cursor = getattr(adapter, "last_cursor", None)
            thread_id = getattr(adapter, "last_thread_id", None)
            if (
                amount
                and isinstance(cursor, str) and cursor
                and isinstance(thread_id, str) and thread_id
                and getattr(adapter, "last_hit_anchor", False) is not True
            ):
                self._start_backfill(user_id, target, contact_id, thread_id, cursor, existing_ids)
            return inserted
        except Exception as e:
            logger.warning(f"Auto-Sync 同步 user={user_id} {target} 失敗 ({e})，Fallback 使用資料庫現有紀錄。")
            log_error(e, context=f"MessageSyncService.sync — user={user_id} {target}", logger_name="bestieAI.bot.sync")
            return SYNC_FAILED

    def _start_backfill(
        self, user_id: int, target: str, contact_id: int, thread_id: str, cursor: str, anchor_ids: Set[str]
    ) -> None:
        """啟動背景執行緒，從 cursor 往更早的歷史續抓，直到接上本地既有紀錄或抓完為止。"""
        key = (user_id, target)
        with self._guard:
            if key in self._backfilling:
                return
            self._backfilling.add(key)
        threading.Thread(
            target=self._backfill_worker,
            args=(user_id, target, contact_id, thread_id, cursor, anchor_ids),
            daemon=True,
        ).start()
        logger.info(f"背景補抓已啟動：user={user_id} {target}")

    def _backfill_worker(
        self, user_id: int, target: str, contact_id: int, thread_id: str, cursor: Optional[str], anchor_ids: Set[str]
    ) -> None:
        from app.storage.db import save_messages
        total = 0
        try:
            while cursor:
                # 讓出 IG 連線給前景任務，避免同時打 API 觸發風控
                while self._is_busy():
                    time.sleep(self.BUSY_POLL_SECONDS)
                ig = self._pool.get(user_id)
                adapter = SourceAdapterFactory.create("instagram", ig_client=ig)
                with self._pool.lock_for(user_id):
                    msgs = adapter.fetch_messages(
                        target=target,
                        amount=self.BACKFILL_CHUNK,
                        stop_item_ids=anchor_ids,
                        start_cursor=cursor,
                        thread_id=thread_id,
                        truncate=False,
                    )
                total += save_messages(contact_id=contact_id, messages=self._to_db_rows(msgs))
                nxt = getattr(adapter, "last_cursor", None)
                cursor = nxt if isinstance(nxt, str) and nxt else None
            logger.info(f"背景補抓完成：user={user_id} {target} 共補入 {total} 則。")
        except Exception as e:
            logger.warning(f"背景補抓 user={user_id} {target} 中斷（已補入 {total} 則）: {e}")
            log_error(e, context=f"MessageSyncService._backfill_worker — user={user_id} {target}", logger_name="bestieAI.bot.sync")
        finally:
            with self._guard:
                self._backfilling.discard((user_id, target))
