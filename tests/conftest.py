import pytest
from app.core.config import settings


def pytest_addoption(parser):
    """新增命令列 Option -E / --external 用於執行外部真實 API 測試。"""
    parser.addoption(
        "-E",
        "--external",
        action="store_true",
        default=False,
        help="執行真實外部 API 測試（Gemini / Instagram），需於環境變數配置金鑰或帳密",
    )


def pytest_collection_modifyitems(config, items):
    """未指定 -E / --external 時，自動 Skip 帶有 external marker 的測試。"""
    if not config.getoption("--external"):
        skip_external = pytest.mark.skip(reason="需指定 -E 或 --external 才會執行真實外部 API 測試")
        for item in items:
            if "external" in item.keywords:
                item.add_marker(skip_external)


@pytest.fixture(autouse=True)
def zero_gemini_pacing(monkeypatch):
    '''測試全域自動歸零 pacing 延遲，避免批次處理時無謂等待 4.5 秒。'''
    monkeypatch.setattr(settings, 'GEMINI_PACING_DELAY', 0.0)


@pytest.fixture(autouse=True)
def default_tenant(request, monkeypatch):
    """
    多數既有測試是單一使用者情境：未指定 user_id 時以擁有者 (user 1) 身分執行。
    驗證多租戶 / 未綁定行為的測試請加上 @pytest.mark.no_default_tenant 並明確傳入 user_id。
    """
    if request.node.get_closest_marker("no_default_tenant"):
        return

    from app.bot.router import CommandRouter
    from app.commands.bus import CommandBus

    orig_structured = CommandRouter.handle_message_structured
    orig_parse = CommandRouter.parse_text_to_command
    orig_dispatch = CommandBus.dispatch

    def structured(self, raw_text, sender_pk=None, user_id=None):
        return orig_structured(self, raw_text, sender_pk=sender_pk, user_id=1 if user_id is None else user_id)

    def parse(self, raw_text, user_id=None):
        return orig_parse(self, raw_text, user_id=1 if user_id is None else user_id)

    def dispatch(self, command):
        if command.requires_user and command.user_id is None:
            command.user_id = 1
        return orig_dispatch(self, command)

    monkeypatch.setattr(CommandRouter, "handle_message_structured", structured)
    monkeypatch.setattr(CommandRouter, "parse_text_to_command", parse)
    monkeypatch.setattr(CommandBus, "dispatch", dispatch)
