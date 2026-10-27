#!/usr/bin/env python3
"""Build a GitHub Trending digest (daily, weekly, monthly) and email it.

Data comes from the public GitHub Trending pages. Mail goes out through
QQ SMTP when QQ_SMTP_AUTH_CODE is set. If that secret is missing and
DIGEST_FALLBACK=formsubmit, the plain-text digest is handed to FormSubmit
so delivery can start before an authorization code exists.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
TRENDING_URL = "https://github.com/trending?since={period}&spoken_language_code={lang}"
USER_AGENT = (
    "Mozilla/5.0 (compatible; daily-thoughts-trending-digest/1.0; "
    "+https://github.com/uncle-leung/daily_thoughts)"
)
DEFAULT_TO = "fisherleung27@qq.com"
PERIODS = (
    ("daily", "今日", "今天新增 Star"),
    ("weekly", "本周", "本周新增 Star"),
    ("monthly", "本月", "本月新增 Star"),
)
GAINED_PERIOD = {
    "today": "今日",
    "this week": "本周",
    "this month": "本月",
}
ARTICLE_RE = re.compile(r'<article class="Box-row">(.*?)</article>', re.S)
H2_HREF_RE = re.compile(
    r'<h2[^>]*>.*?<a[^>]+href="/([^"/]+)/([^"/]+)"',
    re.S,
)
DESC_RE = re.compile(r'<p[^>]*class="[^"]*color-fg-muted[^"]*"[^>]*>(.*?)</p>', re.S)
LANG_RE = re.compile(r'itemprop="programmingLanguage">([^<]+)')
STAR_RE = re.compile(
    r'href="/[^"]+/stargazers"[^>]*>.*?octicon-star.*?</svg>\s*([0-9][0-9,]*)',
    re.S,
)
FORK_RE = re.compile(
    r'href="/[^"]+/forks"[^>]*>.*?octicon-repo-forked.*?</svg>\s*([0-9][0-9,]*)',
    re.S,
)
GAINED_RE = re.compile(
    r'([0-9][0-9,]*)\s+stars\s+(today|this week|this month)',
    re.I,
)
TAG_RE = re.compile(r"<[^>]+>")
FENCE_RE = re.compile(r"```.*?```", re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
BADGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
URL_RE = re.compile(r"https?://\S+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
SKIP_SENTENCE_RE = re.compile(
    r"\b(table of contents|license|changelog|contributing|installation|installing|"
    r"getting started|prerequisite|build status|npm install|pip install|docker pull|"
    r"yarn add|pnpm add|cargo install|go install)\b",
    re.I,
)
README_FILES = ("README.md", "readme.md", "README.rst", "README.txt", "README")


def fetch_html(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def _clean(value: str) -> str:
    text = TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_trending_html(page: str, limit: int = 15) -> list[dict[str, str]]:
    repos: list[dict[str, str]] = []
    for article in ARTICLE_RE.findall(page):
        href = H2_HREF_RE.search(article)
        if not href:
            continue
        owner, name = href.group(1), href.group(2)
        description_match = DESC_RE.search(article)
        language_match = LANG_RE.search(article)
        stars_match = STAR_RE.search(article)
        forks_match = FORK_RE.search(article)
        gained_match = GAINED_RE.search(article)
        repos.append(
            {
                "rank": str(len(repos) + 1),
                "owner": owner,
                "name": name,
                "url": f"https://github.com/{owner}/{name}",
                "description": _clean(description_match.group(1)) if description_match else "",
                "language": _clean(language_match.group(1)) if language_match else "",
                "stars": stars_match.group(1) if stars_match else "",
                "forks": forks_match.group(1) if forks_match else "",
                "gained": gained_match.group(1) if gained_match else "",
                "gained_period": GAINED_PERIOD.get(
                    gained_match.group(2).lower(), ""
                )
                if gained_match
                else "",
            }
        )
        if len(repos) >= limit:
            break
    return repos


def cjk_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha() or "\u4e00" <= char <= "\u9fff"]
    if not letters:
        return 0.0
    cjk = sum(1 for char in letters if "\u4e00" <= char <= "\u9fff")
    return cjk / len(letters)


def readme_plaintext(markdown: str) -> str:
    text = FENCE_RE.sub(" ", markdown)
    text = HTML_COMMENT_RE.sub(" ", text)
    text = BADGE_RE.sub(" ", text)
    text = MD_LINK_RE.sub(r"\1", text)
    text = URL_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = text.replace("**", " ").replace("__", " ").replace("`", " ")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = EMOJI_RE.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？])|(?<=[.!?])\s+", text)
    return [part.strip(" -–—|") for part in parts if part.strip(" -–—|")]


def _usable_sentence(sentence: str, minimum: int) -> bool:
    sentence = sentence.strip()
    if len(sentence) < minimum or len(sentence) > 320:
        return False
    if SKIP_SENTENCE_RE.search(sentence):
        return False
    letters = sum(1 for char in sentence if char.isalpha() or "\u4e00" <= char <= "\u9fff")
    return letters >= 8 and letters / len(sentence) > 0.4


def _overlaps(left: str, right: str) -> bool:
    a = re.sub(r"\W+", "", left).lower()
    b = re.sub(r"\W+", "", right).lower()
    if not a or not b:
        return False
    return a in b or b in a


NAV_LINE_RE = re.compile(
    r"(简体中文|繁体中文|日本語|한국어|table of contents|changelog|installation|license|目录|安装|许可证)",
    re.I,
)
DATE_LINE_RE = re.compile(r"\[20\d{2}|^20\d{2}[-/.]")
GLOSSARY = (
    (re.compile(r"\bmulti-?agents?\b", re.I), "多智能体"),
    (re.compile(r"\bcoding agents?\b", re.I), "编程智能体"),
    (re.compile(r"\bagentic\b", re.I), "智能体"),
    (re.compile(r"\bagents?\b", re.I), "智能体"),
    (re.compile(r"\bLLMs?\b", re.I), "大语言模型"),
    (re.compile(r"\blarge language models?\b", re.I), "大语言模型"),
    (re.compile(r"\bharness(?:es)?\b", re.I), "智能体运行框架"),
    (re.compile(r"\bopen[- ]source\b", re.I), "开源"),
    (re.compile(r"\bframeworks?\b", re.I), "框架"),
    (re.compile(r"\bworkflows?\b", re.I), "工作流"),
    (re.compile(r"\bplugins?\b", re.I), "插件"),
    (re.compile(r"\bskills?\b", re.I), "技能"),
    (re.compile(r"\blocal-first\b", re.I), "本地优先"),
    (re.compile(r"\bvoice cloning\b", re.I), "声音克隆"),
)
TERM_FIXES = (
    ("智能体马具", "智能体框架"),
    ("代理框架", "智能体框架"),
    ("人工智能代理", "智能体"),
    ("现实世界贸易公司", "真实交易公司"),
    ("法学硕士", "大语言模型"),
    ("特工安全带", "智能体运行框架"),
    ("编码代理", "编程智能体"),
    ("代理商", "智能体"),
    ("代理人", "智能体"),
    ("多代理", "多智能体"),
    ("代理 IDE", "智能体 IDE"),
    ("代理聊天", "智能体聊天"),
    ("您的代理", "你的智能体"),
    ("你的代理", "你的智能体"),
    ("代理变成", "智能体变成"),
    ("特工", "智能体"),
    ("安全带", "工具"),
)


def readme_lines(markdown: str) -> list[str]:
    text = FENCE_RE.sub("\n", markdown)
    text = HTML_COMMENT_RE.sub("\n", text)
    text = BADGE_RE.sub(" ", text)
    text = MD_LINK_RE.sub(r"\1", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^#{1,6}\s*", "", raw.strip())
        line = line.replace("**", "").replace("__", "").replace("`", "")
        line = EMOJI_RE.sub(" ", line)
        line = TAG_RE.sub(" ", line)
        line = URL_RE.sub(" ", line)
        line = html.unescape(line)
        line = re.sub(r"\s+", " ", line).strip(" |-–—")
        if line:
            lines.append(line)
    return lines


def _prose_line(line: str) -> bool:
    if len(line) < 24:
        return False
    if line.count("|") >= 2 or line.count("·") >= 2 or line.count("•") >= 2:
        return False
    if DATE_LINE_RE.search(line) or SKIP_SENTENCE_RE.search(line):
        return False
    if NAV_LINE_RE.search(line) and len(line) < 90:
        return False
    letters = sum(1 for char in line if char.isalpha() or "\u4e00" <= char <= "\u9fff")
    return letters >= 12 and letters / len(line) > 0.55


def _clip_sentence(sentence: str, limit: int = 180) -> str:
    sentence = sentence.strip()
    if len(sentence) <= limit:
        return sentence
    cut = max(sentence.rfind(" ", 40, limit), sentence.rfind("，", 20, limit))
    if cut < 20:
        cut = limit
    return sentence[:cut].rstrip(" ,;:，；、")


def _apply_glossary(text: str) -> str:
    if cjk_ratio(text) >= 0.35:
        return text
    for pattern, replacement in GLOSSARY:
        text = pattern.sub(replacement, text)
    return text


def _fix_terms(text: str) -> str:
    for source, target in TERM_FIXES:
        text = text.replace(source, target)
    return text


def _sentence_score(sentence: str) -> int:
    lowered = sentence.lower()
    if sentence.endswith("?") or sentence.endswith("？"):
        return -5
    if any(word in lowered for word in ("thank", "released", "looking forward", "star history", "install the")):
        return -4
    score = 0
    if re.search(r"\b(is|are)\b|是一|用于|提供", sentence):
        score += 5
    if re.search(r"\b(that|which|lets|helps|turns|mirrors)\b|可以|适合|用来", sentence):
        score += 2
    if 50 <= len(sentence) <= 220:
        score += 1
    return score


def _candidate_sentences(description: str, readme: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for raw in readme.splitlines():
        if not raw.strip():
            flush()
            continue
        if raw.lstrip().startswith(">"):
            flush()
            continue
        line = readme_lines(raw + "\n")
        if not line or not _prose_line(line[0]):
            flush()
            continue
        current.append(line[0])
    flush()
    sentences: list[str] = []
    for paragraph in paragraphs:
        for sentence in split_sentences(paragraph) or [paragraph]:
            sentence = _clip_sentence(sentence, 220).strip().rstrip(".")
            if _usable_sentence(sentence, 24):
                sentences.append(sentence)
    return sentences


DEFINITION_RE = re.compile(
    r"\bis (an?|the)\b|是一|旨在|用于|helps you|lets you|turns your",
    re.I,
)


def summary_sentences(description: str, readme: str) -> list[str]:
    """Lead with the GitHub tagline, then one definition sentence from the README."""
    description = EMOJI_RE.sub(" ", description)
    description = re.sub(r"\s+", " ", description).strip()
    picked: list[str] = []
    description_sentences = [
        sentence.strip().rstrip(".")
        for sentence in split_sentences(description)
        if sentence.strip()
    ]
    chinese_sentences = [sentence for sentence in description_sentences if cjk_ratio(sentence) >= 0.35]
    if chinese_sentences:
        picked.extend(chinese_sentences[:2])
    elif _usable_sentence(description, 12):
        picked.append(description.rstrip("."))
    intro = "\n".join(line for line in readme.splitlines()[:180] if "<img" not in line.lower() and "<a " not in line.lower())
    for sentence in _candidate_sentences("", intro):
        if re.search(r"\b(npx|npm|pip3?|docker|cargo|yarn|pnpm|license|licensed)\b", sentence, re.I):
            continue
        if sentence.lower().startswith("each "):
            continue
        if cjk_ratio(description) >= 0.35 and cjk_ratio(sentence) < 0.2:
            continue
        if not DEFINITION_RE.search(sentence):
            continue
        if any(_overlaps(sentence, existing) for existing in picked):
            continue
        picked.append(sentence.rstrip("."))
        if len(picked) == 3:
            break
        break
    cleaned: list[str] = []
    for sentence in picked[:3]:
        sentence = sentence.strip()
        if sentence and sentence[-1] not in "。！？.!?":
            sentence += "."
        cleaned.append(sentence)
    return cleaned


def draft_summary(description: str, readme: str) -> str:
    return " ".join(summary_sentences(description, readme))


def shape_summary(text: str) -> str:
    text = _fix_terms(re.sub(r"\s+", " ", text).strip())
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[。！？])", text) if part.strip()]
    if len(parts) == 1 and text.count("，") >= 4:
        parts = [clause.strip(" ，,;；") for clause in re.split(r"[，,]", text) if len(clause.strip()) >= 4][:3]
    shaped: list[str] = []
    for part in parts[:3]:
        part = part.strip().rstrip("。！？.!?，,")
        if part:
            shaped.append(part + "。")
    return "".join(shaped)


def parse_gtx_payload(payload: object) -> str:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return ""
    parts: list[str] = []
    for item in payload[0]:
        if isinstance(item, list) and item and isinstance(item[0], str):
            parts.append(item[0])
    return "".join(parts)


def _translate_chunk(chunk: str) -> str:
    url = (
        "https://translate.googleapis.com/translate_a/single?client=gtx"
        "&sl=auto&tl=zh-CN&dt=t&q=" + urllib.parse.quote(chunk)
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    translated = parse_gtx_payload(payload).strip()
    if not translated:
        raise RuntimeError("empty translation")
    return translated


def translate_to_zh(text: str) -> str:
    text = text.strip()
    if not text or cjk_ratio(text) >= 0.35:
        return text
    text = re.sub(r"\bharness(?:es)?\b", "framework", text, flags=re.I)
    text = re.sub(r"\bLLMs?\b", "large language models", text)
    pieces: list[str] = []
    rest = text
    while rest:
        chunk = rest[:700]
        if len(rest) > 700:
            cut = max(chunk.rfind("。"), chunk.rfind(". "), chunk.rfind("，"))
            if cut > 180:
                chunk = rest[: cut + 1]
        rest = rest[len(chunk) :].strip()
        pieces.append(_translate_chunk(chunk))
    return "".join(pieces).strip()


def limit_to_three(text: str) -> str:
    parts = split_sentences(text)
    if len(parts) <= 3:
        return text.strip()
    joiner = "" if cjk_ratio(text) >= 0.35 else " "
    return joiner.join(parts[:3]).strip()


def _fetch_bytes(url: str, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(30000).decode("utf-8", errors="replace")


def fetch_readme(owner: str, name: str) -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        try:
            body = _fetch_bytes(
                f"https://api.github.com/repos/{owner}/{name}/readme",
                headers={
                    "Accept": "application/vnd.github.raw",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if not body.lstrip().startswith("{"):
                return body
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            pass
    for filename in README_FILES:
        url = f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/{urllib.parse.quote(filename)}"
        try:
            return _fetch_bytes(url)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            continue
    return ""


def _collapse_short_bits(bits: list[str]) -> str:
    bodies = [bit.strip().rstrip("。！？.!?") for bit in bits if bit.strip()]
    if len(bodies) >= 2 and max(len(body) for body in bodies) <= 24:
        return "，".join(bodies) + "。"
    return "".join(body + "。" for body in bodies)


def summarize_repo(repo: dict[str, str]) -> str:
    readme = ""
    try:
        readme = fetch_readme(repo["owner"], repo["name"])
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        readme = ""
    sentences = summary_sentences(repo.get("description", ""), readme)
    if not sentences:
        sentences = [repo.get("description") or f"{repo['owner']}/{repo['name']}。"]
    rendered: list[str] = []
    for index, sentence in enumerate(sentences):
        try:
            chinese = translate_to_zh(sentence)
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, RuntimeError):
            chinese = sentence
        bits = [bit for bit in split_sentences(shape_summary(chinese)) if bit.strip()]
        if index == 0 and len(sentences) > 1 and len(bits) > 1 and max(len(bit) for bit in bits) <= 24:
            rendered.append(_collapse_short_bits(bits))
        else:
            rendered.extend(bits[: 3 - len(rendered)])
        if len(rendered) >= 3:
            break
    return "".join(rendered[:3])


def attach_summaries(sections: dict[str, list[dict[str, str]]]) -> None:
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key in ("daily", "weekly", "monthly", "daily_zh"):
        for repo in sections.get(key) or []:
            ident = (repo["owner"], repo["name"])
            if ident in seen:
                continue
            seen.add(ident)
            unique.append(repo)
    summaries: dict[tuple[str, str], str] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(summarize_repo, repo): repo for repo in unique}
        for future in as_completed(futures):
            repo = futures[future]
            ident = (repo["owner"], repo["name"])
            try:
                summaries[ident] = future.result()
            except Exception as exc:  # noqa: BLE001
                print(f"summary failed for {ident[0]}/{ident[1]}: {exc}", file=sys.stderr)
                summaries[ident] = repo.get("description") or "暂无足够资料概括这个仓库。"
    for key in ("daily", "weekly", "monthly", "daily_zh"):
        for repo in sections.get(key) or []:
            repo["summary"] = summaries.get((repo["owner"], repo["name"]), repo.get("description", ""))


def collect(limit: int, include_chinese_daily: bool) -> dict[str, list[dict[str, str]]]:
    sections: dict[str, list[dict[str, str]]] = {}
    errors: list[str] = []
    for period, _title, _gain_label in PERIODS:
        url = TRENDING_URL.format(period=period, lang="")
        try:
            sections[period] = parse_trending_html(fetch_html(url), limit=limit)
        except RuntimeError as exc:
            errors.append(str(exc))
            sections[period] = []
        if not sections[period] and period not in {item.split()[0] for item in errors}:
            errors.append(f"{period}: trending page returned no repositories")
    if include_chinese_daily:
        url = TRENDING_URL.format(period="daily", lang="zh")
        try:
            sections["daily_zh"] = parse_trending_html(fetch_html(url), limit=limit)
        except RuntimeError as exc:
            errors.append(str(exc))
            sections["daily_zh"] = []
    if errors and not any(sections.values()):
        raise RuntimeError("; ".join(errors))
    sections["_errors"] = [{"message": item} for item in errors]  # type: ignore[assignment]
    return sections


def _stamp(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def subject_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    # 09:00 Shanghai is 01:00 UTC; 18:00 Shanghai is 10:00 UTC.
    # Use UTC so a delayed runner still labels the slot that fired.
    slot = "09:00" if current.astimezone(ZoneInfo("UTC")).hour < 6 else "18:00"
    return f"GitHub 热门项目 · {current.strftime('%Y-%m-%d')} {slot}（上海）"


def _blurb(repo: dict[str, str]) -> str:
    return repo.get("summary") or repo.get("description") or "（暂无简介）"


def _repo_line(repo: dict[str, str]) -> str:
    language = repo["language"] or "未标注语言"
    gained = (
        f"{repo['gained_period'] or '本时段'} +{repo['gained']} Star"
        if repo["gained"]
        else "新增 Star 未标注"
    )
    stars = f"{repo['stars']} Star" if repo["stars"] else "Star 未知"
    forks = f"{repo['forks']} Fork" if repo["forks"] else "Fork 未知"
    return (
        f"{repo['rank']}. {repo['owner']}/{repo['name']}\n"
        f"   {_blurb(repo)}\n"
        f"   {language} · {stars} · {forks} · {gained}\n"
        f"   {repo['url']}"
    )


def render_text(sections: dict[str, list[dict[str, str]]], now: datetime | None = None) -> str:
    current = _stamp(now)
    lines = [
        subject_for(current),
        "",
        "排名来自 GitHub Trending 官方榜，按该时段新增 Star 排序。每条用两三句话说明这个项目是做什么的。",
        f"整理时间：{current.strftime('%Y-%m-%d %H:%M')} 上海时间",
        "",
    ]
    catalog = [
        ("daily", "今日热门"),
        ("weekly", "本周热门"),
        ("monthly", "本月热门"),
        ("daily_zh", "中文社区今日热门"),
    ]
    for key, title in catalog:
        repos = sections.get(key) or []
        if key == "daily_zh" and not repos:
            continue
        lines.append(f"## {title}")
        lines.append("")
        if not repos:
            lines.append("这一榜暂时没有取到数据。")
            lines.append("")
            continue
        for repo in repos:
            lines.append(_repo_line(repo))
            lines.append("")
    errors = sections.get("_errors") or []
    if errors:
        lines.append("抓取时有部分页面失败，上面只包含成功的榜单。")
        lines.append("")
    lines.append("每天 09:00 和 18:00（上海时间）自动发送。")
    lines.append("来源：https://github.com/trending")
    return "\n".join(lines).strip() + "\n"


def _cell(value: str, extra: str = "") -> str:
    return (
        f'<td style="padding:8px 10px;border-bottom:1px solid #e6e8eb;'
        f'font-size:14px;line-height:1.45;color:#1f2328;vertical-align:top;{extra}">'
        f"{html.escape(value)}</td>"
    )


def _repo_rows(repos: list[dict[str, str]]) -> str:
    rows: list[str] = []
    for repo in repos:
        project = (
            f'<a href="{html.escape(repo["url"], quote=True)}" '
            f'style="color:#0969da;text-decoration:none;font-weight:600;">'
            f'{html.escape(repo["owner"])}/{html.escape(repo["name"])}</a>'
        )
        blurb = html.escape(_blurb(repo))
        gained = f"+{repo['gained']}" if repo["gained"] else "—"
        rows.append(
            "<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid #e6e8eb;'
            f'font-size:14px;color:#57606a;vertical-align:top;">{html.escape(repo["rank"])}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #e6e8eb;'
            f'font-size:14px;line-height:1.6;color:#1f2328;vertical-align:top;">'
            f"{project}<div style=\"margin-top:6px;color:#24292f;\">{blurb}</div></td>"
            + _cell(repo["language"] or "—")
            + _cell(repo["stars"] or "—", "text-align:right;white-space:nowrap;")
            + _cell(repo["forks"] or "—", "text-align:right;white-space:nowrap;")
            + _cell(gained, "text-align:right;white-space:nowrap;color:#1a7f37;font-weight:600;")
            + "</tr>"
        )
    return "".join(rows)


def _section_table(title: str, gain_label: str, repos: list[dict[str, str]]) -> str:
    if not repos:
        body = (
            '<p style="margin:0 0 28px;color:#57606a;">这一榜暂时没有取到数据。</p>'
        )
    else:
        body = f"""
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="border-collapse:collapse;margin:0 0 28px;background:#ffffff;">
          <thead>
            <tr>
              <th align="left" style="padding:8px 10px;border-bottom:2px solid #d0d7de;color:#57606a;font-size:12px;">#</th>
              <th align="left" style="padding:8px 10px;border-bottom:2px solid #d0d7de;color:#57606a;font-size:12px;">项目</th>
              <th align="left" style="padding:8px 10px;border-bottom:2px solid #d0d7de;color:#57606a;font-size:12px;">语言</th>
              <th align="right" style="padding:8px 10px;border-bottom:2px solid #d0d7de;color:#57606a;font-size:12px;">Star</th>
              <th align="right" style="padding:8px 10px;border-bottom:2px solid #d0d7de;color:#57606a;font-size:12px;">Fork</th>
              <th align="right" style="padding:8px 10px;border-bottom:2px solid #d0d7de;color:#57606a;font-size:12px;">{html.escape(gain_label)}</th>
            </tr>
          </thead>
          <tbody>{_repo_rows(repos)}</tbody>
        </table>
        """
    return (
        f'<h2 style="margin:0 0 12px;font-size:18px;color:#1f2328;">{html.escape(title)}</h2>'
        + body
    )


def render_html(sections: dict[str, list[dict[str, str]]], now: datetime | None = None) -> str:
    current = _stamp(now)
    blocks = [
        _section_table("今日热门", "今天新增", sections.get("daily") or []),
        _section_table("本周热门", "本周新增", sections.get("weekly") or []),
        _section_table("本月热门", "本月新增", sections.get("monthly") or []),
    ]
    chinese = sections.get("daily_zh") or []
    if chinese:
        blocks.append(_section_table("中文社区今日热门", "今天新增", chinese))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{html.escape(subject_for(current))}</title></head>
<body style="margin:0;padding:0;background:#f6f8fa;color:#1f2328;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fa;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:760px;">
        <tr><td style="background:#1f2328;color:#ffffff;padding:22px 24px;border-radius:12px 12px 0 0;">
          <div style="font-size:13px;letter-spacing:0.04em;color:#c9d1d9;">GITHUB TRENDING</div>
          <div style="font-size:22px;font-weight:700;margin-top:6px;">热门项目 · 日 / 周 / 月</div>
          <div style="font-size:13px;color:#c9d1d9;margin-top:8px;">
            {html.escape(current.strftime("%Y-%m-%d %H:%M"))} 上海时间 · 每天 09:00 与 18:00
          </div>
        </td></tr>
        <tr><td style="background:#ffffff;padding:22px 24px;border:1px solid #d0d7de;border-top:0;border-radius:0 0 12px 12px;">
          <p style="margin:0 0 22px;color:#57606a;font-size:14px;line-height:1.6;">
            排名来自 GitHub Trending 官方榜，按对应时段内新增 Star 排序。每条下面用两三句话说明这个项目是做什么的。
          </p>
          {''.join(blocks)}
          <p style="margin:8px 0 0;color:#8b949e;font-size:12px;line-height:1.5;">
            来源 <a href="https://github.com/trending" style="color:#0969da;">github.com/trending</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def send_qq_smtp(
    *,
    user: str,
    auth_code: str,
    recipient: str,
    subject: str,
    text: str,
    html_body: str,
    host: str = "smtp.qq.com",
    port: int = 465,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = user
    message["To"] = recipient
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, timeout=40, context=context) as smtp:
        smtp.login(user, auth_code)
        smtp.send_message(message)


def formsubmit_needs_activation(payload: dict[str, object]) -> bool:
    message = str(payload.get("message", ""))
    return str(payload.get("success", "")).lower() == "false" and "activat" in message.lower()


def send_formsubmit(*, recipient: str, subject: str, text: str) -> dict[str, object]:
    payload = {
        "name": "GitHub Trending Digest",
        "_subject": subject,
        "_template": "box",
        "_captcha": "false",
        "message": text,
    }
    request = urllib.request.Request(
        f"https://formsubmit.co/ajax/{recipient}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": "https://github.com/uncle-leung/daily_thoughts",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw": raw[:500]}
    if not isinstance(parsed, dict):
        return {"raw": raw[:500]}
    if str(parsed.get("success", "")).lower() == "false" and not formsubmit_needs_activation(parsed):
        raise RuntimeError(f"FormSubmit rejected the digest: {parsed}")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Email the GitHub Trending digest.")
    parser.add_argument("--send", action="store_true", help="Deliver the digest by email.")
    parser.add_argument("--limit", type=int, default=15, help="Repositories per board.")
    parser.add_argument(
        "--skip-chinese",
        action="store_true",
        help="Omit the Chinese-language daily board.",
    )
    parser.add_argument(
        "--skip-summaries",
        action="store_true",
        help="Keep the one-line GitHub tagline instead of a short summary.",
    )
    parser.add_argument(
        "--html-out",
        default="",
        help="Write the HTML digest to this path.",
    )
    parser.add_argument(
        "--text-out",
        default="",
        help="Write the plain-text digest to this path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit < 1 or args.limit > 25:
        print("limit must be between 1 and 25", file=sys.stderr)
        return 2
    try:
        sections = collect(limit=args.limit, include_chinese_daily=not args.skip_chinese)
    except RuntimeError as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 2

    if not args.skip_summaries:
        attach_summaries(sections)

    now = _stamp()
    subject = subject_for(now)
    text = render_text(sections, now)
    html_body = render_html(sections, now)
    counts = {
        key: len(sections.get(key) or [])
        for key in ("daily", "weekly", "monthly", "daily_zh")
    }
    print(f"subject: {subject}")
    print("counts: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
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

    recipient = os.environ.get("DIGEST_TO", DEFAULT_TO).strip() or DEFAULT_TO
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
        except Exception as exc:  # noqa: BLE001 - report SMTP failure without a traceback dump
            print(f"QQ SMTP send failed: {exc}", file=sys.stderr)
            return 3
        print(f"sent via QQ SMTP to {recipient}")
        return 0

    if os.environ.get("DIGEST_FALLBACK", "").strip().lower() == "formsubmit":
        try:
            result = send_formsubmit(recipient=recipient, subject=subject, text=text)
        except Exception as exc:  # noqa: BLE001
            print(f"FormSubmit send failed: {exc}", file=sys.stderr)
            return 3
        if formsubmit_needs_activation(result):
            print(
                f"FormSubmit sent an activation email to {recipient}. "
                "Open it and click Activate Form. The ranking digest is delivered on the next run."
            )
            return 0
        print(f"sent via FormSubmit to {recipient}: {result}")
        print(
            "QQ SMTP is not configured. Add repository secret QQ_SMTP_AUTH_CODE "
            "for the HTML digest."
        )
        return 0

    print(
        "QQ_SMTP_AUTH_CODE is not set. Refusing to send. "
        "Export the QQ mailbox authorization code, or set DIGEST_FALLBACK=formsubmit.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
