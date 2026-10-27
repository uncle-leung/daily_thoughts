#!/usr/bin/env python3
"""Email ten short reflections at 09:30 and 18:30 Asia/Shanghai."""

from __future__ import annotations

import argparse
import html
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_trending_digest import (
    DEFAULT_TO,
    formsubmit_needs_activation,
    send_formsubmit,
    send_qq_smtp,
)
from ideas_bank import IDEAS

SHANGHAI = ZoneInfo("Asia/Shanghai")
CATEGORIES = ("世间", "人生", "工作", "健康", "财富", "知识")
SENTENCE_RE = re.compile(r"(?<=[。！？])")


def sentence_count(text: str) -> int:
    return len([part for part in SENTENCE_RE.split(text) if part.strip()])


def _stamp(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def slot_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    # 09:30 Shanghai is 01:30 UTC; 18:30 Shanghai is 10:30 UTC.
    return "09:30" if current.astimezone(ZoneInfo("UTC")).hour < 6 else "18:30"


def subject_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    return f"每日想法 · {current.strftime('%Y-%m-%d')} {slot_for(current)}（上海）"


def _sample(day: int, offset: int, excluded: set[str], count: int) -> list[dict[str, str]]:
    rng = random.Random(day * 10 + offset)
    by_category: dict[str, list[dict[str, str]]] = {category: [] for category in CATEGORIES}
    for idea in IDEAS:
        if idea["title"] not in excluded:
            by_category[idea["category"]].append(idea)
    order = list(CATEGORIES)
    rng.shuffle(order)
    queues: dict[str, list[dict[str, str]]] = {}
    for category in CATEGORIES:
        pool = list(by_category[category])
        rng.shuffle(pool)
        queues[category] = pool
    picked: list[dict[str, str]] = []
    while len(picked) < count and any(queues.values()):
        for category in order:
            queue = queues[category]
            if not queue:
                continue
            picked.append(queue.pop(0))
            if len(picked) == count:
                break
    return picked


def select_ideas(now: datetime | None = None, count: int = 10) -> list[dict[str, str]]:
    """Pick a spread of categories. The same day's evening letter uses other titles."""
    if count < 1:
        return []
    current = _stamp(now)
    day = current.date().toordinal()
    morning = _sample(day, 0, set(), count)
    if slot_for(current) == "09:30":
        return morning
    return _sample(day, 1, {idea["title"] for idea in morning}, count)


def render_text(ideas: list[dict[str, str]], now: datetime | None = None) -> str:
    current = _stamp(now)
    lines = [
        subject_for(current),
        "",
        "十条想法，涵盖世事、人生、工作、健康、财富和知识。每条三四句话。",
        f"整理时间：{current.strftime('%Y-%m-%d %H:%M')} 上海时间",
        "",
    ]
    for index, idea in enumerate(ideas, start=1):
        lines.append(f"{index}. [{idea['category']}] {idea['title']}")
        lines.append(idea["body"])
        lines.append("")
    lines.append("每天 09:30 和 18:30（上海时间）自动发送。")
    return "\n".join(lines).strip() + "\n"


def render_html(ideas: list[dict[str, str]], now: datetime | None = None) -> str:
    current = _stamp(now)
    blocks: list[str] = []
    for index, idea in enumerate(ideas, start=1):
        blocks.append(
            "<div style=\"padding:16px 0;border-bottom:1px solid #e6e8eb;\">"
            f"<div style=\"font-size:12px;letter-spacing:0.04em;color:#57606a;\">"
            f"{html.escape(idea['category'])}</div>"
            f"<div style=\"margin-top:4px;font-size:18px;font-weight:700;color:#1f2328;\">"
            f"{index}. {html.escape(idea['title'])}</div>"
            f"<p style=\"margin:8px 0 0;font-size:15px;line-height:1.7;color:#24292f;\">"
            f"{html.escape(idea['body'])}</p>"
            "</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{html.escape(subject_for(current))}</title></head>
<body style="margin:0;padding:0;background:#f6f8fa;color:#1f2328;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fa;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;">
        <tr><td style="background:#1f2328;color:#ffffff;padding:22px 24px;border-radius:12px 12px 0 0;">
          <div style="font-size:13px;letter-spacing:0.04em;color:#c9d1d9;">DAILY THOUGHTS</div>
          <div style="font-size:22px;font-weight:700;margin-top:6px;">十条想法</div>
          <div style="font-size:13px;color:#c9d1d9;margin-top:8px;">
            {html.escape(current.strftime("%Y-%m-%d %H:%M"))} 上海时间 · 每天 09:30 与 18:30
          </div>
        </td></tr>
        <tr><td style="background:#ffffff;padding:8px 24px 22px;border:1px solid #d0d7de;border-top:0;border-radius:0 0 12px 12px;">
          <p style="margin:16px 0 0;color:#57606a;font-size:14px;line-height:1.6;">
            世事、人生、工作、健康、财富和知识。每条三四句话，供你挑一件用在今天。
          </p>
          {''.join(blocks)}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Email ten daily reflections.")
    parser.add_argument("--send", action="store_true", help="Deliver the letter by email.")
    parser.add_argument("--html-out", default="", help="Write the HTML letter to this path.")
    parser.add_argument("--text-out", default="", help="Write the plain-text letter to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _stamp()
    ideas = select_ideas(now)
    subject = subject_for(now)
    text = render_text(ideas, now)
    html_body = render_html(ideas, now)
    print(f"subject: {subject}")
    print("titles: " + "；".join(idea["title"] for idea in ideas))
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
        except Exception as exc:  # noqa: BLE001
            print(f"QQ SMTP send failed: {exc}", file=sys.stderr)
            return 3
        print(f"sent via QQ SMTP to {recipient}")
        return 0

    if os.environ.get("DIGEST_FALLBACK", "").strip().lower() == "formsubmit":
        try:
            result = send_formsubmit(
                recipient=recipient,
                subject=subject,
                text=text,
                sender_name="每日想法",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"FormSubmit send failed: {exc}", file=sys.stderr)
            return 3
        if formsubmit_needs_activation(result):
            print(f"FormSubmit sent an activation email to {recipient}.")
            return 0
        print(f"sent via FormSubmit to {recipient}: {result}")
        return 0

    print(
        "QQ_SMTP_AUTH_CODE is not set. Refusing to send. "
        "Export the QQ mailbox authorization code, or set DIGEST_FALLBACK=formsubmit.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
