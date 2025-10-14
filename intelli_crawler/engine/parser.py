"""DOM and JSON parsing helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin

from html import unescape

from selectolax.parser import HTMLParser

from ..config import SourceConfig


@dataclass
class ParsedRecord:
    """Structured representation of parsed content."""

    url: str
    data: dict[str, Any]


class Parser:
    """Parse listing and detail responses according to source templates."""

    def parse_entries(self, source: SourceConfig, html: str, base_url: str) -> list[str]:
        parser = HTMLParser(html)
        entries: list[str] = []
        seen: set[str] = set()
        for node in parser.css(source.entry_pattern):
            href = node.attributes.get("href")
            if not href:
                continue
            href = href.strip()
            if not href or href.startswith(("javascript:", "#")):
                continue
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                entries.append(full_url)
        return entries

    def parse_detail(self, source: SourceConfig, html: str, url: str) -> ParsedRecord:
        """
        解析详情页内容，支持多选择器回退机制
        
        Args:
            source: 信息源配置
            html: HTML内容
            url: 页面URL
            
        Returns:
            ParsedRecord: 解析后的记录
        """
        data: dict[str, Any] = {
            "url": url,
            "source_name": source.source_name,
            "site_type": source.site_type.value,
        }
        if source.detail_pattern:
            parser = HTMLParser(html)
            for field, selector_config in source.detail_pattern.items():
                # 支持单选择器或多选择器列表
                selectors = selector_config if isinstance(selector_config, list) else [selector_config]
                
                field_value = None
                for selector in selectors:
                    css_selector, mode = self._split_selector(selector)
                    if not css_selector:
                        continue
                    
                    node = parser.css_first(css_selector)
                    if node:
                        if mode == "html":
                            field_value = node.html
                        elif mode.startswith("attr:"):
                            attr = mode.split(":", 1)[1]
                            field_value = node.attributes.get(attr)
                        else:
                            field_value = node.text(separator=" ", strip=True)
                        
                        # 如果获取到有效内容，跳出回退循环
                        if field_value and field_value.strip():
                            break
                
                # 如果所有选择器都没有获取到内容，尝试从meta标签获取
                if not field_value or not field_value.strip():
                    if field == "title":
                        # 尝试从meta标签获取标题
                        meta_selectors = [
                            'meta[property="og:title"]',
                            'meta[name="title"]', 
                            'title'
                        ]
                        for meta_selector in meta_selectors:
                            node = parser.css_first(meta_selector)
                            if node:
                                if meta_selector == 'title':
                                    field_value = node.text(separator=" ", strip=True)
                                else:
                                    field_value = node.attributes.get("content")
                                if field_value and field_value.strip():
                                    break
                    elif field == "content":
                        # 尝试从meta描述获取内容
                        meta_selectors = [
                            'meta[property="og:description"]',
                            'meta[name="description"]'
                        ]
                        for meta_selector in meta_selectors:
                            node = parser.css_first(meta_selector)
                            if node:
                                field_value = node.attributes.get("content")
                                if field_value and field_value.strip():
                                    break
                
                data[field] = field_value if field_value and field_value.strip() else None
                
        if "raw_html" not in data:
            data["raw_html"] = html
        return ParsedRecord(url=url, data=data)

    def parse_json(self, payload: str) -> Any:
        return json.loads(payload)

    def filter_by_keywords(self, record: ParsedRecord, keywords: Iterable[str]) -> bool:
        if not keywords:
            return True
        haystack = " ".join(str(value) for value in record.data.values() if value)
        return any(keyword.lower() in haystack.lower() for keyword in keywords)

    @staticmethod
    def _split_selector(selector: str) -> tuple[str, str]:
        if "::" in selector:
            css, mode = selector.split("::", 1)
            return css.strip(), mode.strip().lower()
        return selector.strip(), "text"

    def extract_foresight_records(self, html: str, base_url: str) -> dict[str, dict[str, Any]]:
        parser = HTMLParser(html)
        records: dict[str, dict[str, Any]] = {}
        wrappers = parser.css("div.el-timeline-item__wrapper")
        if not wrappers:
            wrappers = parser.css("div.list_body")
        for item in wrappers:
            title_node = item.css_first("a.news_body_title")
            content_node = item.css_first("div.news_body_content span")
            time_node = item.css_first("div.el-timeline-item__timestamp")
            if not content_node:
                content_node = item.css_first("div.detail-body")
            link_node = title_node
            if not title_node or not content_node or not link_node:
                continue
            href = link_node.attributes.get("href") or ""
            full_url = urljoin(base_url, href)
            if not full_url:
                continue
            if time_node is None:
                time_node = item.css_first("span.topic-time")
            title_text = title_node.text(strip=True)
            if not title_text:
                topic_node = item.css_first("div.topic")
                title_text = topic_node.text(strip=True) if topic_node else ""
            record = {
                "title": title_text,
                "content": content_node.text(separator=" ", strip=True),
                "raw_html": item.html or "",
            }
            if time_node:
                record["published_at"] = time_node.text(strip=True)
            records[full_url] = record
        return records

    def extract_odaily_records(self, html: str, base_url: str) -> dict[str, dict[str, Any]]:
        marker = 'initData":'
        idx = html.find(marker)
        if idx == -1:
            return {}
        start = html.find("{", idx)
        if start == -1:
            return {}
        brace = 0
        end = None
        for pos in range(start, len(html)):
            ch = html[pos]
            if ch == '{':
                brace += 1
            elif ch == '}':
                brace -= 1
                if brace == 0:
                    end = pos + 1
                    break
        if end is None:
            return {}
        try:
            payload = json.loads(html[start:end])
        except json.JSONDecodeError:
            return {}
        page_result = payload.get("pageResult", {})
        items = page_result.get("list") or []
        records: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            record_url = urljoin(base_url, f"/zh-CN/newsflash/{item.get('id')}")
            description = item.get("description") or ""
            description_html = unescape(description)
            text_content = HTMLParser(description_html).text(separator=" ", strip=True)
            publish_ts = item.get("publishTimestamp")
            if isinstance(publish_ts, (int, float)):
                published = datetime.fromtimestamp(publish_ts / 1000, tz=timezone.utc).isoformat()
            else:
                published = None
            records[record_url] = {
                "title": item.get("title") or "",
                "content": text_content,
                "raw_html": description_html,
                "published_at": published,
            }
        return records


__all__ = ["Parser", "ParsedRecord"]
