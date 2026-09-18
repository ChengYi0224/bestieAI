"""
test_utils.py — app/utils 輔助模組單元測試。
"""
import sqlite3
from datetime import datetime, timezone
import pytest

from app.utils.time import parse_time_str, format_time, now_utc_iso
from app.utils.math import cosine_similarity, cosine_distance
from app.utils.text import clean_message_text, truncate_text, parse_bullet_list
from app.utils.db import row_to_dict, get_row_field


# ==================== Time Utils ====================

def test_parse_time_str_iso_and_z():
    dt_z = parse_time_str("2026-09-19T10:30:00Z")
    assert dt_z is not None
    assert dt_z.year == 2026
    assert dt_z.month == 9
    assert dt_z.day == 19
    assert dt_z.hour == 10
    assert dt_z.minute == 30

    dt_offset = parse_time_str("2026-09-19T18:30:00+08:00")
    assert dt_offset is not None
    assert dt_offset.hour == 18

    dt_date = parse_time_str("2026-09-19")
    assert dt_date is not None
    assert dt_date.day == 19

    assert parse_time_str(None) is None
    assert parse_time_str("") is None
    assert parse_time_str("invalid-time-format") is None


def test_format_time():
    dt = datetime(2026, 9, 19, 14, 5, 0)
    assert format_time(dt) == "2026-09-19 14:05:00"
    assert format_time(dt, fmt="%Y/%m/%d") == "2026/09/19"
    assert format_time(None) == ""


def test_now_utc_iso():
    iso_str = now_utc_iso()
    assert isinstance(iso_str, str)
    parsed = datetime.fromisoformat(iso_str)
    assert parsed.tzinfo is not None


# ==================== Math Utils ====================

def test_cosine_similarity_and_distance():
    vec_a = [1.0, 0.0]
    vec_b = [1.0, 0.0]
    assert pytest.approx(cosine_similarity(vec_a, vec_b)) == 1.0
    assert pytest.approx(cosine_distance(vec_a, vec_b)) == 0.0

    vec_c = [0.0, 1.0]
    assert pytest.approx(cosine_similarity(vec_a, vec_c)) == 0.0
    assert pytest.approx(cosine_distance(vec_a, vec_c)) == 1.0

    vec_d = [-1.0, 0.0]
    assert pytest.approx(cosine_similarity(vec_a, vec_d)) == -1.0
    assert pytest.approx(cosine_distance(vec_a, vec_d)) == 2.0

    # 零向量與邊界條件
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], []) == 0.0


# ==================== Text Utils ====================

def test_clean_message_text():
    assert clean_message_text("  哈囉你好  ") == "哈囉你好"
    assert clean_message_text(None) == "[非文字訊息]"
    assert clean_message_text("   ") == "[非文字訊息]"
    assert clean_message_text("", default="[無文字]") == "[無文字]"


def test_truncate_text():
    assert truncate_text("短文字", max_length=10) == "短文字"
    assert truncate_text("這是一段非常長的測試訊息用來驗證截斷功能", max_length=5) == "這是一段非..."
    assert truncate_text("", max_length=5) == ""


def test_parse_bullet_list():
    raw = """
    - 第一條事項
    * 第二條重點
    • 第三條備註
    - 無
    """
    items = parse_bullet_list(raw)
    assert items == ["第一條事項", "第二條重點", "第三條備註"]

    assert parse_bullet_list("無") == []
    assert parse_bullet_list("無新增事實") == []
    assert parse_bullet_list("") == []
    assert parse_bullet_list(None) == []


# ==================== DB Utils ====================

def test_row_to_dict_and_get_field():
    # 測試 dict
    d = {"name": "alice", "age": 25}
    assert row_to_dict(d) == d
    assert get_row_field(d, "name") == "alice"
    assert get_row_field(d, "gender", default="unknown") == "unknown"

    # 測試 sqlite3.Row
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE test (id INTEGER, val TEXT)")
    cursor.execute("INSERT INTO test VALUES (1, 'hello')")
    cursor.execute("SELECT * FROM test WHERE id = 1")
    row = cursor.fetchone()

    converted = row_to_dict(row)
    assert converted == {"id": 1, "val": "hello"}
    assert get_row_field(row, "val") == "hello"
    assert get_row_field(row, "not_exist", default="fallback") == "fallback"

    # 測試 None
    assert row_to_dict(None) == {}
    assert get_row_field(None, "any", default=42) == 42
