import logging

from app.utils.progress import notify_progress


def test_notify_progress_calls_callback():
    calls = []
    notify_progress(calls.append, "hello")
    assert calls == ["hello"]


def test_notify_progress_ignores_none():
    notify_progress(None, "x")


def test_notify_progress_swallows_but_logs(caplog):
    def boom(_):
        raise RuntimeError("ui down")

    with caplog.at_level(logging.WARNING, logger="bestieAI.progress"):
        notify_progress(boom, "x")
    assert any("ui down" in r.message for r in caplog.records)
