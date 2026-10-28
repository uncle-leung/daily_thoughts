#!/usr/bin/env python3
"""Keep a public page of letters that were actually sent."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
KIND_TITLE = {
    "trending": "GitHub 热门项目",
    "events": "国内外大事",
    "ideas": "每日想法",
}
STEM_RE = re.compile(r"^(trending|events|ideas)-(\d{4})$")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _day_key(when: datetime) -> str:
    current = when if when.tzinfo else when.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI).date().isoformat()


def _slot_text(hhmm: str) -> str:
    return f"{hhmm[:2]}:{hhmm[2:]}"


def _parse_sent_at(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _html_title(page: str) -> str:
    match = TITLE_RE.search(page)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def remember_letter(
    root: Path,
    kind: str,
    slot: str,
    sent_at: datetime,
    subject: str,
    html_body: str,
    text: str,
) -> None:
    """Store one sent letter. The page is rebuilt from this folder and mail-state."""
    if kind not in KIND_TITLE or not re.fullmatch(r"\d{2}:\d{2}", slot):
        raise ValueError(f"unknown letter slot {kind} {slot}")
    day = _day_key(sent_at)
    folder = root / "archive" / day
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{kind}-{slot.replace(':', '')}"
    (folder / f"{stem}.html").write_text(html_body, encoding="utf-8")
    (folder / f"{stem}.txt").write_text(text, encoding="utf-8")
    meta = {
        "kind": kind,
        "slot": slot,
        "subject": subject.strip(),
        "sentAt": sent_at.astimezone(SHANGHAI).isoformat(),
    }
    (folder / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish_sent_letter(kind: str, sent_at: datetime, slot: str, subject: str, html_body: str, text: str) -> None:
    try:
        root = repo_root()
        remember_letter(root, kind, slot, sent_at, subject, html_body, text)
        rebuild_site(root, sent_at)
    except OSError as exc:
        print(f"site update failed: {exc}")
    else:
        print(f"site updated for {kind} {slot}")


def _blank(kind: str, slot: str) -> dict[str, str]:
    return {
        "kind": kind,
        "slot": slot,
        "subject": "",
        "sentAt": "",
        "html": "",
        "text": "",
    }


def collect_day(root: Path, day: str) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    state = root / "mail-state" / day
    if state.is_dir():
        for path in sorted(state.iterdir()):
            parsed = STEM_RE.match(path.name)
            if parsed is None or not path.is_file():
                continue
            kind, hhmm = parsed.group(1), parsed.group(2)
            row = _blank(kind, _slot_text(hhmm))
            sent = _parse_sent_at(path.read_text(encoding="utf-8"))
            if sent is not None:
                row["sentAt"] = sent.isoformat()
            found[path.name] = row
    folder = root / "archive" / day
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            parsed = STEM_RE.match(path.stem)
            if parsed is None:
                continue
            kind, hhmm = parsed.group(1), parsed.group(2)
            row = found.get(path.stem) or _blank(kind, _slot_text(hhmm))
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
            if isinstance(meta, dict):
                subject = str(meta.get("subject") or "").strip()
                sent = _parse_sent_at(str(meta.get("sentAt") or ""))
                if subject:
                    row["subject"] = subject
                if sent is not None:
                    row["sentAt"] = sent.isoformat()
            html_path = path.with_suffix(".html")
            text_path = path.with_suffix(".txt")
            if html_path.is_file():
                row["html"] = html_path.read_text(encoding="utf-8")
                if not row["subject"]:
                    row["subject"] = _html_title(row["html"])
            elif text_path.is_file():
                row["text"] = text_path.read_text(encoding="utf-8")
            found[path.stem] = row
    rows = list(found.values())
    rows.sort(key=lambda item: (item["sentAt"] or "9999", item["kind"], item["slot"]))
    return rows


def _clock(sent_at: str) -> str:
    parsed = _parse_sent_at(sent_at)
    if parsed is None:
        return ""
    return parsed.strftime("%H:%M")


def _letter_html(day: str, row: dict[str, str]) -> str:
    title = KIND_TITLE[row["kind"]]
    stem = f"{row['kind']}-{row['slot'].replace(':', '')}"
    clock = _clock(row["sentAt"])
    when = f"{clock} 发出" if clock else "已发出"
    subject = row["subject"]
    head = f"<h2 id=\"letter-{stem}\">{html.escape(title)}</h2>"
    meta = f"<p class=\"meta\">{html.escape(when)}"
    if subject:
        meta += f" · {html.escape(subject)}"
    meta += "</p>"
    if row["html"]:
        href = f"letters/{day}/{stem}.html"
        frame = (
            f"<iframe title=\"{html.escape(title)}\" src=\"{href}\" "
            "onload=\"fitLetter(this)\"></iframe>"
            f"<p class=\"open\"><a href=\"{href}\">单独打开这封</a></p>"
        )
        return f"<article class=\"letter\">{head}{meta}{frame}</article>"
    if row["text"]:
        body = f"<pre>{html.escape(row['text'])}</pre>"
        return f"<article class=\"letter\">{head}{meta}{body}</article>"
    note = "这封已经发出。当时没有把正文留在页面上，之后发出的信会完整显示在这里。"
    return f"<article class=\"letter missing\">{head}{meta}<p>{note}</p></article>"


def render_index(days: list[tuple[str, list[dict[str, str]]]], today: str) -> str:
    today_rows = next((rows for day, rows in days if day == today), [])
    earlier = [(day, rows) for day, rows in days if day != today and rows]
    if today_rows:
        lead = f"今天 · {today}"
        body = "".join(_letter_html(today, row) for row in today_rows)
        stale = ""
    else:
        lead = f"今天 · {today}"
        body = "<p class=\"empty\" id=\"empty\">今天还没有发出的邮件。</p>"
        stale = ""
    earlier_html = ""
    if earlier:
        blocks = []
        for day, rows in earlier:
            inner = "".join(_letter_html(day, row) for row in rows)
            blocks.append(f"<section class=\"earlier-day\"><h2 class=\"day-label\">{html.escape(day)}</h2>{inner}</section>")
        earlier_html = "<details class=\"earlier\"><summary>更早的信</summary>" + "".join(blocks) + "</details>"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>今日邮件</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; background: #f6f8fa; color: #1f2328;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }}
    main {{ max-width: 760px; margin: 0 auto; padding: 28px 16px 64px; }}
    header.top {{ background: #1f2328; color: #fff; border-radius: 16px; padding: 22px 24px; }}
    header.top p {{ margin: 8px 0 0; color: #c9d1d9; font-size: 14px; line-height: 1.6; }}
    h1 {{ margin: 0; font-size: 28px; }}
    #lead {{ margin-top: 8px; font-size: 15px; color: #c9d1d9; }}
    article.letter {{ margin-top: 22px; }}
    article.letter h2 {{ margin: 0; font-size: 18px; }}
    .meta {{ margin: 6px 0 10px; color: #57606a; font-size: 13px; }}
    article.missing {{ background: #fff; border: 1px solid #d0d7de; border-radius: 12px; padding: 16px 18px; }}
    article.missing p:last-child {{ margin: 0; color: #57606a; line-height: 1.6; }}
    iframe {{ width: 100%; min-height: 320px; border: 0; border-radius: 12px; background: #fff; }}
    .open {{ margin: 8px 0 0; font-size: 13px; }}
    .open a, a {{ color: #0969da; }}
    pre {{ white-space: pre-wrap; background: #fff; border: 1px solid #d0d7de; border-radius: 12px; padding: 16px; }}
    .empty {{ background: #fff; border: 1px dashed #d0d7de; border-radius: 12px; padding: 18px; color: #57606a; }}
    details.earlier {{ margin-top: 36px; }}
    details.earlier summary {{ cursor: pointer; color: #57606a; }}
    .day-label {{ margin-top: 22px; font-size: 16px; color: #57606a; }}
    #stale {{ display: none; margin-top: 14px; color: #57606a; }}
  </style>
</head>
<body>
  <main>
    <header class="top">
      <h1>今日邮件</h1>
      <p id="lead" data-date="{html.escape(today)}">{html.escape(lead)}</p>
      <p>这里是已经发出的信。定时任务发完一封，就会把正文留在这个页面上。</p>
      <p id="stale">今天的信还没发。下面是最近留下的内容。</p>
    </header>
    {body}
    {earlier_html}
    {stale}
  </main>
  <script>
    function fitLetter(frame) {{
      try {{
        frame.style.height = (frame.contentDocument.documentElement.scrollHeight + 12) + "px";
      }} catch (err) {{}}
    }}
    (function () {{
      var lead = document.getElementById("lead");
      var today = new Intl.DateTimeFormat("en-CA", {{
        timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit"
      }}).format(new Date());
      if (lead.dataset.date !== today) {{
        lead.textContent = lead.dataset.date + " · 上海";
        var stale = document.getElementById("stale");
        if (stale) stale.style.display = "block";
      }}
    }})();
  </script>
</body>
</html>
"""


def list_days(root: Path) -> list[str]:
    names: set[str] = set()
    for folder_name in ("mail-state", "archive"):
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
                names.add(child.name)
    return sorted(names, reverse=True)


def rebuild_site(root: Path, now: datetime | None = None) -> Path:
    current = now or datetime.now(SHANGHAI)
    today = _day_key(current)
    days = [(day, collect_day(root, day)) for day in list_days(root)]
    docs = root / "docs"
    letters = docs / "letters"
    if letters.exists():
        shutil.rmtree(letters)
    letters.mkdir(parents=True, exist_ok=True)
    for day, rows in days:
        for row in rows:
            if not row["html"]:
                continue
            stem = f"{row['kind']}-{row['slot'].replace(':', '')}"
            target = letters / day
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{stem}.html").write_text(row["html"], encoding="utf-8")
    index = docs / "index.html"
    index.write_text(render_index(days, today), encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    return index


def main() -> None:
    path = rebuild_site(repo_root())
    print(path)


if __name__ == "__main__":
    main()
