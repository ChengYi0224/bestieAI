"""
sources — 資料來源適配層（Source Adapter Layer）。

Import 順序：
  1. base（基底型別，無相依）
  2. factory（建立 _registry，無相依）
  3. Adapter 模組（觸發各自的 SourceAdapterFactory.register()）
"""
from app.sources.base import BaseSourceAdapter, NormalizedMessage
from app.sources.factory import SourceAdapterFactory
# 以下 import 會觸發各 Adapter 模組末尾的 register() 呼叫
from app.sources.instagram import InstagramAdapter
from app.sources.file_import import FileImportAdapter

__all__ = [
    "BaseSourceAdapter",
    "NormalizedMessage",
    "SourceAdapterFactory",
    "InstagramAdapter",
    "FileImportAdapter",
]
