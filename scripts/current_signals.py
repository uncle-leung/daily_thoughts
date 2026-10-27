#!/usr/bin/env python3
"""Collect recent public reporting for the daily ideas letter."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from github_trending_digest import USER_AGENT, parse_gtx_payload

MAX_AGE = timedelta(days=4)
TRADITIONAL_MARKERS = set(
    "國與為麼這後發對會說開關東車門問間長馬體機電無書學點線網業產價過進選變"
    "個們來執總將關係敗複雜斷從還經現時臺萬廣獨義"
)
LOW_VALUE_RE = re.compile(
    r"举办|座谈会|学术报告|招聘活动|走进|专场|直播间|期货|涨超|大涨|涨逾|"
    r"碎屏|摇一摇|卖房了|迷因|Vegemite|梅根|血细胞|甲状腺|折叠|蝙蝠|囚犯|"
    r"iPhone Duo|赵长鹏|三季报|净利润|请收好|谨防|扩容|锁定集团|"
    r"收盘|股指|交易热情|社论|推介会|颁奖|举行|有救了|迷你机|多中心|纵向|"
    r"病例系列|靶向|临床特征|要守不住|政务公开|财富自由|监测|暴拉|刷屏|"
    r"毫无区别|老酒|天使轮|天使\+|出席|SUMMIT|分享|病例对照|倾向评分|决策链路|迈向信任|消费决策|生意增长"
)
TOPIC_CATEGORY = {
    "ai": "知识",
    "work": "工作",
    "health": "健康",
    "wealth": "财富",
    "world": "世间",
    "climate": "世间",
    "society": "人生",
}
TAG_RE = re.compile(r"<[^>]+>")


def _fetch(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def strip_html(value: str) -> str:
    text = TAG_RE.sub(" ", value or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if "news.google.com" in text or text.startswith("http"):
        return ""
    return text


def split_headline(title: str, default_source: str) -> tuple[str, str]:
    title = re.sub(r"^(原创｜|原创\|)", "", title.strip())
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        tail = tail.strip()
        if 1 < len(tail) <= 24 and not tail.startswith("http"):
            return head.strip(), tail
    return title.strip(), default_source


def looks_traditional(text: str) -> bool:
    return any(char in TRADITIONAL_MARKERS for char in text)


def to_simplified(text: str) -> str:
    text = text.strip()
    if not text or not looks_traditional(text):
        return text
    url = (
        "https://translate.googleapis.com/translate_a/single?client=gtx"
        "&sl=zh-TW&tl=zh-CN&dt=t&q=" + urllib.parse.quote(text[:900])
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8", errors="replace")
        converted = parse_gtx_payload(json.loads(payload)).strip()
    except (OSError, ValueError, json.JSONDecodeError):
        return text
    return converted or text


def topic_of(title: str) -> str:
    """Classify from the headline only, so a long article cannot pull the idea off topic."""
    if re.search(r"裁员|裁員|离职|離職|就业|就業|岗位|崗位|员工|員工|奖金|獎金|工会|工會|农民工|農民工", title):
        return "work"
    if re.search(r"痴呆|癡呆|癌症|筛查|篩查|疫情|疫苗|疾病|阿尔茨海默|腸癌|肠癌", title):
        return "health"
    if re.search(r"热浪|熱浪|气候|氣候|泄漏|洩漏|漏油|污染|汙染|排放|干旱|乾旱|洪水", title):
        return "climate"
    if re.search(
        r"人工智能|人工智慧|大模型|生成式|开放权重|開放權重|机器人|機器人|芯片|晶片|算法|演算法|"
        r"Anthropic|Claude|(?<![A-Za-z])AI(?![A-Za-z])",
        title,
        re.I,
    ):
        return "ai"
    if re.search(r"招股|贸易|貿易|进出口|進出口|金价|金價|房价|房價", title):
        return "wealth"
    if re.search(r"战争|戰爭|选举|選舉|停火|移民|饥荒|飢荒|制裁|星链|星鏈|冲突|衝突|军费|軍費", title):
        return "world"
    if re.search(r"养老|養老|人口|隐私|隱私|平台经济|平臺經濟|延迟退休|延遲退休|灵活就业|靈活就業|零工", title):
        return "society"
    return ""


def classify(text: str) -> str:
    return TOPIC_CATEGORY.get(topic_of(text), "")


def parse_rss(xml_bytes: bytes, default_source: str, *, keep_summary: bool = True) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    found: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        raw_title = strip_html(item.findtext("title") or "")
        if not raw_title:
            continue
        title, source = split_headline(raw_title, default_source)
        summary = ""
        if keep_summary:
            summary = strip_html(item.findtext("description") or "")
            if summary == title or len(summary) < 40 or "http" in summary or "www." in summary:
                summary = ""
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        found.append(
            {
                "title": title,
                "summary": summary,
                "source": source,
                "link": link,
                "published": published,
            }
        )
    return found


def _published_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def accept_signal(item: dict[str, str], now: datetime) -> bool:
    if LOW_VALUE_RE.search(item["title"]):
        return False
    if not topic_of(item["title"]):
        return False
    if len(item["title"]) < 8:
        return False
    published = _published_at(item["published"])
    current = now.astimezone(timezone.utc)
    if published is not None and current - published > MAX_AGE:
        return False
    return True


def score_signal(item: dict[str, str], now: datetime) -> int:
    score = 0
    if len(item["summary"]) >= 80:
        score += 6
    elif len(item["summary"]) >= 40:
        score += 3
    published = _published_at(item["published"])
    if published is not None:
        age_hours = (now.astimezone(timezone.utc) - published).total_seconds() / 3600
        if age_hours <= 18:
            score += 4
        elif age_hours <= 48:
            score += 2
    if item["source"] in {"Solidot", "BBC中文"}:
        score += 2
    if re.search(r"战争|戰爭|停火|星链|星鏈|移民|热浪|熱浪|漏油|辟谣|辟謠|贸易|貿易|进出口|進出口|金价|金價", item["title"]):
        score += 3
    return score


def _cluster_key(title: str) -> str:
    folded = title.casefold()
    numbers = re.findall(r"\d+(?:\.\d+)?\s*亿", folded)
    orgs = [
        name
        for name in ("anthropic", "openai", "ibm", "微软", "meta", "英伟达", "nvidia", "谷歌", "google")
        if name in folded
    ]
    if orgs and numbers:
        return "deal:" + "+".join(orgs) + ":" + "+".join(numbers)
    if "人口" in folded:
        return "society:population"
    return re.sub(r"[\s，。、“”\"'：:？?！!|]", "", folded)[:40]


def prepare_signals(items: list[dict[str, str]], now: datetime) -> list[dict[str, str]]:
    best: dict[str, dict[str, str]] = {}
    for item in items:
        if not accept_signal(item, now):
            continue
        key = _cluster_key(item["title"])
        ranked = dict(item)
        ranked["topic"] = topic_of(item["title"])
        ranked["category"] = TOPIC_CATEGORY[ranked["topic"]]
        ranked["score"] = score_signal(item, now)
        previous = best.get(key)
        if previous is None or ranked["score"] > previous["score"]:
            best[key] = ranked
    ordered = list(best.values())
    ordered.sort(key=lambda item: (-int(item["score"]), item["title"]))
    return ordered


def _google(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


def feed_urls() -> list[tuple[str, str, bool]]:
    return [
        ("Solidot", "https://www.solidot.org/index.rss", True),
        ("BBC中文", "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", True),
        ("Google 新闻", _google("人工智能 OR 大模型 OR Anthropic when:3d"), False),
        ("Google 新闻", _google("灵活就业 OR 延迟退休 OR 人口 OR 平台经济 OR 消费 when:5d"), False),
        ("Google 新闻", "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-CN&gl=CN&ceid=CN:zh-Hans", False),
        ("Google 新闻", "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans", False),
        ("Google 新闻", "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=zh-CN&gl=CN&ceid=CN:zh-Hans", False),
        ("Google 新闻", "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-CN&gl=CN&ceid=CN:zh-Hans", False),
    ]


def load_signals(now: datetime) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    for source, url, keep_summary in feed_urls():
        try:
            collected.extend(parse_rss(_fetch(url), source, keep_summary=keep_summary))
        except (OSError, ET.ParseError, ValueError) as exc:
            print(f"signal source skipped ({source}): {exc}")
    prepared = prepare_signals(collected, now)
    print(f"signals: {len(prepared)} from {len(collected)} headlines")
    return prepared


def simplify_signal(item: dict[str, str]) -> dict[str, str]:
    copied = dict(item)
    copied["title"] = to_simplified(item["title"])
    copied["summary"] = to_simplified(item["summary"])
    return copied
