#!/usr/bin/env python3
"""Ask a Cursor cloud agent for current events it has just opened on the web."""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from cursor_agent import CursorResearchError, api_key, run_research

SHANGHAI = ZoneInfo("Asia/Shanghai")
SENTENCE_RE = re.compile(r"(?<=[。！？])")
IDEA_CATEGORIES = ("世间", "人生", "工作", "健康", "财富", "知识")
IDEA_TOPICS = ("ai", "world", "work", "climate", "health", "wealth", "society")
MIN_EVENTS = 8
MIN_IDEAS = 8
Runner = Callable[[str, str], tuple[str, list[str]]]


def sentence_count(text: str) -> int:
    return len([part for part in SENTENCE_RE.split(text) if part.strip()])


def clip_sentences(text: str) -> str:
    parts = [part.strip() for part in SENTENCE_RE.split(text or "") if part.strip()]
    if len(parts) < 3:
        return ""
    clipped = "".join(parts[:4])
    if clipped[-1] not in "。！？":
        clipped += "。"
    return clipped


def extract_json(text: str) -> dict:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise CursorResearchError("agent reply had no JSON object")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise CursorResearchError("agent reply was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CursorResearchError("agent reply JSON was not an object")
    return payload


def usable_link(value: str) -> bool:
    link = (value or "").strip()
    if not link.startswith("https://") or " " in link:
        return False
    host = (urllib.parse.urlparse(link).hostname or "").lower()
    if not host or host.endswith(".google.com") or "google." in host:
        return False
    if host in {"news.google.com", "www.bing.com", "bing.com"}:
        return False
    return True


def _items(payload: dict, key: str) -> list[dict]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _event(row: dict, scope: str) -> dict[str, str] | None:
    title = str(row.get("title") or "").strip()
    source = str(row.get("source") or "").strip()
    link = str(row.get("link") or "").strip()
    body = clip_sentences(str(row.get("body") or ""))
    if len(title) < 6 or len(source) < 2 or not usable_link(link) or sentence_count(body) < 3:
        return None
    return {
        "title": title.rstrip("。"),
        "source": source,
        "link": link,
        "body": body,
        "scope": scope,
        "via": "cursor",
    }


def _dedupe(items: list[dict[str, str]]) -> list[dict[str, str]]:
    kept: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        key = item["title"] + "|" + item["link"]
        if item["title"] in seen or item["link"] in seen or key in seen:
            continue
        seen.add(item["title"])
        seen.add(item["link"])
        kept.append(item)
    return kept


def parse_events(text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    payload = extract_json(text)
    domestic = _dedupe([item for row in _items(payload, "domestic") if (item := _event(row, "国内"))])
    world = _dedupe([item for row in _items(payload, "world") if (item := _event(row, "国外"))])
    return domestic[:10], world[:10]


def parse_ideas(text: str) -> list[dict[str, str]]:
    payload = extract_json(text)
    ideas: list[dict[str, str]] = []
    for row in _items(payload, "ideas"):
        title = str(row.get("title") or "").strip().rstrip("。")
        category = str(row.get("category") or "").strip()
        topic = str(row.get("topic") or "").strip()
        source = str(row.get("source") or "").strip()
        link = str(row.get("link") or "").strip()
        body = clip_sentences(str(row.get("body") or ""))
        if category not in IDEA_CATEGORIES or topic not in IDEA_TOPICS:
            continue
        if len(title) < 4 or len(source) < 2 or not usable_link(link) or sentence_count(body) < 3:
            continue
        ideas.append(
            {
                "category": category,
                "title": title,
                "body": body,
                "source": source,
                "link": link,
                "topic": topic,
                "grounded": "yes",
                "via": "cursor",
            }
        )
    return _dedupe(ideas)[:10]


def events_prompt(now: datetime) -> str:
    current = now.astimezone(SHANGHAI)
    slot = "09:15" if current.hour < 12 else "18:15"
    focus = (
        "优先午夜到今早的报道。"
        if slot == "09:15"
        else "优先今天中午以后仍在发展的报道，避开只是复述今早已经讲过的通稿。"
    )
    return f"""你在查今天的时事。现在是 {current.strftime("%Y-%m-%d %H:%M")}（上海），这一档是 {slot}。
禁止凭模型记忆作答。每条事实都要先调用 web_search，再对将要引用的页面调用 web_fetch。
没有打开过的页面不要写进结果。不要改文件，不要提代码。这是没有代码仓库的检索。

只输出一个 JSON 对象，不要 Markdown：
{{"domestic":[{{"title":"","source":"","link":"","body":""}}],"world":[{{"title":"","source":"","link":"","body":""}}]}}

domestic 恰好 10 条中国国内大事，world 恰好 10 条国外大事。{focus}
title 用中文，不超过 40 字。source 是媒体名。link 必须是你 web_fetch 打开过的 https 原文，不要用搜索引擎的跳转链接。
body 从该网页摘 3 到 4 句中文，保留事实，不要评论，不要写「这说明」。
避开文旅花絮、赛事开幕式、广告和同一事件的重复稿。国内和国外不要写成同一件事。
"""


def ideas_prompt(now: datetime) -> str:
    current = now.astimezone(SHANGHAI)
    slot = "09:30" if current.hour < 12 else "18:30"
    focus = "偏已经发生的政策、科技和公共安排。" if slot == "09:30" else "偏仍在变化的国际、社会和产业消息。"
    return f"""你在整理「每日想法」。现在是 {current.strftime("%Y-%m-%d %H:%M")}（上海），这一档是 {slot}。{focus}
禁止凭模型记忆写时事。每条都要先 web_search，再 web_fetch 打开一篇近三天的公开报道。
不要改文件。不要输出记忆里的旧闻。

只输出一个 JSON 对象，不要 Markdown：
{{"ideas":[{{"category":"","title":"","body":"","source":"","link":"","topic":""}}]}}

恰好 10 条。category 只能是：世间、人生、工作、健康、财富、知识。
topic 只能是：ai、world、work、climate、health、wealth、society。
数量：ai 3 条，world 2 条，work、climate、health、wealth、society 各 1 条。
title 用中文，不超过 28 字，不要照抄报道标题。
body 正好 3 或 4 句。第一句复述你打开的报道里的事实，并点出媒体名。后面的句子给读者一个今天用得上的判断。
不要写成投资建议或医疗建议。link 必须是你 web_fetch 打开过的 https 原文。
"""


def _usable(rows: list[dict[str, str]], minimum: int) -> bool:
    return len(rows) >= minimum


def load_cursor_events(
    now: datetime,
    runner: Runner | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]] | None:
    """Return searched stories, or None when Cursor is not configured or the search is too thin."""
    if not api_key():
        print("CURSOR_API_KEY is not set; events stay on RSS")
        return None
    research = runner or run_research
    try:
        text, tools = research(events_prompt(now), f"国内外大事 {now.astimezone(SHANGHAI).strftime('%m-%d %H:%M')}")
        domestic, world = parse_events(text)
    except (CursorResearchError, OSError, ValueError) as exc:
        print(f"cursor events skipped: {exc}")
        return None
    print(
        "cursor events searched with "
        + ",".join(sorted(set(tools)))
        + f"; kept domestic {len(domestic)} world {len(world)}"
    )
    if not _usable(domestic, MIN_EVENTS) or not _usable(world, MIN_EVENTS):
        print("cursor events were too few after checks; using RSS")
        return None
    return domestic, world


def load_cursor_ideas(now: datetime, runner: Runner | None = None) -> list[dict[str, str]] | None:
    if not api_key():
        print("CURSOR_API_KEY is not set; ideas stay on RSS")
        return None
    research = runner or run_research
    try:
        text, tools = research(ideas_prompt(now), f"每日想法 {now.astimezone(SHANGHAI).strftime('%m-%d %H:%M')}")
        ideas = parse_ideas(text)
    except (CursorResearchError, OSError, ValueError) as exc:
        print(f"cursor ideas skipped: {exc}")
        return None
    print("cursor ideas searched with " + ",".join(sorted(set(tools))) + f"; kept {len(ideas)}")
    if not _usable(ideas, MIN_IDEAS):
        print("cursor ideas were too few after checks; using RSS")
        return None
    return ideas
