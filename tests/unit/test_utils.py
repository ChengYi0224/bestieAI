"""
test_utils.py — app/utils 輔助模組單元測試。
"""
import sqlite3
from datetime import datetime, timezone
import pytest

from app.utils.time import parse_time_str, format_time, now_utc_iso
from app.utils.math import cosine_similarity, cosine_distance
from app.utils.text import (
    clean_message_text,
    truncate_text,
    strip_bullet_prefix,
    parse_bullet_list,
    normalize_to_bullet_lines,
    extract_tagged_blocks,
    parse_cluster_results,
    extract_leading_date,
    parse_line_chat_date_header,
    parse_line_chat_message,
    extract_date_and_time,
    format_chat_messages,
)
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


def test_strip_bullet_prefix():
    assert strip_bullet_prefix("- 項目A") == "項目A"
    assert strip_bullet_prefix("* 項目B") == "項目B"
    assert strip_bullet_prefix("• 項目C") == "項目C"
    assert strip_bullet_prefix("1. 項目D") == "項目D"
    assert strip_bullet_prefix("02. 項目E") == "項目E"
    assert strip_bullet_prefix("3) 項目F") == "項目F"
    assert strip_bullet_prefix("純文字內容") == "純文字內容"


def test_parse_bullet_list():
    raw = """
    - 第一條事項
    * 第二條重點
    • 第三條備註
    1. 第四條編號
    02. 第五條編號
    - 無
    """
    items = parse_bullet_list(raw)
    assert items == ["第一條事項", "第二條重點", "第三條備註", "第四條編號", "第五條編號"]

    assert parse_bullet_list("無") == []
    assert parse_bullet_list("無新增事實") == []
    assert parse_bullet_list("無重要事件") == []
    assert parse_bullet_list("") == []
    assert parse_bullet_list(None) == []


def test_normalize_to_bullet_lines():
    raw = """
    1. 喜歡吃辣
    2. 養了一隻貓叫米米
    無新增事實
    """
    normalized = normalize_to_bullet_lines(raw)
    assert normalized == "- 喜歡吃辣\n- 養了一隻貓叫米米"

    assert normalize_to_bullet_lines("無") == ""
    assert normalize_to_bullet_lines("") == ""


def test_extract_tagged_blocks_and_cluster_results():
    payload = """
    <cluster_result id="group_1">
    - 2026-09-19 討論專案架構
    - 2026-09-19 確認交付時程
    </cluster_result>

    <cluster_result id="group_2">
    1. 2026-09-20 購買食材
    </cluster_result>
    """
    blocks = extract_tagged_blocks(payload, "cluster_result")
    assert len(blocks) == 2
    assert blocks[0][0] == "group_1"

    results = parse_cluster_results(payload)
    assert "group_1" in results
    assert len(results["group_1"]) == 2
    assert results["group_1"][0] == "2026-09-19 討論專案架構"
    assert results["group_2"] == ["2026-09-20 購買食材"]

    assert parse_cluster_results("") == {}


def test_extract_leading_date():
    assert extract_leading_date("[2026-09-19 14:00] 對話內容") == "2026-09-19"
    assert extract_leading_date("[2026/9/5] 訊息") == "2026-09-05"
    assert extract_leading_date("2026.03.01 標題") == "2026-03-01"
    assert extract_leading_date("沒有日期的文字") is None
    assert extract_leading_date("") is None


def test_parse_line_chat_helpers():
    # 測試日期標頭行
    assert parse_line_chat_date_header("2026/09/19 星期六") == "2026-09-19"
    assert parse_line_chat_date_header("2026-9-5 週一") == "2026-09-05"
    assert parse_line_chat_date_header("2026.01.02") == "2026-01-02"
    assert parse_line_chat_date_header("今天吃飽沒？") is None

    # 測試訊息行
    msg = parse_line_chat_message("14:30 小美 週末要不要去露營？")
    assert msg is not None
    time_str, sender, content = msg
    assert time_str == "14:30"
    assert sender == "小美"
    assert content == "週末要不要去露營？"

    assert parse_line_chat_message("這不是訊息格式") is None


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


# ==================== Chat Message Formatting Utils ====================

def test_extract_date_and_time():
    # ISO 帶 T 與時間
    d, t = extract_date_and_time("2026-09-19T10:15:30")
    assert d == "2026-09-19"
    assert t == "10:15:30"

    # 空格分隔
    d, t = extract_date_and_time("2026-09-19 14:20:00")
    assert d == "2026-09-19"
    assert t == "14:20:00"

    # 純日期無時間
    d, t = extract_date_and_time("2026-09-19")
    assert d == "2026-09-19"
    assert t is None

    # datetime 物件
    dt = datetime(2026, 9, 19, 8, 30, 0)
    d, t = extract_date_and_time(dt)
    assert d == "2026-09-19"
    assert t == "08:30:00"

    # 空值與無效格式
    assert extract_date_and_time(None) == (None, None)
    assert extract_date_and_time("") == (None, None)


def test_format_chat_messages_grouping_and_sections():
    messages = [
        {"sender": "them", "content": "哈囉！", "sent_at": "2026-09-18T22:30:00"},
        {"sender": "me", "content": "晚安", "sent_at": "2026-09-18T22:31:00"},
        {"sender": "them", "content": "早安呀！", "sent_at": "2026-09-19T09:00:00"},
        {"sender": "me", "content": "今天天氣真好", "sent_at": "2026-09-19T09:01:00"},
    ]

    formatted = format_chat_messages(messages, other_label="小美")
    expected = (
        "--- 2026-09-18 ---\n"
        "[22:30:00] 小美: 哈囉！\n"
        "[22:31:00] 我: 晚安\n\n"
        "--- 2026-09-19 ---\n"
        "[09:00:00] 小美: 早安呀！\n"
        "[09:01:00] 我: 今天天氣真好"
    )
    assert formatted == expected


def test_format_chat_messages_empty_and_no_time():
    assert format_chat_messages([]) == ""

    # 無時間或日期格式
    messages = [
        {"sender": "me", "content": "無時間訊息", "sent_at": None},
        {"sender": "them", "content": "收到", "sent_at": ""},
    ]
    formatted = format_chat_messages(messages, other_label="對方")
    assert formatted == "我: 無時間訊息\n對方: 收到"
