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
