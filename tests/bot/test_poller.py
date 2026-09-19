import pytest
from unittest.mock import MagicMock
from instagrapi import Client
from instagrapi.realtime import RealtimeClient
from app.bot.poller import BotPoller
from app.services.ig_service import IGClient

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
    from app.commands.base import CommandResult
    mock_router = MagicMock()
    mock_router.handle_message_structured.return_value = CommandResult(
        success=True, message="測試回覆", action_type=None
    )

    poller = BotPoller(router=mock_router)
    poller.allowed_main_pk = "22222"  # 設定授權主帳號 ID
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

    # 驗證 router 接收到正確指令與發訊者 PK
    mock_router.handle_message_structured.assert_called_with("help", sender_pk="22222")
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


def test_poller_blocks_unauthorized_users():
    """驗證非主帳號白名單之外部私訊會被 @require_whitelist 靜默攔截拋棄"""
    mock_router = MagicMock()
    poller = BotPoller(router=mock_router)
    poller.allowed_main_pk = "99999"  # 僅允許主帳號
    poller.bot_client = Client()
    poller.bot_client.authorization_data = {"ds_user_id": "11111"}
    mock_ig = MagicMock(spec=IGClient)
    poller.bot_ig = mock_ig

    # 陌生人傳來 track 或 status 指令
    event_payload = {
        "message": {
            "thread_id": "thread_stranger",
            "item_id": "msg_hack_1",
            "user_id": "88888",  # 非白名單
            "text": "track victim_user"
        }
    }

    poller._on_realtime_message(event_payload)
    # router 與 send_message 都不應被觸發
    mock_router.handle_message.assert_not_called()
    mock_ig.send_message.assert_not_called()


def test_poller_queue_boundaries():
    """驗證全量爬取工作隊列邊界防護：重複請求拒絕、不同對象進排程"""
    from app.commands.base import CommandResult
    mock_router = MagicMock()
    poller = BotPoller(router=mock_router)
    poller.allowed_main_pk = "22222"
    poller.bot_client = Client()
    mock_ig = MagicMock(spec=IGClient)
    poller.bot_ig = mock_ig

    # 模擬任務 A 正在執行中
    poller._current_task = {"target": "user_a", "max_amount": 1000, "thread_id": "t1"}

    # 1. 收到相同對象 user_a 的 track_full → 直接拒絕並提示進度
    mock_router.handle_message_structured.return_value = CommandResult(
        success=True, message="", action_type="TRACK_FULL_REQUEST",
        data={"target": "user_a", "max_amount": 1000}
    )
    poller._process_message("t1", "22222", "item_1", "track_full user_a")
    mock_ig.send_message.assert_called()
    args, _ = mock_ig.send_message.call_args
    assert "已有相同任務進行中" in args[1]

    # 2. 收到不同對象 user_b 的 track_full → 排入隊列
    mock_router.handle_message_structured.return_value = CommandResult(
        success=True, message="", action_type="TRACK_FULL_REQUEST",
        data={"target": "user_b", "max_amount": 1000}
    )
    poller._process_message("t1", "22222", "item_2", "track_full user_b")
    assert "user_b" in poller._get_queued_targets()
    args, _ = mock_ig.send_message.call_args
    assert "已將 user_b 加入排程" in args[1]

    # 3. 再次收到 user_b → 提示已在排程中
    poller._process_message("t1", "22222", "item_3", "track_full user_b")
    args, _ = mock_ig.send_message.call_args
    assert "已在排程名單中" in args[1]


def test_poller_sync_contact_messages(monkeypatch):
    """驗證 BotPoller._sync_contact_messages 以 amount=0 呼叫 adapter 並寫入訊息至資料庫。"""
    from unittest.mock import patch
    from app.sources.base import NormalizedMessage

    poller = BotPoller(router=MagicMock())
    poller.main_ig = MagicMock()

    mock_msgs = [
        NormalizedMessage(
            source_type="instagram",
            external_id="ext_1",
            sender="them",
            content="最新私訊內容",
            sent_at="2026-09-19T00:00:00Z"
        )
    ]

    mock_adapter = MagicMock()
    mock_adapter.fetch_messages.return_value = mock_msgs

    with patch("app.sources.SourceAdapterFactory.create", return_value=mock_adapter) as mock_factory, \
         patch("app.storage.db.get_or_create_contact", return_value=42) as mock_get_contact, \
         patch("app.storage.db.get_latest_item_ids", return_value={"ext_known"}) as mock_get_ids, \
         patch("app.storage.db.save_messages", return_value=1) as mock_save:

        inserted = poller._sync_contact_messages("target_u")

        assert inserted == 1
        mock_factory.assert_called_once_with("instagram", ig_client=poller.main_ig)
        mock_adapter.fetch_messages.assert_called_once_with(target="target_u", amount=0, stop_item_ids={"ext_known"})
        mock_get_contact.assert_called_once_with(ig_account_id="target_u", display_name="target_u")
        mock_save.assert_called_once_with(
            contact_id=42,
            messages=[{
                "ig_item_id": "ext_1",
                "sender": "them",
                "content": "最新私訊內容",
                "sent_at": "2026-09-19T00:00:00Z"
            }]
        )

