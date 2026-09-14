import time
import pytest
from unittest.mock import patch, MagicMock
from app.rate_limit import ig_retry, gemini_retry, wait_with_log, _is_gemini_retryable_error
from instagrapi.exceptions import ClientThrottledError, PleaseWaitFewMinutes
from google.genai.errors import ClientError, ServerError


# ─── IG retry ────────────────────────────────────────────────────────────────

def test_ig_retry_succeeds_immediately():
    """第一次呼叫就成功時不等待。"""
    calls = []

    @ig_retry(max_retries=1)
    def ok_fn():
        calls.append(1)
        return "ok"

    result = ok_fn()
    assert result == "ok"
    assert len(calls) == 1


def test_ig_retry_retries_on_throttle(monkeypatch):
    """觸發 ClientThrottledError 後等待並重試一次成功。"""
    calls = []

    # 不實際等待 30 分鐘
    monkeypatch.setattr("app.rate_limit.LONG_WAIT_SECONDS", 0)
    monkeypatch.setattr("app.rate_limit.wait_with_log", lambda s, reason="": None)

    @ig_retry(max_retries=1)
    def flaky_fn():
        calls.append(1)
        if len(calls) == 1:
            raise ClientThrottledError()
        return "retried"

    result = flaky_fn()
    assert result == "retried"
    assert len(calls) == 2


def test_ig_retry_raises_after_max_retries(monkeypatch):
    """超過 max_retries 仍失敗時應拋出例外。"""
    monkeypatch.setattr("app.rate_limit.wait_with_log", lambda s, reason="": None)

    @ig_retry(max_retries=1)
    def always_fail():
        raise PleaseWaitFewMinutes()

    with pytest.raises(PleaseWaitFewMinutes):
        always_fail()


# ─── Gemini retry ─────────────────────────────────────────────────────────────

def test_gemini_retry_succeeds_immediately():
    @gemini_retry(max_short_retries=3, base_delay=0)
    def ok_fn():
        return "ok"

    assert ok_fn() == "ok"


def test_gemini_retry_short_backoff_then_success(monkeypatch):
    """前兩次 429，第三次成功。"""
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []

    @gemini_retry(max_short_retries=3, base_delay=0)
    def flaky_fn():
        calls.append(1)
        if len(calls) < 3:
            raise ClientError(429, {})
        return "done"

    result = flaky_fn()
    assert result == "done"
    assert len(calls) == 3


def test_gemini_retry_raises_after_short_retries(monkeypatch):
    """短退避次數耗盡後直接拋出，不長等待，讓外層切換下一個模型。"""
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []

    @gemini_retry(max_short_retries=2, base_delay=0)
    def always_fail():
        calls.append(1)
        raise ClientError(429, {})

    with pytest.raises(ClientError):
        always_fail()
    assert len(calls) == 2


def test_gemini_retry_non_quota_error_raises_immediately(monkeypatch):
    """非 429 錯誤不應重試，直接拋出。"""
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []

    @gemini_retry(max_short_retries=3, base_delay=0)
    def broken_fn():
        calls.append(1)
        raise ValueError("不相關的錯誤")

    with pytest.raises(ValueError):
        broken_fn()
    assert len(calls) == 1


# ─── is_gemini_retryable_error ────────────────────────────────────────────────

def test_is_gemini_retryable_error_detects_429_and_503():
    assert _is_gemini_retryable_error(ClientError(429, {})) is True
    assert _is_gemini_retryable_error(ServerError(503, {})) is True


def test_is_gemini_retryable_error_ignores_client_errors():
    assert _is_gemini_retryable_error(ClientError(400, {})) is False
    assert _is_gemini_retryable_error(ClientError(404, {})) is False
    assert _is_gemini_retryable_error(ValueError("nope")) is False


def test_calculate_human_delay_high_variance():
    import statistics
    from app.rate_limit import calculate_human_delay

    samples = [calculate_human_delay(min_delay=3.5, max_delay=14.0, pause_chance=0.2, pause_min=20.0, pause_max=40.0) for _ in range(100)]
    stdev = statistics.stdev(samples)
    # 驗證標準差顯著大於舊版的 1~2 秒區間
    assert stdev > 3.0
    # 驗證樣本中有包含微停頓（大於 18 秒）
    assert any(s >= 18.0 for s in samples)
