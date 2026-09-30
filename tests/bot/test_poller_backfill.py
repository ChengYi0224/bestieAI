from unittest.mock import MagicMock, patch

from app.bot.poller import BotPoller
from app.sources.base import NormalizedMessage


def _msg(i):
    return NormalizedMessage(source_type="instagram", external_id=f"e{i}", sender="them",
                             content=f"m{i}", sent_at="2026-09-19T00:00:00Z")


def _poller(user_id=1):
    poller = BotPoller(router=MagicMock())
    poller.ig_pool.prime(user_id, MagicMock())
    return poller


def test_sync_with_amount_backfills_older_history_in_background():
    """amount>0 且尚未接上既有紀錄時，前景回傳後由背景以 cursor 續抓，直到抓完。"""
    poller = _poller()
    svc = poller.sync_service
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
        svc._backfilling.add((a[0], a[1]))
        svc._backfill_worker(*a)  # 測試中同步執行背景流程

    svc._start_backfill = sync_start

    def fake_save(contact_id, messages):
        saved.extend(messages)
        return len(messages)

    with patch("app.sources.SourceAdapterFactory.create", return_value=adapter), \
         patch("app.storage.db.get_or_create_contact", return_value=7), \
         patch("app.storage.db.get_latest_item_ids", return_value={"old"}), \
         patch("app.storage.db.save_messages", side_effect=fake_save):
        assert poller._sync_contact_messages("u", amount=20, user_id=1) == 1

    assert started and started[0][:2] == (1, "u") and started[0][3:5] == ("T1", "c1")
    assert [r["ig_item_id"] for r in saved] == ["e1", "e2"]
    assert calls[0]["truncate"] is False and calls[0]["amount"] == 20
    assert calls[1]["start_cursor"] == "c1" and calls[1]["thread_id"] == "T1"
    assert not svc._backfilling


def test_sync_with_amount_skips_backfill_when_anchored():
    poller = _poller()
    adapter = MagicMock()
    adapter.fetch_messages.return_value = []
    adapter.last_cursor = "c1"
    adapter.last_thread_id = "T1"
    adapter.last_hit_anchor = True
    poller.sync_service._start_backfill = MagicMock()

    with patch("app.sources.SourceAdapterFactory.create", return_value=adapter), \
         patch("app.storage.db.get_or_create_contact", return_value=7), \
         patch("app.storage.db.get_latest_item_ids", return_value={"old"}), \
         patch("app.storage.db.save_messages", return_value=0):
        poller._sync_contact_messages("u", amount=20, user_id=1)

    poller.sync_service._start_backfill.assert_not_called()


def test_sync_returns_failed_marker_on_error():
    from app.commands.base import SYNC_FAILED
    poller = _poller()
    with patch("app.sources.SourceAdapterFactory.create", side_effect=RuntimeError("boom")), \
         patch("app.storage.db.get_or_create_contact", return_value=7), \
         patch("app.storage.db.get_latest_item_ids", return_value=set()):
        assert poller._sync_contact_messages("u", amount=10, user_id=1) == SYNC_FAILED


def test_sync_fails_cleanly_when_user_has_no_ig_session():
    """未綁定 IG 的使用者同步時回傳 SYNC_FAILED，而不是借用擁有者的連線。"""
    from app.commands.base import SYNC_FAILED
    from app.services.ig_pool import IGSessionUnavailable
    poller = BotPoller(router=MagicMock())
    poller.ig_pool.get = MagicMock(side_effect=IGSessionUnavailable("尚未綁定"))
    with patch("app.storage.db.get_or_create_contact", return_value=7), \
         patch("app.storage.db.get_latest_item_ids", return_value=set()):
        assert poller._sync_contact_messages("u", user_id=2) == SYNC_FAILED


def test_seen_message_ids_are_bounded_and_deduplicated():
    poller = _poller()
    poller.MAX_SEEN_MESSAGE_IDS = 3
    assert poller._mark_seen("a") is True
    assert poller._mark_seen("a") is False
    for i in "bcd":
        poller._mark_seen(i)
    assert len(poller.seen_message_ids) == 3
    assert "a" not in poller.seen_message_ids  # 最舊的被淘汰
