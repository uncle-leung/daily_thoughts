#!/usr/bin/env python3
"""Chinese-English study pairs for major events and daily thoughts."""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CATEGORY_EN = {
    "世间": "World",
    "人生": "Life",
    "工作": "Work",
    "健康": "Health",
    "财富": "Wealth",
    "知识": "Knowledge",
}
HEADING_EN = {
    "国内大事": "China",
    "国外大事": "World",
}
EVENTS_SUBTITLE_EN = "Ten from China, ten from abroad"
IDEAS_SUBTITLE_EN = "Ten thoughts"
STUDY_NOTE_EN = (
    "Read the Chinese first, then the English in the green box. "
    "The English is a study translation."
)

# Content words a learner can reuse. Longer phrases win when they overlap.
GLOSSARY = {
    "人工智能": "artificial intelligence",
    "开放权重": "open weights",
    "计算能力": "computing power",
    "供应链": "supply chain",
    "现金流": "cash flow",
    "人口老龄化": "an aging population",
    "老龄化": "aging population",
    "永久居留": "permanent residence",
    "低空经济": "low-altitude economy",
    "商用飞机": "commercial aircraft",
    "霍尔木兹海峡": "Strait of Hormuz",
    "阿尔茨海默病": "Alzheimer's disease",
    "公共卫生": "public health",
    "冷空气": "cold air",
    "雨夹雪": "sleet",
    "儿童票": "child ticket",
    "政绩观": "view of political performance",
    "融资项目": "financing project",
    "停火": "ceasefire",
    "选举": "election",
    "制裁": "sanctions",
    "总统": "president",
    "袭击": "attack",
    "疫情": "epidemic",
    "地震": "earthquake",
    "台风": "typhoon",
    "外交": "diplomacy",
    "航班": "flight",
    "停飞": "ground stop",
    "油轮": "oil tanker",
    "爆炸": "explosion",
    "示威": "protest",
    "拘捕": "arrest",
    "纵火": "arson",
    "抢劫": "robbery",
    "卫星": "satellite",
    "火箭": "rocket",
    "轨道": "orbit",
    "降温": "drop in temperature",
    "降雪": "snowfall",
    "暴雪": "blizzard",
    "大风": "strong wind",
    "阵风": "gust",
    "模型": "model",
    "融资": "funding",
    "估值": "valuation",
    "算力": "computing power",
    "芯片": "chip",
    "无人机": "drone",
    "裁员": "layoffs",
    "岗位": "job",
    "养老": "elder care",
    "隐私": "privacy",
    "罚款": "fine",
    "睡眠": "sleep",
    "处方": "prescription",
    "物价": "prices",
    "远程": "remote",
    "病例": "cases",
    "流感": "flu",
    "埃博拉": "Ebola",
    "贸易": "trade",
    "出口": "exports",
    "黄金": "gold",
    "房价": "housing prices",
    "调查": "investigation",
    "政府": "government",
    "警方": "police",
    "军事": "military",
    "防空": "air defense",
    "签证": "visa",
    "志愿者": "volunteer",
    "捐赠": "donation",
    "峰会": "summit",
    "领导人": "leaders",
    "冲突": "conflict",
    "停火协议": "ceasefire agreement",
    "通胀": "inflation",
    "利率": "interest rate",
    "裁员潮": "wave of layoffs",
    "工作效率": "productivity",
    "数据隐私": "data privacy",
    "算法": "algorithm",
    "开源": "open source",
    "闭源": "closed source",
    "创业": "startup",
    "投资": "investment",
    "亏损": "loss",
    "盈利": "profit",
    "失业": "unemployment",
    "加班": "overtime",
    "远程办公": "remote work",
    "心理健康": "mental health",
    "疫苗": "vaccine",
    "确诊": "confirmed diagnosis",
    "症状": "symptom",
    "医院": "hospital",
    "气候": "climate",
    "排放": "emissions",
    "干旱": "drought",
    "洪水": "flood",
    "热浪": "heat wave",
    "能源": "energy",
    "石油": "oil",
    "天然气": "natural gas",
    "股票": "shares",
    "汇率": "exchange rate",
    "关税": "tariff",
    "出口管制": "export controls",
    "供应链中断": "supply-chain disruption",
    "人道主义": "humanitarian",
    "难民": "refugees",
    "停火谈判": "ceasefire talks",
    "大选": "general election",
    "议会": "parliament",
    "首相": "prime minister",
    "外交部": "foreign ministry",
    "声明": "statement",
    "协议": "agreement",
    "条约": "treaty",
}

PAIR_RE = re.compile(
    r'<div style="(?P<title_style>[^"]*font-size:18px;font-weight:700;[^"]*)">(?P<title>[^<]*)</div>\s*'
    r'(?P<title_en><div[^>]*data-study="en"[^>]*>.*?</div>\s*)?'
    r'<p style="(?P<body_style>margin:8px 0 0;font-size:15px;line-height:[^"]*)">(?P<body>[^<]*)</p>',
    re.S,
)
HEADING_RE = re.compile(r'(<h2 style="margin:[^"]*">)(.*?)(</h2>)', re.S)
CATEGORY_RE = re.compile(
    r'(<div style="font-size:12px;letter-spacing:0.04em;color:#57606a;">)([^<]*)(</div>)'
)
INTRO_RE = re.compile(
    r'(<p style="margin:16px 0 0;color:#57606a;font-size:14px;line-height:1\.6;">)(.*?)(</p>)',
    re.S,
)
INDEX_RE = re.compile(r"^(\d+\.\s*)(\S.*)$", re.S)
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def cache_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "study-en.json"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def usable_english(text: str) -> str:
    """Keep a study translation only when it is mostly English."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    letters = len(re.findall(r"[A-Za-z]", cleaned))
    han = len(HAN_RE.findall(cleaned))
    if letters < 3 or letters < han:
        return ""
    for wrong, right in (
        ("Jen-Hsun Huang", "Jensen Huang"),
        ("Huang Jen-Hsun", "Jensen Huang"),
        ("Huang Renxun", "Jensen Huang"),
    ):
        cleaned = cleaned.replace(wrong, right)
    return cleaned


def load_cache(path: Path | None = None) -> dict[str, str]:
    file = path or cache_path()
    if not file.is_file():
        return {}
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if usable_english(str(value))}


def save_cache(cache: dict[str, str], path: Path | None = None) -> None:
    file = path or cache_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: cache[key] for key in sorted(cache)}
    file.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _chunks(text: str, limit: int = 420) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = [part for part in SENTENCE_SPLIT_RE.split(text) if part]
    if not parts:
        return [text[index : index + limit] for index in range(0, len(text), limit)]
    packed: list[str] = []
    current = ""
    for part in parts:
        if len(part) > limit:
            if current:
                packed.append(current)
                current = ""
            packed.extend(part[index : index + limit] for index in range(0, len(part), limit))
            continue
        if current and len(current) + len(part) > limit:
            packed.append(current)
            current = part
        else:
            current += part
    if current:
        packed.append(current)
    return packed


_google_paused = False


def _google_one(text: str) -> str:
    """One Google request. A 429 pauses Google for the rest of this process."""
    global _google_paused
    if _google_paused or not text:
        return ""
    last_error: Exception | None = None
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": "zh-CN", "tl": "en", "dt": "t", "q": text}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return "".join(row[0] for row in payload[0] if row and row[0])
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                _google_paused = True
                print("translate paused: Google returned 429, switching to the backup translator")
                return ""
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
        except (OSError, ValueError, IndexError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    print(f"translate failed: {last_error}")
    return ""


def google_translate(text: str) -> str:
    if _google_paused:
        return ""
    pieces = [_google_one(piece) for piece in _chunks(normalize(text))]
    return re.sub(r"\s+", " ", " ".join(piece for piece in pieces if piece)).strip()


def _mymemory_one(text: str) -> str:
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
        {"q": text, "langpair": "zh-CN|en"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"backup translate failed: {exc}")
        return ""
    translated = str((payload.get("responseData") or {}).get("translatedText") or "")
    if payload.get("quotaFinished") or "MYMEMORY WARNING" in translated.upper():
        print("backup translate quota finished")
        return ""
    return translated


def mymemory_translate(text: str) -> str:
    pieces = [_mymemory_one(piece) for piece in _chunks(normalize(text), limit=400)]
    return re.sub(r"\s+", " ", " ".join(piece for piece in pieces if piece)).strip()


def study_translate(text: str) -> str:
    """Google first. When GitHub Actions is rate-limited, MyMemory fills the gap."""
    english = usable_english(google_translate(text))
    if english:
        return english
    return usable_english(mymemory_translate(text))


def glossary_hits(text: str, limit: int = 5) -> list[tuple[str, str]]:
    """Up to a few useful words, longer phrases first, then reading order."""
    source = text or ""
    occupied = [False] * len(source)
    found: list[tuple[int, str, str]] = []
    for zh, en in sorted(GLOSSARY.items(), key=lambda item: len(item[0]), reverse=True):
        start = 0
        while True:
            index = source.find(zh, start)
            if index < 0:
                break
            end = index + len(zh)
            if any(occupied[index:end]):
                start = index + 1
                continue
            for mark in range(index, end):
                occupied[mark] = True
            found.append((index, zh, en))
            break
    if len(found) > limit:
        found = sorted(found, key=lambda item: (-len(item[1]), item[0]))[:limit]
    found.sort()
    return [(zh, en) for _index, zh, en in found]


def vocab_html(text: str) -> str:
    hits = glossary_hits(text)
    if not hits:
        return ""
    chips = " · ".join(
        f'<span style="color:#0f766e;font-weight:600;">{html.escape(en)}</span> {html.escape(zh)}'
        for zh, en in hits
    )
    return (
        '<div data-study="vocab" style="margin-top:8px;font-size:12px;line-height:1.7;color:#57606a;">'
        f"生词 {chips}</div>"
    )


def vocab_text(text: str) -> str:
    hits = glossary_hits(text)
    if not hits:
        return ""
    return "生词: " + " · ".join(f"{en} {zh}" for zh, en in hits)


def english_title_html(text: str) -> str:
    if not text:
        return ""
    return (
        '<div data-study="en" style="margin-top:4px;font-size:14px;font-weight:600;'
        'line-height:1.45;color:#0f766e;">'
        f"{html.escape(text)}</div>"
    )


def english_body_html(text: str) -> str:
    if not text:
        return ""
    return (
        '<p data-study="en" style="margin:8px 0 0;padding:10px 12px;border-left:3px solid #14b8a6;'
        'background:#f3fbfa;font-size:14px;line-height:1.75;color:#134e4a;">'
        '<span style="display:inline-block;margin-right:6px;padding:1px 5px;border-radius:4px;'
        "background:#0f766e;color:#ffffff;font-size:10px;letter-spacing:0.08em;"
        'vertical-align:1px;">EN</span>'
        f"{html.escape(text)}</p>"
    )


def study_note_html() -> str:
    return (
        '<p data-study="note" style="margin:16px 0 0;color:#57606a;font-size:14px;line-height:1.65;">'
        "中英对照，用来学英语。先读中文，再读绿色框里的英文。"
        f'<br><span style="color:#0f766e;">{html.escape(STUDY_NOTE_EN)}</span></p>'
    )


def header_en_html(text: str) -> str:
    return (
        '<div data-study="en" style="font-size:14px;font-weight:500;color:#9ad7d0;margin-top:4px;">'
        f"{html.escape(text)}</div>"
    )


def section_heading(zh: str, en: str, *, margin: str) -> str:
    return (
        f'<h2 style="margin:{margin};font-size:16px;">{html.escape(zh)} '
        f'<span style="font-weight:600;color:#0f766e;">· {html.escape(en)}</span></h2>'
    )


def category_label(category: str) -> str:
    english = CATEGORY_EN.get(category, "")
    if not english:
        return category
    return f"{category} · {english}"


def _split_index(title: str) -> tuple[str, str]:
    match = INDEX_RE.match(title.strip())
    if not match:
        return "", title.strip()
    return match.group(1), match.group(2).strip()


def annotate_study_letter(page: str, *, cache: dict[str, str] | None = None) -> str:
    """Add study English to an already sent events or ideas letter. Idempotent."""
    if "MAJOR EVENTS" not in page and "DAILY THOUGHTS" not in page:
        return page
    known = cache if cache is not None else load_cache()

    def lookup(text: str) -> str:
        return usable_english(known.get(normalize(text), ""))

    def replace_pair(match: re.Match[str]) -> str:
        tail = page[match.end() : match.end() + 220]
        has_body_en = 'data-study="en"' in tail
        existing_title = match.group("title_en") or ""
        if existing_title and has_body_en:
            return match.group(0)
        title = normalize(match.group("title"))
        body = normalize(match.group("body"))
        _prefix, core = _split_index(title)
        title_en = lookup(core)
        body_en = lookup(body)
        if not existing_title and not title_en:
            return match.group(0)
        if not body_en and not has_body_en:
            return match.group(0)
        title_html = f'<div style="{match.group("title_style")}">{match.group("title")}</div>'
        if existing_title:
            title_html += existing_title
        elif title_en:
            title_html += english_title_html(title_en)
        body_html = f'<p style="{match.group("body_style")}">{match.group("body")}</p>'
        if body_en and not has_body_en:
            body_html += english_body_html(body_en)
            if 'data-study="vocab"' not in tail:
                body_html += vocab_html(core + body)
        return title_html + body_html

    page = PAIR_RE.sub(replace_pair, page)

    def replace_heading(match: re.Match[str]) -> str:
        label = normalize(match.group(2))
        english = HEADING_EN.get(label)
        if not english or "·" in label:
            return match.group(0)
        return (
            f"{match.group(1)}{html.escape(label)} "
            f'<span style="font-weight:600;color:#0f766e;">· {html.escape(english)}</span>{match.group(3)}'
        )

    page = HEADING_RE.sub(replace_heading, page)

    def replace_category(match: re.Match[str]) -> str:
        label = normalize(match.group(2))
        english = CATEGORY_EN.get(label)
        if not english:
            return match.group(0)
        return f"{match.group(1)}{html.escape(label)} · {html.escape(english)}{match.group(3)}"

    page = CATEGORY_RE.sub(replace_category, page)
    if EVENTS_SUBTITLE_EN not in page:
        page = page.replace(
            "国内 10 条 · 国外 10 条</div>",
            "国内 10 条 · 国外 10 条</div>\n          " + header_en_html(EVENTS_SUBTITLE_EN),
            1,
        )
    if IDEAS_SUBTITLE_EN not in page and "十条想法</div>" in page:
        page = page.replace(
            "十条想法</div>",
            "十条想法</div>\n          " + header_en_html(IDEAS_SUBTITLE_EN),
            1,
        )
    if 'data-study="note"' not in page:
        intro = INTRO_RE.search(page)
        if intro and "对照今天" in intro.group(2):
            addition = (
                "<br>下面每条都有学习用英文，先读中文，再读绿色框。"
                f'<span data-study="note" style="color:#0f766e;"> {html.escape(STUDY_NOTE_EN)}</span>'
            )
            page = page[: intro.end(2)] + addition + page[intro.end(2) :]
        else:
            heading = re.search(r"<h2\b", page)
            if heading:
                page = page[: heading.start()] + study_note_html() + page[heading.start() :]
    return page


def attach_study_english(
    items: list[dict[str, str]],
    *,
    translator=None,
    cache: dict[str, str] | None = None,
    write_cache: bool = False,
) -> None:
    """Fill title_en and body_en. Uses a saved translation before calling out."""
    stored = cache if cache is not None else load_cache()
    dirty = False
    translate = translator or study_translate

    def lookup(text: str) -> str:
        nonlocal dirty
        key = normalize(text)
        if not key:
            return ""
        found = usable_english(stored.get(key, ""))
        if found:
            return found
        try:
            found = usable_english(translate(key))
        except (OSError, ValueError):
            found = ""
        if found:
            stored[key] = found
            dirty = True
        return found

    for item in items:
        if not usable_english(item.get("title_en", "")):
            title_en = lookup(item.get("title", ""))
            if title_en:
                item["title_en"] = title_en
        if usable_english(item.get("body_en", "")):
            continue
        fact = normalize(item.get("fact", ""))
        reflection_en = usable_english(item.get("reflection_en", ""))
        if fact and reflection_en:
            fact_en = lookup(fact)
            if fact_en:
                if fact_en[-1] not in ".!?":
                    fact_en += "."
                item["body_en"] = f"{fact_en} {reflection_en.lstrip()}"
                continue
        body_en = lookup(item.get("body", ""))
        if body_en:
            item["body_en"] = body_en
        elif reflection_en:
            item["body_en"] = reflection_en
    if dirty and write_cache and cache is None:
        save_cache(stored)


def text_lines(title: str, title_en: str, body: str, body_en: str) -> list[str]:
    lines = [title]
    if title_en:
        lines.append(f"EN: {title_en}")
    lines.append(body)
    if body_en:
        lines.append(f"EN: {body_en}")
        vocab = vocab_text(title + body)
        if vocab:
            lines.append(vocab)
    return lines


def _archive_strings(root: Path) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    archive = root / "archive"
    if not archive.is_dir():
        return []
    for path in sorted(archive.rglob("*.html")):
        if not (path.name.startswith("events-") or path.name.startswith("ideas-")):
            continue
        page = path.read_text(encoding="utf-8")
        for match in PAIR_RE.finditer(page):
            title = normalize(match.group("title"))
            _prefix, core = _split_index(title)
            body = normalize(match.group("body"))
            for text in (core, body):
                if text and text not in seen:
                    seen.add(text)
                    found.append(text)
    return found


def warm_cache(root: Path | None = None, *, workers: int = 4) -> int:
    """Translate archived events and ideas that do not yet have English."""
    base = root or repo_root()
    stored = load_cache(cache_path(base))
    pending = [text for text in _archive_strings(base) if normalize(text) not in stored]
    print(f"study English: {len(pending)} new strings, {len(stored)} already saved")
    if not pending:
        return 0

    def job(text: str) -> tuple[str, str]:
        return text, study_translate(text)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for text, translated in executor.map(job, pending):
            english = usable_english(translated)
            done += 1
            if english:
                stored[normalize(text)] = english
            if done % 25 == 0 or done == len(pending):
                save_cache(stored, cache_path(base))
                print(f"study English: {done}/{len(pending)}")
    save_cache(stored, cache_path(base))
    return len(pending)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fill study-English cache for sent letters.")
    parser.add_argument("--warm", action="store_true", help="Translate archived events and ideas.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.warm:
        warm_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
