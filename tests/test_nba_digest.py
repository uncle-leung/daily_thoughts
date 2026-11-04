import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import nba_digest  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


CATALOG = {
    "NBATV.us": {
        "id": "NBATV.us",
        "name": "NBA TV (720p)",
        "in_sports_m3u": "1",
        "url": "http://example.test/nba.m3u8",
        "note": "",
    },
    "ESPN.us": {
        "id": "ESPN.us",
        "name": "ESPN (United States) HD (720p)",
        "in_sports_m3u": "1",
        "url": "http://example.test/espn.m3u8",
        "note": "",
    },
    "ESPN2.us": {
        "id": "ESPN2.us",
        "name": "ESPN 2 (United States) HD (720p)",
        "in_sports_m3u": "1",
        "url": "http://example.test/espn2.m3u8",
        "note": "",
    },
    "TNT.us": {
        "id": "TNT.us",
        "name": "TNT",
        "in_sports_m3u": "0",
        "url": "http://example.test/tnt.m3u8",
        "note": "本季美国不转 NBA",
    },
    "ABC.us": {
        "id": "ABC.us",
        "name": "ABC",
        "in_sports_m3u": "0",
        "url": "http://example.test/abc.m3u8",
        "note": "全国场次；iptv 多为地方台信号",
    },
    "Sportsnet.ca": {
        "id": "Sportsnet.ca",
        "name": "Sportsnet",
        "in_sports_m3u": "0",
        "url": "",
        "note": "iptv-org 暂无可用流",
    },
    "SportsnetOne.ca": {
        "id": "SportsnetOne.ca",
        "name": "Sportsnet One",
        "in_sports_m3u": "0",
        "url": "",
        "note": "",
    },
    "Sportsnet360.ca": {
        "id": "Sportsnet360.ca",
        "name": "Sportsnet 360",
        "in_sports_m3u": "0",
        "url": "",
        "note": "",
    },
    "SportsnetWorld.ca": {
        "id": "SportsnetWorld.ca",
        "name": "Sportsnet World",
        "in_sports_m3u": "0",
        "url": "",
        "note": "",
    },
}


def _event(event_id: str, when: str, away: str, home: str, broadcasts: list[str]) -> dict:
    return {
        "id": event_id,
        "date": when,
        "status": {"type": {"description": "Scheduled"}},
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "away", "team": {"abbreviation": away, "displayName": away}},
                    {"homeAway": "home", "team": {"abbreviation": home, "displayName": home}},
                ],
                "broadcasts": [{"names": broadcasts}] if broadcasts else [],
                "geoBroadcasts": [],
            }
        ],
    }


class NbaDigestTest(unittest.TestCase):
    def test_shanghai_today_and_tomorrow_are_split_and_mapped_to_espn(self) -> None:
        now = datetime(2026, 11, 4, 16, 30, tzinfo=SHANGHAI)
        # 08:00 Shanghai Nov 5 == 2026-11-05T00:00:00Z
        payload_nov4 = {
            "events": [
                _event("1", "2026-11-05T00:00:00Z", "PHI", "DET", ["ESPN"]),
                _event("2", "2026-11-05T02:30:00Z", "DAL", "SA", ["ESPN"]),
                # Still Nov 5 Shanghai (23:00), maps to NBA TV in sports.m3u
                _event("3", "2026-11-05T15:00:00Z", "MIA", "GS", ["NBA TV"]),
            ]
        }

        def fake_fetch(url: str, timeout: int = 30) -> str:
            if "dates=20261104" in url:
                return json.dumps(payload_nov4)
            return json.dumps({"events": []})

        with patch.object(nba_digest, "_fetch", side_effect=fake_fetch):
            games = nba_digest.load_games(now, CATALOG)

        self.assertEqual(len(games), 3)
        self.assertEqual(games[0]["shanghai_date"].isoformat(), "2026-11-05")
        self.assertEqual(games[0]["away_zh"], "费城76人")
        self.assertIn("ESPN", games[0]["iptv_label"])
        self.assertIn("NBA TV", games[2]["iptv_label"])
        # Nov 4 Shanghai afternoon: "today" empty, "tomorrow" has the slate
        text = nba_digest.render_text(games, CATALOG, now)
        self.assertIn("今天直播 · 2026-11-04", text)
        self.assertIn("（这一天没有比赛）", text)
        self.assertIn("明天预告 · 2026-11-05", text)
        self.assertIn("08:00  费城76人 @ 底特律活塞", text)
        self.assertIn("NBA TV", text)
        subject = nba_digest.subject_for(now, games)
        self.assertTrue(subject.startswith("NBA直播 · "))
        self.assertIn("ESPN", subject)
        self.assertIn("费城76人", subject)
        self.assertNotIn("sports.m3u", subject)

    def test_tnt_and_sportsnet_notes_appear_in_channel_guide(self) -> None:
        rows = {row["id"]: row for row in nba_digest.channel_guide(CATALOG)}
        self.assertIn("本季美国不转 NBA", rows["TNT.us"]["status"])
        self.assertIn("暂无源", rows["Sportsnet.ca"]["status"])

    def test_slot_switches_at_shanghai_afternoon(self) -> None:
        morning = datetime(2026, 11, 4, 9, 0, tzinfo=SHANGHAI)
        evening = datetime(2026, 11, 4, 18, 50, tzinfo=SHANGHAI)
        self.assertEqual(nba_digest.slot_for(morning), "08:45")
        self.assertEqual(nba_digest.slot_for(evening), "18:45")


if __name__ == "__main__":
    unittest.main()
