import pytest
from unittest.mock import MagicMock
from instagrapi import Client
from instagrapi.realtime import RealtimeClient
from app.poller import BotPoller
from app.ig import IGClient

def test_poller_setup_realtime_contract():
    """驗證 BotPoller._setup_realtime 呼叫的函式真實存在於 instagrapi.Client 與 RealtimeClient"""
    client = Client()
    rt_client = client.realtime_client()

    assert hasattr(client, "realtime_connect"), "Client 缺少 realtime_connect"
    assert hasattr(client, "realtime_on"), "Client 缺少 realtime_on"
    assert hasattr(rt_client, "direct_subscribe"), "RealtimeClient 缺少 direct_subscribe"

    poller = BotPoller()
    poller.bot_client = client

    # 模擬連線動作避免觸發真實網路 IO
    client.realtime_connect = MagicMock(return_value=rt_client)
    client.realtime_on = MagicMock()
    rt_client.direct_subscribe = MagicMock()

    # 執行 _setup_realtime，不得拋出 AttributeError
    poller._setup_realtime()

    client.realtime_connect.assert_called_once()
    client.realtime_on.assert_called_with("message", poller._on_realtime_message)
    rt_client.direct_subscribe.assert_called_once()

def test_poller_realtime_message_processing():
    """驗證真實 Realtime message 事件 payload 解析與分派"""
    mock_router = MagicMock()
    mock_router.handle_message.return_value = "測試回覆"

    poller = BotPoller(router=mock_router)
    poller.bot_client = Client()
    poller.bot_client.authorization_data = {"ds_user_id": "11111"}
    mock_ig = MagicMock(spec=IGClient)
    poller.bot_ig = mock_ig

    # 模擬真實 IG Iris message sync 封裝格式
    event_payload = {
        "message": {
            "thread_id": "thread_abc_123",
            "item_id": "msg_999",
            "user_id": 22222,  # 使用者 ID
            "text": "help"
        }
    }

    poller._on_realtime_message(event_payload)

    # 驗證 router 接收到正確指令
    mock_router.handle_message.assert_called_with("help")
    # 驗證發送回覆至正確的 thread
    mock_ig.send_message.assert_called_with("thread_abc_123", "測試回覆")

def test_poller_ignores_own_bot_messages():
    """驗證 Bot 發送的訊息不會被自我重複處理"""
    mock_router = MagicMock()
    poller = BotPoller(router=mock_router)
    poller.bot_client = Client()
    poller.bot_client.authorization_data = {"ds_user_id": "11111"}

    event_payload = {
        "message": {
            "thread_id": "thread_abc_123",
            "item_id": "msg_own",
            "user_id": 11111,  # 與 bot_client.user_id 相同
            "text": "這是 bot 自己發的"
        }
    }

    poller._on_realtime_message(event_payload)
    mock_router.handle_message.assert_not_called()

