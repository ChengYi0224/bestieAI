import pytest
from app.core.config import settings

@pytest.fixture(autouse=True)
def zero_gemini_pacing(monkeypatch):
    '''測試全域自動歸零 pacing 延遲，避免批次處理時無謂等待 4.5 秒。'''
    monkeypatch.setattr(settings, 'GEMINI_PACING_DELAY', 0.0)
