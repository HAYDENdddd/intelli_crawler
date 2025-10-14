"""File based exporter supporting JSON/CSV/TXT."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import BaseExporter


class FileExporter(BaseExporter):
    """Write records to local files in multiple formats."""

    def __init__(self, output_dir: Path, source_name: str, fmt: str, run_tag: str | None = None) -> None:
        self.output_dir = output_dir
        self.source_name = source_name
        self.format = fmt
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_tag = run_tag or datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^0-9A-Za-z_-]+", "_", source_name.strip()) or "source"
        filename = f"{slug}-{self.run_tag}.{self._extension}"
        self.path = self.output_dir / filename
        self._file = self.path.open("a", encoding="utf-8", newline="")
        self._csv_writer: Optional[csv.DictWriter] = None
        self._counter = 0

    @property
    def _extension(self) -> str:
        if self.format == "json":
            return "jsonl"
        if self.format == "csv":
            return "csv"
        return "txt"

    def export(self, record: dict) -> None:
        if self.format == "json":
            json.dump(record, self._file, ensure_ascii=False)
            self._file.write("\n")
        elif self.format == "csv":
            if not self._csv_writer:
                fieldnames = sorted(record.keys())
                self._csv_writer = csv.DictWriter(self._file, fieldnames=fieldnames)
                self._csv_writer.writeheader()
            self._csv_writer.writerow(record)
        else:  # txt
            self._counter += 1
            formatted = self._format_txt(record, index=self._counter)
            self._file.write(formatted)
            if not formatted.endswith("\n"):
                self._file.write("\n")

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def _format_txt(self, record: dict, index: int) -> str:
        title = str(record.get("title") or record.get("headline") or "(未提供标题)")
        source = record.get("source_name") or ""
        header = f"{index}. {title}" + (f"｜{source}" if source else "")

        published = record.get("published_at") or record.get("time") or record.get("timestamp")
        fetched = record.get("fetched_at")
        meta_lines = []
        if published:
            meta_lines.append(f"发布时间：{published}")
        if fetched:
            meta_lines.append(f"抓取时间：{fetched}")

        summary = record.get("summary") or record.get("content") or ""
        if isinstance(summary, str):
            summary_text = summary.strip()
        else:
            summary_text = ""

        url = record.get("original_url") or record.get("source_url") or record.get("url")

        lines = [header]
        if meta_lines:
            lines.extend(meta_lines)
        if summary_text:
            lines.append(summary_text)
        if url:
            lines.append(f"链接：{url}")

        # Separate records with a blank line
        return "\n".join(lines).strip() + "\n\n"


__all__ = ["FileExporter"]
