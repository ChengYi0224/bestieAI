import logging

import pytest

from app.core.config import INSECURE_DEFAULT_API_SECRET, Settings

STRONG = "x" * 48


def _make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_llm_log_defaults_follow_env():
    assert _make(APP_ENV="dev").ENABLE_LLM_LOG is True
    assert _make(APP_ENV="prod").ENABLE_LLM_LOG is False
    # 明確設定時尊重設定值
    assert _make(APP_ENV="prod", ENABLE_LLM_LOG=True).ENABLE_LLM_LOG is True


def test_prod_rejects_default_api_secret():
    s = _make(APP_ENV="prod", GOOGLE_CLIENT_ID_WEB="cid")
    assert s.API_SECRET == INSECURE_DEFAULT_API_SECRET
    with pytest.raises(RuntimeError, match="API_SECRET"):
        s.validate_security()


def test_prod_rejects_short_secret_and_missing_google_client():
    with pytest.raises(RuntimeError, match="長度不足"):
        _make(APP_ENV="prod", API_SECRET="short", GOOGLE_CLIENT_ID_WEB="cid").validate_security()
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        _make(APP_ENV="prod", API_SECRET=STRONG).validate_security()


def test_prod_rejects_admin_password_reuse():
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        _make(APP_ENV="prod", API_SECRET=STRONG, GOOGLE_CLIENT_ID_WEB="cid", ADMIN_PASSWORD=STRONG).validate_security()


def test_prod_with_safe_config_passes():
    _make(APP_ENV="prod", API_SECRET=STRONG, GOOGLE_CLIENT_ID_WEB="cid", ADMIN_PASSWORD="another-long-password").validate_security()


def test_dev_only_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="bestieAI.config"):
        _make(APP_ENV="dev").validate_security()
    assert any("API_SECRET" in r.message for r in caplog.records)
