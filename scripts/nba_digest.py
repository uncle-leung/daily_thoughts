#!/usr/bin/env python3
"""Email today's and tomorrow's NBA tip-offs in Shanghai time, with iptv-org channels."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_trending_digest import USER_AGENT, finish_delivery  # noqa: E402
from mail_schedule import begin_send, require_recipient  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
ET = ZoneInfo("America/New_York")
SPORTS_M3U = "https://iptv-org.github.io/iptv/categories/sports.m3u"
STREAMS_API = "https://iptv-org.github.io/api/streams.json"
CHANNELS_API = "https://iptv-org.github.io/api/channels.json"
ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={ymd}"
)

# Channel ids we care about for NBA national / Canadian coverage.
WANTED_CHANNEL_IDS = (
    "NBATV.us",
    "ESPN.us",
    "ESPN2.us",
    "TNT.us",
    "ABC.us",
    "Sportsnet.ca",
    "SportsnetOne.ca",
    "Sportsnet360.ca",
    "SportsnetWorld.ca",
)

TEAM_ZH = {
    "ATL": "亚特兰大老鹰",
    "BOS": "波士顿凯尔特人",
    "BKN": "布鲁克林篮网",
    "CHA": "夏洛特黄蜂",
    "CHI": "芝加哥公牛",
    "CLE": "克利夫兰骑士",
    "DAL": "达拉斯独行侠",
    "DEN": "丹佛掘金",
    "DET": "底特律活塞",
    "GS": "金州勇士",
    "GSW": "金州勇士",
    "HOU": "休斯顿火箭",
    "IND": "印第安纳步行者",
    "LAC": "洛杉矶快船",
    "LAL": "洛杉矶湖人",
    "MEM": "孟菲斯灰熊",
    "MIA": "迈阿密热火",
    "MIL": "密尔沃基雄鹿",
    "MIN": "明尼苏达森林狼",
    "NO": "新奥尔良鹈鹕",
    "NOP": "新奥尔良鹈鹕",
    "NY": "纽约尼克斯",
    "NYK": "纽约尼克斯",
    "OKC": "俄克拉荷马城雷霆",
    "ORL": "奥兰多魔术",
    "PHI": "费城76人",
    "PHX": "菲尼克斯太阳",
    "POR": "波特兰开拓者",
    "SA": "圣安东尼奥马刺",
    "SAS": "圣安东尼奥马刺",
    "SAC": "萨克拉门托国王",
    "TOR": "多伦多猛龙",
    "UTA": "犹他爵士",
    "UTAH": "犹他爵士",
    "WSH": "华盛顿奇才",
    "WAS": "华盛顿奇才",
}

# ESPN short names / aliases → preferred iptv-org channel id.
BROADCAST_TO_CHANNEL = {
    "espn": "ESPN.us",
    "espn2": "ESPN2.us",
    "nba tv": "NBATV.us",
    "nbatv": "NBATV.us",
    "abc": "ABC.us",
    "tnt": "TNT.us",
    "sportsnet": "Sportsnet.ca",
    "sn": "Sportsnet.ca",
    "sn1": "SportsnetOne.ca",
    "sportsnet one": "SportsnetOne.ca",
}

# 2026-27: TNT no longer carries the NBA nationally in the US.
SEASON_NOTE = (
    "本赛季（2026-27）美国全国转播以 ESPN / ABC / NBA TV / NBC / Peacock / Prime Video 为主；"
    "TNT 本季不转 NBA。Sportsnet 是加拿大转播网。"
)


def _stamp(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def slot_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    return "08:45" if current.astimezone(timezone.utc).hour < 6 else "18:45"


def subject_for(now: datetime | None = None, games: list[dict] | None = None) -> str:
    current = _stamp(now)
    headline = _push_headline(games or [], current)
    if headline:
        return f"NBA直播 · {headline}"
    return f"NBA直播 · {current.strftime('%Y-%m-%d %H:%M')}（上海）"


def _pick_headline_game(games: list[dict], now: datetime) -> dict | None:
    today = now.date()
    buckets = [
        [
            game
            for game in games
            if game["shanghai_date"] == today
            and game["status"] in ("Scheduled", "In Progress", "Halftime")
        ],
        [game for game in games if game["shanghai_date"] == today + timedelta(days=1)],
        list(games),
    ]
    for bucket in buckets:
        if not bucket:
            continue
        national = [game for game in bucket if game.get("national")]
        return (national or bucket)[0]
    return None


def _push_headline(games: list[dict], now: datetime) -> str:
    """One short line for email push / notification preview."""
    game = _pick_headline_game(games, now)
    if game is None:
        return ""
    channel = game.get("iptv_label") or game.get("tv_label") or "待定"
    # Keep push titles short: drop trailing sports.m3u / note clutter.
    channel = re.split(r"[（(·]", channel, maxsplit=1)[0].strip() or channel
    return (
        f"{game['tip_shanghai'].strftime('%m-%d %H:%M')} "
        f"{game['away_zh']}@{game['home_zh']} · {channel}"
    )


def _fetch(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.espn.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_extinf_name(line: str) -> str:
    return line.split(",", 1)[-1].strip() if "," in line else line.strip()


def load_iptv_catalog() -> dict[str, dict[str, str]]:
    """Map channel id → display name, playlist presence, and one stream URL if any."""
    catalog: dict[str, dict[str, str]] = {
        channel_id: {
            "id": channel_id,
            "name": channel_id,
            "in_sports_m3u": "0",
            "url": "",
            "note": "",
        }
        for channel_id in WANTED_CHANNEL_IDS
    }
    try:
        channels = json.loads(_fetch(CHANNELS_API))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
        print(f"iptv channels skipped: {exc}")
        channels = []
    for item in channels:
        channel_id = str(item.get("id") or "")
        if channel_id in catalog:
            catalog[channel_id]["name"] = str(item.get("name") or channel_id)

    try:
        playlist = _fetch(SPORTS_M3U)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"sports.m3u skipped: {exc}")
        playlist = ""
    if playlist:
        lines = playlist.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if line.startswith("#EXTINF"):
                match = re.search(r'tvg-id="([^"]+)"', line)
                tvg_id = match.group(1) if match else ""
                # sports.m3u tvg-id often looks like ESPN.us@HD
                base = tvg_id.split("@", 1)[0] if tvg_id else ""
                name = _parse_extinf_name(line)
                jump = index + 1
                while jump < len(lines) and lines[jump].startswith("#") and not lines[jump].startswith(
                    "#EXTINF"
                ):
                    jump += 1
                url = lines[jump].strip() if jump < len(lines) else ""
                if base in catalog:
                    catalog[base]["in_sports_m3u"] = "1"
                    previous = catalog[base].get("name") or ""
                    prefer = bool(
                        not catalog[base]["url"]
                        or (
                            re.search(r"\bHD\b|1080|720", name, re.I)
                            and not re.search(r"\bHD\b|1080|720", previous, re.I)
                        )
                    )
                    if prefer:
                        catalog[base]["name"] = name or catalog[base]["name"]
                        catalog[base]["url"] = url
                index = jump + 1
            else:
                index += 1

    # Fill missing streams from the API (TNT / ABC often sit outside sports.m3u).
    missing = [channel_id for channel_id, row in catalog.items() if not row["url"]]
    if missing:
        try:
            streams = json.loads(_fetch(STREAMS_API))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
            print(f"iptv streams skipped: {exc}")
            streams = []
        for item in streams:
            channel_id = str(item.get("channel") or "")
            if channel_id not in missing or catalog[channel_id]["url"]:
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            catalog[channel_id]["url"] = url
            title = str(item.get("title") or "").strip()
            if title:
                catalog[channel_id]["name"] = title

    catalog["TNT.us"]["note"] = "本季美国不转 NBA"
    catalog["ABC.us"]["note"] = "全国场次；iptv 多为地方台信号"
    if not catalog["Sportsnet.ca"]["url"]:
        catalog["Sportsnet.ca"]["note"] = "iptv-org 暂无可用流"
    return catalog


def _team_zh(abbr: str, fallback: str) -> str:
    return TEAM_ZH.get(abbr.upper(), fallback or abbr)


def _broadcast_names(competition: dict) -> list[str]:
    names: list[str] = []
    for item in competition.get("broadcasts") or []:
        for name in item.get("names") or []:
            if name:
                names.append(str(name))
    for item in competition.get("geoBroadcasts") or []:
        media = item.get("media") or {}
        label = media.get("shortName") or media.get("name")
        if label:
            names.append(str(label))
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def _match_iptv(broadcasts: list[str], catalog: dict[str, dict[str, str]]) -> tuple[str, str, str]:
    """Return (tv_label, iptv_label, channel_id)."""
    tv_label = "、".join(broadcasts) if broadcasts else "地方台 / League Pass"
    for name in broadcasts:
        key = re.sub(r"\s+", " ", name).strip().casefold()
        channel_id = BROADCAST_TO_CHANNEL.get(key)
        if channel_id is None:
            for alias, mapped in BROADCAST_TO_CHANNEL.items():
                if alias in key:
                    channel_id = mapped
                    break
        if not channel_id:
            continue
        row = catalog.get(channel_id) or {}
        label = row.get("name") or channel_id
        note = row.get("note") or ""
        if note:
            label = f"{label}（{note}）"
        elif not row.get("url"):
            label = f"{label}（源暂缺）"
        elif row.get("in_sports_m3u") == "1":
            label = f"{label} · sports.m3u"
        return tv_label, label, channel_id
    return tv_label, "", ""


def _parse_event(event: dict, catalog: dict[str, dict[str, str]]) -> dict | None:
    competition = (event.get("competitions") or [{}])[0]
    teams = competition.get("competitors") or []
    away = next((item for item in teams if item.get("homeAway") == "away"), None)
    home = next((item for item in teams if item.get("homeAway") == "home"), None)
    if away is None or home is None:
        return None
    raw = event.get("date") or competition.get("date") or ""
    try:
        tip = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(SHANGHAI)
    except ValueError:
        return None
    away_abbr = str((away.get("team") or {}).get("abbreviation") or "")
    home_abbr = str((home.get("team") or {}).get("abbreviation") or "")
    away_name = str((away.get("team") or {}).get("displayName") or away_abbr)
    home_name = str((home.get("team") or {}).get("displayName") or home_abbr)
    broadcasts = _broadcast_names(competition)
    tv_label, iptv_label, channel_id = _match_iptv(broadcasts, catalog)
    status = str(((event.get("status") or {}).get("type") or {}).get("description") or "Scheduled")
    return {
        "id": str(event.get("id") or ""),
        "away_abbr": away_abbr,
        "home_abbr": home_abbr,
        "away_zh": _team_zh(away_abbr, away_name),
        "home_zh": _team_zh(home_abbr, home_name),
        "tip_shanghai": tip,
        "shanghai_date": tip.date(),
        "tip_et": tip.astimezone(ET),
        "broadcasts": broadcasts,
        "tv_label": tv_label,
        "iptv_label": iptv_label,
        "channel_id": channel_id,
        "status": status,
        "national": bool(channel_id),
    }


def espn_dates_covering(start: date, end: date) -> list[str]:
    """ESPN scoreboard keys are Eastern calendar days that can tip into Shanghai range."""
    found: list[str] = []
    cursor = datetime(start.year, start.month, start.day, tzinfo=SHANGHAI) - timedelta(hours=16)
    last = datetime(end.year, end.month, end.day, 23, 59, tzinfo=SHANGHAI) + timedelta(hours=16)
    seen: set[str] = set()
    while cursor <= last:
        key = cursor.astimezone(ET).strftime("%Y%m%d")
        if key not in seen:
            seen.add(key)
            found.append(key)
        cursor += timedelta(hours=12)
    return found


def load_games(now: datetime | None = None, catalog: dict[str, dict[str, str]] | None = None) -> list[dict]:
    current = _stamp(now)
    today = current.date()
    tomorrow = today + timedelta(days=1)
    catalog = catalog if catalog is not None else load_iptv_catalog()
    by_id: dict[str, dict] = {}
    for ymd in espn_dates_covering(today, tomorrow):
        url = ESPN_SCOREBOARD.format(ymd=ymd)
        try:
            payload = json.loads(_fetch(url))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
            print(f"espn scoreboard skipped {ymd}: {exc}")
            continue
        for event in payload.get("events") or []:
            parsed = _parse_event(event, catalog)
            if parsed is None:
                continue
            if parsed["shanghai_date"] not in (today, tomorrow):
                continue
            by_id[parsed["id"] or f"{parsed['away_abbr']}-{parsed['home_abbr']}-{parsed['tip_shanghai']}"] = parsed
    games = list(by_id.values())
    games.sort(key=lambda item: (item["tip_shanghai"], item["away_abbr"], item["home_abbr"]))
    print(f"nba games: {len(games)} for {today}–{tomorrow} Shanghai")
    return games


def channel_guide(catalog: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for channel_id in WANTED_CHANNEL_IDS:
        row = catalog[channel_id]
        if channel_id.startswith("Sportsnet") and channel_id != "Sportsnet.ca" and not row.get("url"):
            continue
        status = "sports.m3u 有源" if row.get("in_sports_m3u") == "1" else (
            "API 有源" if row.get("url") else "暂无源"
        )
        if row.get("note"):
            status = f"{status} · {row['note']}"
        rows.append(
            {
                "id": channel_id,
                "name": row.get("name") or channel_id,
                "status": status,
                "url": row.get("url") or "",
            }
        )
    return rows


def render_text(
    games: list[dict],
    catalog: dict[str, dict[str, str]],
    now: datetime | None = None,
) -> str:
    current = _stamp(now)
    today = current.date()
    tomorrow = today + timedelta(days=1)
    lines = [
        subject_for(current, games),
        "",
        "今天直播与明天预告（开球为中国时间）。全国转播场次对照 iptv-org 体育源频道。",
        f"整理时间：{current.strftime('%Y-%m-%d %H:%M')} 上海时间",
        SEASON_NOTE,
        f"体育源：{SPORTS_M3U}",
        "",
    ]
    for label, day in (("今天直播", today), ("明天预告", tomorrow)):
        day_games = [game for game in games if game["shanghai_date"] == day]
        lines.append(f"{label} · {day.isoformat()}")
        lines.append("")
        if not day_games:
            lines.append("（这一天没有比赛）")
            lines.append("")
            continue
        for index, game in enumerate(day_games, start=1):
            tip = game["tip_shanghai"].strftime("%H:%M")
            channel = game["iptv_label"] or game["tv_label"]
            lines.append(
                f"{index}. {tip}  {game['away_zh']} @ {game['home_zh']}"
            )
            lines.append(f"   转播：{game['tv_label']}")
            if game["iptv_label"]:
                lines.append(f"   iptv 频道：{game['iptv_label']}")
            elif game["national"] is False and game["broadcasts"]:
                lines.append("   iptv：无对应全国源，多为地方台 / 流媒体")
            else:
                lines.append(f"   iptv 频道：{channel}")
            lines.append("")
    lines.append("iptv-org 可对照频道")
    lines.append("")
    for row in channel_guide(catalog):
        lines.append(f"- {row['name']}（{row['id']}）· {row['status']}")
    lines.append("")
    lines.append("流地址可能失效或受版权/地区限制，仅作频道对照。每天 08:45 与 18:45（上海）自动发送。")
    return "\n".join(lines).strip() + "\n"


def _game_blocks(games: list[dict], day: date, title: str) -> str:
    day_games = [game for game in games if game["shanghai_date"] == day]
    if not day_games:
        return (
            f"<h2 style=\"margin:22px 0 8px;font-size:16px;\">{html.escape(title)} · {day.isoformat()}</h2>"
            "<p style=\"margin:0;color:#57606a;\">这一天没有比赛。</p>"
        )
    blocks = [
        f"<h2 style=\"margin:22px 0 8px;font-size:16px;\">{html.escape(title)} · {day.isoformat()}</h2>"
    ]
    for index, game in enumerate(day_games, start=1):
        tip = game["tip_shanghai"].strftime("%H:%M")
        iptv = game["iptv_label"] or "无对应全国源"
        badge = ""
        if game["national"]:
            badge = (
                "<span style=\"display:inline-block;margin-left:8px;padding:2px 8px;"
                "border-radius:999px;background:#dafbe1;color:#1a7f37;font-size:12px;\">全国转播</span>"
            )
        blocks.append(
            "<div style=\"padding:14px 0;border-bottom:1px solid #e6e8eb;\">"
            f"<div style=\"font-size:17px;font-weight:700;color:#1f2328;\">"
            f"{index}. {html.escape(tip)}　{html.escape(game['away_zh'])} @ {html.escape(game['home_zh'])}"
            f"{badge}</div>"
            f"<div style=\"margin-top:6px;font-size:14px;color:#24292f;\">转播：{html.escape(game['tv_label'])}</div>"
            f"<div style=\"margin-top:4px;font-size:14px;color:#57606a;\">iptv 频道：{html.escape(iptv)}</div>"
            "</div>"
        )
    return "".join(blocks)


def render_html(
    games: list[dict],
    catalog: dict[str, dict[str, str]],
    now: datetime | None = None,
) -> str:
    current = _stamp(now)
    today = current.date()
    tomorrow = today + timedelta(days=1)
    guide_rows = "".join(
        "<tr>"
        f"<td style=\"padding:8px 6px;border-bottom:1px solid #e6e8eb;\">{html.escape(row['name'])}</td>"
        f"<td style=\"padding:8px 6px;border-bottom:1px solid #e6e8eb;font-size:12px;color:#57606a;\">"
        f"{html.escape(row['id'])}</td>"
        f"<td style=\"padding:8px 6px;border-bottom:1px solid #e6e8eb;\">{html.escape(row['status'])}</td>"
        "</tr>"
        for row in channel_guide(catalog)
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{html.escape(subject_for(current, games))}</title></head>
<body style="margin:0;padding:0;background:#f6f8fa;color:#1f2328;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fa;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;">
        <tr><td style="background:#1f2328;color:#ffffff;padding:22px 24px;border-radius:12px 12px 0 0;">
          <div style="font-size:13px;letter-spacing:0.04em;color:#c9d1d9;">NBA LIVE</div>
          <div style="font-size:22px;font-weight:700;margin-top:6px;">今天直播 · 明天预告</div>
          <div style="font-size:13px;color:#c9d1d9;margin-top:8px;">{html.escape(current.strftime("%Y-%m-%d %H:%M"))} 上海时间 · 每天 08:45 与 18:45</div>
        </td></tr>
        <tr><td style="background:#ffffff;padding:8px 24px 22px;border:1px solid #d0d7de;border-top:0;border-radius:0 0 12px 12px;">
          <p style="margin:16px 0 0;font-size:14px;line-height:1.7;color:#57606a;">{html.escape(SEASON_NOTE)}</p>
          <p style="margin:8px 0 0;font-size:13px;"><a href="{html.escape(SPORTS_M3U, quote=True)}" style="color:#0969da;text-decoration:none;">iptv-org sports.m3u</a></p>
          {_game_blocks(games, today, "今天直播")}
          {_game_blocks(games, tomorrow, "明天预告")}
          <h2 style="margin:28px 0 8px;font-size:16px;">iptv-org 可对照频道</h2>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:14px;">
            <tr style="color:#57606a;font-size:12px;text-align:left;">
              <th style="padding:6px;border-bottom:1px solid #d0d7de;">频道</th>
              <th style="padding:6px;border-bottom:1px solid #d0d7de;">id</th>
              <th style="padding:6px;border-bottom:1px solid #d0d7de;">状态</th>
            </tr>
            {guide_rows}
          </table>
          <p style="margin:18px 0 0;font-size:12px;color:#57606a;line-height:1.6;">流地址可能失效或受版权/地区限制，邮件只做频道对照，不保证能直接观看。</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Email NBA tip-offs with iptv-org channel mapping.")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--html-out", default="")
    parser.add_argument("--text-out", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _stamp()
    slot = None
    if args.send:
        slot = begin_send("nba", now)
        if slot is None:
            return 0
        if require_recipient() is None:
            return 3
    try:
        catalog = load_iptv_catalog()
        games = load_games(now, catalog)
    except Exception as exc:  # noqa: BLE001
        print(f"nba load failed: {exc}", file=sys.stderr)
        return 3
    subject = subject_for(now, games)
    text = render_text(games, catalog, now)
    html_body = render_html(games, catalog, now)
    print(f"subject: {subject}")
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
    return finish_delivery(
        "nba",
        now,
        slot or "08:45",
        subject,
        html_body,
        text,
        "NBA直播",
    )


if __name__ == "__main__":
    raise SystemExit(main())
