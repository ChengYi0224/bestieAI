import time
import random
from typing import List, Dict, Any, Optional
from instagrapi import Client
from instagrapi.types import DirectThread, DirectMessage


class IGClient:
    def __init__(self, client: Client, min_delay: float = 1.5, max_delay: float = 3.5):
        self.client = client
        self.min_delay = min_delay
        self.max_delay = max_delay

    def _sleep_jitter(self) -> None:
        delay = random.uniform(self.min_delay, self.max_delay)
        time.sleep(delay)

    def get_inbox_threads(self, amount: int = 20) -> List[DirectThread]:
        self._sleep_jitter()
        return self.client.direct_threads(amount=amount)

    def get_thread_by_username(self, username: str) -> Optional[DirectThread]:
        self._sleep_jitter()
        user_id = self.client.user_id_from_username(username)
        threads = self.client.direct_threads(amount=30)
        for thread in threads:
            for user in thread.users:
                if str(user.pk) == str(user_id):
                    return thread
        return None

    def get_thread_messages(self, thread_id: str, amount: int = 100) -> List[DirectMessage]:
        self._sleep_jitter()
        return self.client.direct_messages(thread_id=thread_id, amount=amount)

    def send_message(self, thread_id: str, text: str) -> DirectMessage:
        self._sleep_jitter()
        return self.client.direct_send(text=text, thread_ids=[thread_id])
