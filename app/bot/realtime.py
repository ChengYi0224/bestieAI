"""
realtime.py — IG Realtime (MQTT) 事件 payload 解析。
"""
from typing import Any, Dict, NamedTuple, Optional


class IncomingMessage(NamedTuple):
    thread_id: str
    sender_pk: str
    item_id: str
    text: str


def parse_realtime_event(event: Any) -> Optional[IncomingMessage]:
    """
    解析 instagrapi realtime 的 message 事件；非文字 / 缺少發送者的事件回傳 None。
    支援 {"message": {...}} 與頂層欄位，以及 message.value 內嵌的格式。
    """
    msg_wrapper = event.get("message", {}) if isinstance(event, dict) else {}
    if not isinstance(event, dict):
        return None
    thread_id = str(msg_wrapper.get("thread_id") or event.get("thread_id") or "")
    item_id = str(msg_wrapper.get("item_id") or event.get("item_id") or "")
    sender_pk = str(msg_wrapper.get("user_id") or event.get("user_id") or "")
    text = msg_wrapper.get("text") or event.get("text") or ""

    if not text and isinstance(msg_wrapper.get("value"), dict):
        val: Dict[str, Any] = msg_wrapper["value"]
        text = val.get("text", "")
        item_id = item_id or str(val.get("item_id", ""))
        sender_pk = sender_pk or str(val.get("user_id", ""))

    if not text or not str(sender_pk).strip():
        return None
    return IncomingMessage(thread_id, sender_pk, item_id, text)
