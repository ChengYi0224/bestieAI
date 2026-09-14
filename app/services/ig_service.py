"""
ig_service.py — Instagram 私訊通訊服務。

封裝 instagrapi Client 的對話串查詢、分頁防風控訊息抓取與訊息發送。
"""
import time
import random
import logging
from typing import List, Optional, Callable
from instagrapi import Client
from instagrapi.types import DirectThread, DirectMessage
from app.core.rate_limit import ig_retry, paged_jitter

logger = logging.getLogger("bestieAI.ig_service")


class IGClient:
    def __init__(self, client: Client, min_delay: float = 1.5, max_delay: float = 3.5):
        self.client = client
        self.min_delay = min_delay
        self.max_delay = max_delay

    def _sleep_jitter(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    @ig_retry(max_retries=1)
    def get_inbox_threads(self, amount: int = 20) -> List[DirectThread]:
        self._sleep_jitter()
        return self.client.direct_threads(amount=amount)

    @ig_retry(max_retries=1)
    def get_thread_by_username(self, username: str) -> Optional[DirectThread]:
        self._sleep_jitter()

        # 0. 若傳入的是純數字 thread_id，直接嘗試撈取
        if username.isdigit() and len(username) > 10:
            try:
                logger.info(f"偵測到為 thread_id 格式 ({username})，直接撈取對話串...")
                return self.client.direct_thread(int(username))
            except Exception as e:
                logger.debug(f"直接以 thread_id 查詢失敗: {e}")

        # 1. 解析對方的 user_id
        user_id = None
        try:
            user_id = int(self.client.user_id_from_username(username))
        except Exception as e:
            logger.warning(f"無法透過 username 取得 user_id ({username}): {e}")

        # 2. 第一優先：利用 IG 官方 direct_thread_by_participants API 直接獲取兩人的唯一對話串
        if user_id:
            try:
                paged_jitter(min_delay=1.0, max_delay=2.5)
                thread_info = self.client.direct_thread_by_participants([user_id])
                thread_id = thread_info.get("thread_id") or thread_info.get("thread_v2_id")
                if not thread_id and isinstance(self.client.last_json, dict):
                    t_data = self.client.last_json.get("thread") or {}
                    thread_id = t_data.get("thread_id") or t_data.get("thread_v2_id")

                if thread_id:
                    logger.info(f"透過 participants 成功鎖定對話串 (thread_id={thread_id})")
                    paged_jitter(min_delay=1.0, max_delay=2.5)
                    return self.client.direct_thread(int(thread_id))
            except Exception as e:
                logger.info(f"direct_thread_by_participants 查詢未果 ({e})，降級進行收件匣深層搜尋...")

        # 3. 備援方案：收件匣深層分頁掃描
        cursor = None
        for page_idx in range(5):  # 最多翻 5 頁（約 100 筆對話串）
            paged_jitter(min_delay=1.0, max_delay=2.5)
            try:
                threads_chunk, cursor = self.client.direct_threads_chunk(cursor=cursor)
            except Exception as e:
                logger.warning(f"掃描收件匣分頁異常: {e}")
                break

            for thread in threads_chunk:
                all_participants = list(thread.users)
                if thread.inviter:
                    all_participants.append(thread.inviter)

                for u in all_participants:
                    if (user_id and str(u.pk) == str(user_id)) or (u.username and u.username.lower() == username.lower()):
                        logger.info(f"在收件匣第 {page_idx + 1} 頁找到與 {username} 的對話串！")
                        return thread

            if not cursor:
                break

        return None

    @ig_retry(max_retries=1)
    def get_thread_messages(
        self,
        thread_id: str,
        amount: int = 100,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        batch_rest_pages: int = 5,
        batch_rest_seconds: float = 25.0,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[DirectMessage]:
        """
        手動分頁撈取訊息，每頁（20 則）之間插入隨機延遲，支援長時間批次休眠以防風控。
        amount=0 表示不限制，一路抓到該對話串最初的那一則。
        """
        params = {
            "visual_message_return_type": "unseen",
            "direction": "older",
            "seq_id": "40065",
            "limit": "20",
        }
        cursor = None
        items = []
        page = 0

        while True:
            if cursor:
                params["cursor"] = cursor

            if page > 0:
                target_rest_interval = getattr(self, "_current_batch_rest_interval", batch_rest_pages)
                if batch_rest_pages > 0 and page % target_rest_interval == 0:
                    rest_time = random.uniform(batch_rest_seconds * 0.8, batch_rest_seconds * 2.2)
                    logger.info(f"已爬取 {page} 頁（{len(items)} 則），啟動風控防禦深層休眠 {rest_time:.1f} 秒...")
                    time.sleep(rest_time)
                    self._current_batch_rest_interval = random.randint(max(3, batch_rest_pages - 1), batch_rest_pages + 2)
                else:
                    paged_jitter(min_delay=min_delay, max_delay=max_delay)
            else:
                self._sleep_jitter()

            try:
                result = self.client.private_request(
                    f"direct_v2/threads/{thread_id}/", params=params
                )
            except Exception as e:
                logger.error(f"分頁撈取訊息失敗 (page={page}, cursor={cursor}): {e}")
                raise

            thread_data = result.get("thread", {})
            for item in thread_data.get("items", []):
                items.append(item)

            cursor = thread_data.get("oldest_cursor")
            page += 1
            logger.info(f"  已抓第 {page} 頁，累計 {len(items)} 則，cursor={bool(cursor)}")

            if progress_callback and page % 5 == 0:
                try:
                    progress_callback(len(items), page)
                except Exception as cb_e:
                    logger.warning(f"progress_callback 異常: {cb_e}")

            if not cursor or (amount and len(items) >= amount):
                break

        if amount:
            items = items[:amount]

        from instagrapi.extractors import extract_direct_message
        return [extract_direct_message(i) for i in items]

    @ig_retry(max_retries=1)
    def send_message(self, thread_id: str, text: str) -> DirectMessage:
        self._sleep_jitter()
        return self.client.direct_send(text=text, thread_ids=[thread_id])
