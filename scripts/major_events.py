#!/usr/bin/env python3
"""Email ten domestic and ten international news briefs twice a day."""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cursor_news import load_cursor_events  # noqa: E402
from mail_schedule import begin_send, mark_sent  # noqa: E402
from github_trending_digest import (  # noqa: E402
    USER_AGENT,
    digest_recipient,
    formsubmit_needs_activation,
    redact,
    send_formsubmit,
    send_qq_smtp,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_AGE = timedelta(hours=40)
SENTENCE_RE = re.compile(r"(?<=[。！？])")
TAG_RE = re.compile(r"<[^>]+>")
SOFT_RE = re.compile(
    r"乡村行|影展|研学|微光计划|葫芦|开训仪式|建言|新风貌|产业入村|圈粉|"
    r"近观中国|国际论坛|长征路上|模拟外卖|田间地头|三件套|布展|总决赛|"
    r"直飞|万元起|灯船节|板球|旅游活力|医疗队|超级联赛|白皮书|关爱|"
    r"推荐官|焕发|圈粉|学习卡|官话|忆唱|纪念歌|开幕|开赛|图书馆|秋色|文化中国行|肌瘤|得了啥病|东西问|"
    r"淘金|热销|金球奖|精英赛|攀岩|双11|份额战|租赁资产|错位竞争"
)
DOMESTIC_FEEDS = (
    "https://www.chinanews.com.cn/rss/china.xml",
    "https://www.chinanews.com.cn/rss/importnews.xml",
)
WORLD_FEEDS = ("https://www.chinanews.com.cn/rss/world.xml",)


def sentence_count(text: str) -> int:
    return len([part for part in SENTENCE_RE.split(text) if part.strip()])


def _stamp(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def slot_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    # 09:15 Shanghai is 01:15 UTC; 18:15 Shanghai is 10:15 UTC.
    return "09:15" if current.astimezone(ZoneInfo("UTC")).hour < 6 else "18:15"


def subject_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    return f"国内外大事 · {current.strftime('%Y-%m-%d %H:%M')}（上海）"


def clean_fragment(value: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", value or "")
    text = TAG_RE.sub("", text)
    text = html.unescape(text).replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def _published_at(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_rss(xml_text: str, scope: str) -> list[dict[str, str]]:
    text = re.sub(r"<\?xml-stylesheet[^?]*\?>", "", xml_text)
    text = re.sub(r"<\?xml[^?]*\?>", '<?xml version="1.0" encoding="utf-8"?>', text, count=1)
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return []
    found: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = clean_fragment(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        found.append(
            {
                "title": title,
                "link": link,
                "summary": clean_fragment(item.findtext("description") or ""),
                "published": (item.findtext("pubDate") or "").strip(),
                "scope": scope,
                "source": "中国新闻网",
            }
        )
    return found


def accept_story(item: dict[str, str], now: datetime) -> bool:
    title = item["title"]
    if len(title) < 8 or SOFT_RE.search(title):
        return False
    published = _published_at(item.get("published", ""))
    if published is not None and now.astimezone(timezone.utc) - published > MAX_AGE:
        return False
    return True


def score_story(item: dict[str, str], now: datetime) -> int:
    score = 0
    published = _published_at(item.get("published", ""))
    if published is not None:
        age_hours = (now.astimezone(timezone.utc) - published).total_seconds() / 3600
        if age_hours <= 8:
            score += 6
        elif age_hours <= 20:
            score += 3
    if re.search(r"习近平|外交部|国务院|中央纪委|台风|地震|停火|选举|疫情|袭击|总统|一审|海试", item["title"]):
        score += 4
    if len(item.get("summary", "")) >= 80:
        score += 2
    return score


def rank_stories(items: list[dict[str, str]], now: datetime) -> list[dict[str, str]]:
    best: dict[str, dict[str, str]] = {}
    for item in items:
        if not accept_story(item, now):
            continue
        key = _cluster_key(item["title"])
        ranked = dict(item)
        ranked["score"] = score_story(item, now)
        previous = best.get(key)
        if previous is None or ranked["score"] > previous["score"]:
            best[key] = ranked
    ordered = list(best.values())
    ordered.sort(key=lambda item: (-int(item["score"]), -_timestamp(item), item["title"]))
    return ordered


def _looks_foreign(title: str) -> bool:
    return re.search(
        r"日本|美国|俄乌|以色列|印度|塞尔维亚|法国|加拿大|古巴|北约|伊朗|南苏丹|"
        r"马来西亚|叙利亚|约旦|巴西|苏丹|福岛|朝鲜|韩国|欧盟|英国",
        title,
    ) is not None


def _cluster_key(title: str) -> str:
    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", title)
    if "警方" in compact and "英" in compact:
        return "uk-police"
    if "伊朗" in compact and ("打击" in compact or "美军" in compact):
        return "iran-strike"
    return compact[:28]


def _timestamp(item: dict[str, str]) -> float:
    published = _published_at(item.get("published", ""))
    if published is None:
        return 0.0
    return published.timestamp()


def article_sentences(page: str) -> list[str]:
    start = page.find('class="left_zw"')
    if start < 0:
        return []
    chunk = page[start : start + 14000]
    for marker in ("<!--正文end-->", 'class="adEditor"', "recommend_news", "更多精彩内容"):
        end = chunk.find(marker)
        if end > 80:
            chunk = chunk[:end]
            break
    sentences: list[str] = []
    for fragment in re.findall(r"<p\b[^>]*>(.*?)</p>", chunk, re.S):
        text = clean_fragment(fragment)
        if len(text) < 18 or text.startswith("图为") or text.startswith("资料图"):
            continue
        for sentence in SENTENCE_RE.split(text):
            sentence = sentence.strip()
            if len(sentence) < 12 or re.search(r"热血沸腾|彩票中奖|全球南方需要什么", sentence):
                continue
            if len(sentence) > 180:
                cut = sentence[:170]
                comma = max(cut.rfind("，"), cut.rfind("；"))
                sentence = (cut[:comma] if comma >= 40 else cut).rstrip("，； ") + "。"
            elif sentence[-1] not in "。！？":
                sentence += "。"
            sentences.append(sentence)
            if len(sentences) == 4:
                return sentences
    return sentences


def body_from_sentences(sentences: list[str]) -> str:
    if len(sentences) < 3:
        return ""
    return "".join(sentences[:4])


def _fetch(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml,text/xml,*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset()
    if not charset:
        head = raw[:180].decode("latin1", errors="ignore")
        match = re.search(r'encoding=["\']([^"\']+)', head) or re.search(
            r'charset=["\']([^"\']+)', head, re.I
        )
        charset = match.group(1) if match else "utf-8"
    return raw.decode(charset, errors="replace")


def _with_body(item: dict[str, str]) -> dict[str, str] | None:
    try:
        sentences = article_sentences(_fetch(item["link"]))
    except (OSError, ValueError):
        return None
    body = body_from_sentences(sentences)
    if sentence_count(body) < 3:
        return None
    copied = dict(item)
    copied["body"] = body
    return copied


def materialize(items: list[dict[str, str]], limit: int = 20) -> list[dict[str, str]]:
    pool = items[: max(limit + 16, limit)]
    if not pool:
        return []
    workers = min(6, len(pool))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        loaded = list(executor.map(_with_body, pool))
    ready = [item for item in loaded if item]
    return ready[:limit]


def choose_slot(items: list[dict[str, str]], slot: str, count: int = 10) -> list[dict[str, str]]:
    offset = 0 if slot == "09:15" else 1
    chosen = [item for index, item in enumerate(items) if index % 2 == offset]
    if len(chosen) < count:
        used = {item["title"] for item in chosen}
        for item in items:
            if item["title"] in used:
                continue
            chosen.append(item)
            if len(chosen) == count:
                break
    return chosen[:count]


def select_events(
    now: datetime | None,
    domestic: list[dict[str, str]],
    world: list[dict[str, str]],
    count: int = 10,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    slot = slot_for(now)
    return choose_slot(domestic, slot, count), choose_slot(world, slot, count)


def load_events(now: datetime) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    domestic: list[dict[str, str]] = []
    world: list[dict[str, str]] = []
    for url in DOMESTIC_FEEDS:
        try:
            for item in parse_rss(_fetch(url), "国内"):
                if _looks_foreign(item["title"]) and "中方" not in item["title"] and "中国" not in item["title"] and "外交部" not in item["title"]:
                    item["scope"] = "国外"
                    world.append(item)
                else:
                    domestic.append(item)
        except (OSError, ET.ParseError, ValueError) as exc:
            print(f"domestic feed skipped: {exc}")
    for url in WORLD_FEEDS:
        try:
            world.extend(parse_rss(_fetch(url), "国外"))
        except (OSError, ET.ParseError, ValueError) as exc:
            print(f"world feed skipped: {exc}")
    domestic_ready = materialize(rank_stories(domestic, now))
    world_ready = materialize(rank_stories(world, now))
    print(f"events: domestic {len(domestic_ready)} from {len(domestic)}; world {len(world_ready)} from {len(world)}")
    return domestic_ready, world_ready


def material_note(items: list[dict[str, str]]) -> str:
    if any(item.get("via") == "cursor" for item in items):
        return "每条事实来自 Cursor 云端代理当场的联网搜索，并打开了原文。不使用模型记忆。默认模型是 Grok 4.7。"
    return "材料来自中国新闻网公开报道，只摘开头几句，不是评论。"


def render_text(
    domestic: list[dict[str, str]],
    world: list[dict[str, str]],
    now: datetime | None = None,
) -> str:
    current = _stamp(now)
    lines = [
        subject_for(current),
        "",
        "国内大事 10 条，国外大事 10 条。每条用报道里的三四句话说明。",
        f"整理时间：{current.strftime('%Y-%m-%d %H:%M')} 上海时间",
        "",
        "国内大事",
        "",
    ]
    for index, item in enumerate(domestic, start=1):
        lines.append(f"{index}. {item['title']}")
        lines.append(item["body"])
        lines.append("")
    lines.append("国外大事")
    lines.append("")
    for index, item in enumerate(world, start=1):
        lines.append(f"{index}. {item['title']}")
        lines.append(item["body"])
        lines.append("")
    lines.append(material_note(list(domestic) + list(world)))
    lines.append("每天 09:15 和 18:15（上海时间）自动发送，上下午不是同一组。")
    return "\n".join(lines).strip() + "\n"


def _blocks(items: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(items, start=1):
        link = item.get("link") or ""
        source = ""
        if link.startswith("https://"):
            label = item.get("source") or "原文"
            source = (
                "<div style=\"margin-top:6px;font-size:12px;\">"
                f"<a href=\"{html.escape(link, quote=True)}\" style=\"color:#0969da;text-decoration:none;\">"
                f"{html.escape(label)}</a></div>"
            )
        blocks.append(
            "<div style=\"padding:16px 0;border-bottom:1px solid #e6e8eb;\">"
            f"<div style=\"font-size:18px;font-weight:700;color:#1f2328;\">{index}. {html.escape(item['title'])}</div>"
            f"<p style=\"margin:8px 0 0;font-size:15px;line-height:1.75;color:#24292f;\">{html.escape(item['body'])}</p>"
            f"{source}</div>"
        )
    return "".join(blocks)


def render_html(
    domestic: list[dict[str, str]],
    world: list[dict[str, str]],
    now: datetime | None = None,
) -> str:
    current = _stamp(now)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{html.escape(subject_for(current))}</title></head>
<body style="margin:0;padding:0;background:#f6f8fa;color:#1f2328;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fa;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;">
        <tr><td style="background:#1f2328;color:#ffffff;padding:22px 24px;border-radius:12px 12px 0 0;">
          <div style="font-size:13px;letter-spacing:0.04em;color:#c9d1d9;">MAJOR EVENTS</div>
          <div style="font-size:22px;font-weight:700;margin-top:6px;">国内 10 条 · 国外 10 条</div>
          <div style="font-size:13px;color:#c9d1d9;margin-top:8px;">{html.escape(current.strftime("%Y-%m-%d %H:%M"))} 上海时间 · 每天 09:15 与 18:15</div>
        </td></tr>
        <tr><td style="background:#ffffff;padding:8px 24px 22px;border:1px solid #d0d7de;border-top:0;border-radius:0 0 12px 12px;">
          <h2 style="margin:18px 0 0;font-size:16px;">国内大事</h2>
          {_blocks(domestic)}
          <h2 style="margin:22px 0 0;font-size:16px;">国外大事</h2>
          {_blocks(world)}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Email ten domestic and ten world news briefs.")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--html-out", default="")
    parser.add_argument("--text-out", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _stamp()
    slot = None
    if args.send:
        slot = begin_send("events", now)
        if slot is None:
            return 0
    cursor_pair = load_cursor_events(now)
    if cursor_pair is not None:
        domestic, world = cursor_pair
    else:
        try:
            domestic_ready, world_ready = load_events(now)
        except Exception as exc:  # noqa: BLE001
            print(f"event load failed: {exc}", file=sys.stderr)
            return 3
        domestic, world = select_events(now, domestic_ready, world_ready)
    if len(domestic) < 10 or len(world) < 10:
        print(
            f"only found domestic {len(domestic)} and world {len(world)}; still sending what is ready",
            file=sys.stderr,
        )
    subject = subject_for(now)
    text = render_text(domestic, world, now)
    html_body = render_html(domestic, world, now)
    print(f"subject: {subject}")
    print("domestic: " + "；".join(item["title"] for item in domestic))
    print("world: " + "；".join(item["title"] for item in world))
    if args.text_out:
        os.makedirs(os.path.dirname(args.text_out) or ".", exist_ok=True)
        with open(args.text_out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {args.text_out}")
    if args.html_out:
        os.makedirs(os.path.dirname(args.html_out) or ".", exist_ok=True)
        with open(args.html_out, "w", encoding="utf-8") as handle:
            handle.write(html_body)
        print(f"wrote {args.html_out}")
    if not args.send:
        sys.stdout.write(text)
        return 0

    recipient = digest_recipient()
    if not recipient:
        print("DIGEST_TO is not set. Refusing to send.", file=sys.stderr)
        return 3
    auth_code = os.environ.get("QQ_SMTP_AUTH_CODE", "").strip()
    smtp_user = os.environ.get("QQ_SMTP_USER", "").strip() or recipient
    if auth_code:
        try:
            send_qq_smtp(
                user=smtp_user,
                auth_code=auth_code,
                recipient=recipient,
                subject=subject,
                text=text,
                html_body=html_body,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"QQ SMTP send failed: {redact(str(exc), recipient, smtp_user, auth_code)}", file=sys.stderr)
            return 3
        mark_sent("events", now, slot or "09:15")
        print("sent via QQ SMTP")
        return 0
    if os.environ.get("DIGEST_FALLBACK", "").strip().lower() == "formsubmit":
        try:
            result = send_formsubmit(
                recipient=recipient,
                subject=subject,
                text=text,
                sender_name="国内外大事",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"FormSubmit send failed: {redact(str(exc), recipient)}", file=sys.stderr)
            return 3
        if formsubmit_needs_activation(result):
            print("FormSubmit sent an activation email.")
            return 0
        mark_sent("events", now, slot or "09:15")
        print("sent via FormSubmit")
        return 0
    print(
        "QQ_SMTP_AUTH_CODE is not set. Refusing to send. "
        "Export the QQ mailbox authorization code, or set DIGEST_FALLBACK=formsubmit.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
