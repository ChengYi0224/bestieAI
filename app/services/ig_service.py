"""
ig_service.py — 向後相容轉接層。實際實作已遷移至 app.clients.instagram.IGClient。
"""
from app.clients.instagram import IGClient

__all__ = ["IGClient"]
