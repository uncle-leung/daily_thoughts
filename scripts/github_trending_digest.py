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
import urllib.request
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


def _repo_line(repo: dict[str, str]) -> str:
    language = repo["language"] or "未标注语言"
    description = repo["description"] or "（暂无简介）"
    gained = (
        f"{repo['gained_period'] or '本时段'} +{repo['gained']} Star"
        if repo["gained"]
        else "新增 Star 未标注"
    )
    stars = f"{repo['stars']} Star" if repo["stars"] else "Star 未知"
    forks = f"{repo['forks']} Fork" if repo["forks"] else "Fork 未知"
    return (
        f"{repo['rank']}. {repo['owner']}/{repo['name']}\n"
        f"   {description}\n"
        f"   {language} · {stars} · {forks} · {gained}\n"
        f"   {repo['url']}"
    )


def render_text(sections: dict[str, list[dict[str, str]]], now: datetime | None = None) -> str:
    current = _stamp(now)
    lines = [
        subject_for(current),
        "",
        "排名来自 GitHub Trending 官方榜，按该时段新增 Star 排序。",
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
        description = html.escape(repo["description"] or "（暂无简介）")
        gained = f"+{repo['gained']}" if repo["gained"] else "—"
        rows.append(
            "<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid #e6e8eb;'
            f'font-size:14px;color:#57606a;vertical-align:top;">{html.escape(repo["rank"])}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #e6e8eb;'
            f'font-size:14px;line-height:1.45;color:#1f2328;vertical-align:top;">'
            f"{project}<div style=\"margin-top:4px;color:#57606a;\">{description}</div></td>"
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
            排名来自 GitHub Trending 官方榜，按对应时段内新增 Star 排序。点项目名可打开仓库。
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
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw": raw[:500]}
    if isinstance(parsed, dict) and str(parsed.get("success", "")).lower() == "false":
        raise RuntimeError(f"FormSubmit rejected the digest: {parsed}")
    return parsed if isinstance(parsed, dict) else {"raw": raw[:500]}


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
        print(f"sent via FormSubmit to {recipient}: {result}")
        print(
            "QQ SMTP is not configured. Add repository secret QQ_SMTP_AUTH_CODE "
            "for the HTML digest. FormSubmit's first message may be a confirmation link."
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
