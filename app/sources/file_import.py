"""
file_import.py — 本地檔案聊天紀錄匯入適配器（FileImportAdapter）。

PIPELINE (L2):
  FileImportAdapter.fetch_messages(target=file_path, amount)
       │
       ▼
  判斷副檔名 / 指定格式
       ├─ .json ──► _parse_json()
       ├─ .csv  ──► _parse_csv()
       └─ .txt  ──► _parse_line_txt()
       │
       ▼ [解析中介訊息字典]
  逐筆轉換為 NormalizedMessage:
       ├─ external_id   ← 自定義 ID 或行號
       ├─ sender        ← 'me' if sender == self_id else 'them'
       ├─ content       ← clean_text(content)
       ├─ sent_at       ← ISO 8601 時間字串
       ├─ source_type   ← 'file_import'
       └─ extras        ← {'file_path': ..., 'row': ...}
       │
       ▼
  [NormalizedMessage 清單]
"""
import csv
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.sources.base import BaseSourceAdapter, NormalizedMessage

logger = logging.getLogger("bestieAI.sources.file_import")


class FileImportAdapter(BaseSourceAdapter):
    """本地檔案（JSON, CSV, LINE 匯出 TXT）資料來源適配器。"""

    source_type: str = "file_import"

    def __init__(self, self_id: str = "me", format: str = "auto"):
        self.self_id = self_id
        self.format = format

    def get_self_id(self) -> str:
        return self.self_id

    def fetch_messages(
        self,
        target: str,
        amount: int = 0,
        progress_callback: Optional[Any] = None,
    ) -> List[NormalizedMessage]:
        path = Path(target)
        if not path.exists():
            raise FileNotFoundError(f"找不到匯入檔案：{target}")

        fmt = self.format.lower()
        if fmt == "auto":
            ext = path.suffix.lower()
            if ext == ".json":
                fmt = "json"
            elif ext == ".csv":
                fmt = "csv"
            else:
                fmt = "line_txt"

        if fmt == "json":
            messages = self._parse_json(path)
        elif fmt == "csv":
            messages = self._parse_csv(path)
        else:
            messages = self._parse_line_txt(path)

        if amount > 0:
            messages = messages[:amount]

        return messages

    def _parse_json(self, path: Path) -> List[NormalizedMessage]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_msgs = data.get("messages", []) if isinstance(data, dict) else data
        file_self_id = data.get("self_id", self.self_id) if isinstance(data, dict) else self.self_id

        result: List[NormalizedMessage] = []
        for idx, item in enumerate(raw_msgs):
            msg_id = str(item.get("id") or item.get("external_id") or f"json_{idx+1}")
            sender_raw = str(item.get("sender") or item.get("sender_name") or "")
            sender = "me" if sender_raw in (file_self_id, "me") else "them"
            content = str(item.get("content") or item.get("text") or "[圖片/貼圖/非文字訊息]").strip()

            sent_at = item.get("sent_at")
            if not sent_at and "timestamp_ms" in item:
                sent_at = datetime.fromtimestamp(item["timestamp_ms"] / 1000.0, tz=timezone.utc).isoformat()
            elif not sent_at:
                sent_at = datetime.now(timezone.utc).isoformat()

            result.append(NormalizedMessage(
                external_id=msg_id,
                sender=sender,
                content=content or "[圖片/貼圖/非文字訊息]",
                sent_at=sent_at,
                source_type=self.source_type,
                raw_media_type=item.get("raw_media_type", "text"),
                extras={"file_path": str(path), "row": idx + 1},
            ))
        return result

    def _parse_csv(self, path: Path) -> List[NormalizedMessage]:
        result: List[NormalizedMessage] = []
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                msg_id = str(row.get("id") or row.get("external_id") or f"csv_{idx+1}")
                sender_raw = str(row.get("sender") or row.get("sender_name") or "")
                sender = "me" if sender_raw in (self.self_id, "me") else "them"
                content = str(row.get("content") or row.get("text") or "[圖片/貼圖/非文字訊息]").strip()
                sent_at = str(row.get("sent_at") or row.get("timestamp") or datetime.now(timezone.utc).isoformat())

                result.append(NormalizedMessage(
                    external_id=msg_id,
                    sender=sender,
                    content=content or "[圖片/貼圖/非文字訊息]",
                    sent_at=sent_at,
                    source_type=self.source_type,
                    raw_media_type=row.get("raw_media_type", "text"),
                    extras={"file_path": str(path), "row": idx + 1},
                ))
        return result

    def _parse_line_txt(self, path: Path) -> List[NormalizedMessage]:
        result: List[NormalizedMessage] = []
        current_date_str = None

        date_header_re = re.compile(r"^(\d{4}[/\.-]\d{1,2}[/\.-]\d{1,2})")
        msg_line_re = re.compile(r"^(\d{1,2}:\d{2})\s+([^\s]+)\s+(.+)$")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue

                date_m = date_header_re.match(line)
                if date_m and ("星期" in line or len(line) <= 15):
                    raw_d = date_m.group(1).replace("/", "-").replace(".", "-")
                    parts = raw_d.split("-")
                    current_date_str = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                    continue

                msg_m = msg_line_re.match(line)
                if msg_m:
                    time_str, sender_raw, content = msg_m.group(1), msg_m.group(2), msg_m.group(3)
                    sender = "me" if sender_raw in (self.self_id, "me") else "them"
                    d_prefix = current_date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    sent_at = f"{d_prefix}T{time_str}:00"

                    result.append(NormalizedMessage(
                        external_id=f"line_txt_{idx+1}",
                        sender=sender,
                        content=content.strip() or "[圖片/貼圖/非文字訊息]",
                        sent_at=sent_at,
                        source_type=self.source_type,
                        raw_media_type="text",
                        extras={"file_path": str(path), "row": idx + 1, "original_sender": sender_raw},
                    ))
        return result


# 自我註冊至 SourceAdapterFactory
from app.sources.factory import SourceAdapterFactory  # noqa: E402
SourceAdapterFactory.register("file_import", FileImportAdapter)
SourceAdapterFactory.register("file", FileImportAdapter)
SourceAdapterFactory.register("local", FileImportAdapter)
