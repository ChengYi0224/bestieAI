from unittest.mock import MagicMock, patch

from app.bot.poller import BotPoller
from app.sources.base import NormalizedMessage


def _msg(i):
    return NormalizedMessage(source_type="instagram", external_id=f"e{i}", sender="them",
                             content=f"m{i}", sent_at="2026-09-19T00:00:00Z")


def _poller():
    poller = BotPoller(router=MagicMock())
    poller.main_ig = MagicMock()
    return poller


def test_sync_with_amount_backfills_older_history_in_background():
    """amount>0 且尚未接上既有紀錄時，前景回傳後由背景以 cursor 續抓，直到抓完。"""
    poller = _poller()
    adapter = MagicMock()
    adapter.last_thread_id = "T1"
    adapter.last_hit_anchor = False
    calls = []

    def fake_fetch(**kw):
        calls.append(kw)
        if "start_cursor" not in kw:
            adapter.last_cursor = "c1"
            return [_msg(1)]
        adapter.last_cursor = None  # 背景第一輪即抓完
        return [_msg(2)]

    adapter.fetch_messages.side_effect = fake_fetch
    saved = []
    started = []

    def sync_start(*a, **k):
        started.append(a)
        poller._backfilling.add(a[0])
        poller._backfill_worker(*a)  # 測試中同步執行背景流程

    poller._start_backfill = sync_start

    def fake_save(contact_id, messages):
        saved.extend(messages)
        return len(messages)

    with patch("app.sources.SourceAdapterFactory.create", return_value=adapter), \
         patch("app.storage.db.get_or_create_contact", return_value=7), \
         patch("app.storage.db.get_latest_item_ids", return_value={"old"}), \
         patch("app.storage.db.save_messages", side_effect=fake_save):
        assert poller._sync_contact_messages("u", amount=20) == 1

    assert started and started[0][2:4] == ("T1", "c1")
    assert [r["ig_item_id"] for r in saved] == ["e1", "e2"]
    assert calls[0]["truncate"] is False and calls[0]["amount"] == 20
    assert calls[1]["start_cursor"] == "c1" and calls[1]["thread_id"] == "T1"
    assert not poller._backfilling


def test_sync_with_amount_skips_backfill_when_anchored():
    poller = _poller()
    adapter = MagicMock()
    adapter.fetch_messages.return_value = []
    adapter.last_cursor = "c1"
    adapter.last_thread_id = "T1"
    adapter.last_hit_anchor = True
    poller._start_backfill = MagicMock()

    with patch("app.sources.SourceAdapterFactory.create", return_value=adapter), \
         patch("app.storage.db.get_or_create_contact", return_value=7), \
         patch("app.storage.db.get_latest_item_ids", return_value={"old"}), \
         patch("app.storage.db.save_messages", return_value=0):
        poller._sync_contact_messages("u", amount=20)

    poller._start_backfill.assert_not_called()


def test_sync_returns_failed_marker_on_error():
    from app.commands.base import SYNC_FAILED
    poller = _poller()
    with patch("app.sources.SourceAdapterFactory.create", side_effect=RuntimeError("boom")), \
         patch("app.storage.db.get_or_create_contact", return_value=7), \
         patch("app.storage.db.get_latest_item_ids", return_value=set()):
        assert poller._sync_contact_messages("u", amount=10) == SYNC_FAILED


def test_seen_message_ids_are_bounded_and_deduplicated():
    poller = _poller()
    poller.MAX_SEEN_MESSAGE_IDS = 3
    assert poller._mark_seen("a") is True
    assert poller._mark_seen("a") is False
    for i in "bcd":
        poller._mark_seen(i)
    assert len(poller.seen_message_ids) == 3
    assert "a" not in poller.seen_message_ids  # 最舊的被淘汰


def test_get_main_ig_logs_in_once():
    poller = BotPoller(router=MagicMock())
    poller.session_manager = MagicMock()
    with patch("app.bot.poller.IGClient") as ig_cls:
        first = poller._get_main_ig()
        second = poller._get_main_ig()
    assert first is second
    poller.session_manager.login.assert_called_once_with("main")
    ig_cls.assert_called_once()
