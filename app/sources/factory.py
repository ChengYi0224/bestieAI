"""
factory.py — 資料來源適配器工廠（SourceAdapterFactory）。

PIPELINE (L2):
  SourceAdapterFactory.create(source_type, **kwargs)
       │
       ▼
  查表 _registry.get(source_type)
       │
       ├─ (未找到) ──► raise ValueError，列出所有已註冊 source_type
       │
       ▼ (找到 adapter_cls)
  adapter_cls(**kwargs) 實例化
       │
       ▼
  [BaseSourceAdapter 實例]

新增來源只需在該 Adapter 的模組底部呼叫：
  SourceAdapterFactory.register("source_type", AdapterClass)
  factory.py 本身不需要改動。
"""
import logging
from typing import Any, Dict, Type
from app.sources.base import BaseSourceAdapter

logger = logging.getLogger("bestieAI.sources.factory")


class SourceAdapterFactory:
    """來源適配器 Registry 工廠。"""

    _registry: Dict[str, Type[BaseSourceAdapter]] = {}

    @classmethod
    def register(cls, source_type: str, adapter_cls: Type[BaseSourceAdapter]) -> None:
        """註冊一個 Adapter 類別到指定的 source_type 代號。"""
        key = source_type.lower().strip()
        cls._registry[key] = adapter_cls
        logger.debug(f"已註冊 SourceAdapter: {key!r} → {adapter_cls.__name__}")

    @classmethod
    def create(cls, source_type: str, **kwargs: Any) -> BaseSourceAdapter:
        """依 source_type 建立對應 Adapter 實例。"""
        st = source_type.lower().strip()
        adapter_cls = cls._registry.get(st)
        if adapter_cls is None:
            registered = list(cls._registry.keys())
            raise ValueError(
                f"不支援的資料來源類別: {source_type!r}，"
                f"已註冊清單: {registered}"
            )
        return adapter_cls(**kwargs)

    @classmethod
    def registered_types(cls) -> list:
        """回傳所有已註冊的 source_type 清單。"""
        return list(cls._registry.keys())
