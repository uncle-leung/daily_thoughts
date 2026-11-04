import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from site_page import (  # noqa: E402
    collect_day,
    open_links_in_new_tab,
    remember_letter,
    rebuild_site,
    theme_published_letter,
    with_rank_tabs,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 28, 15, 0, tzinfo=SHANGHAI)
LETTER = "<!DOCTYPE html><html><head><title>每日想法 · 测试</title></head><body><p>三条已经发出的话。</p></body></html>"


class SitePageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sent_letter_is_on_the_page_and_marker_without_body_is_named(self) -> None:
        state = self.root / "mail-state" / "2026-10-28"
        state.mkdir(parents=True)
        (state / "trending-0900").write_text("2026-10-28T10:17:09+08:00\n", encoding="utf-8")
        remember_letter(
            self.root,
            "ideas",
            "12:01",
            datetime(2026, 10, 28, 12, 1, tzinfo=SHANGHAI),
            "每日想法 · <测试>",
            LETTER,
            "三条已经发出的话。\n",
        )
        index = rebuild_site(self.root, NOW)
        page = index.read_text(encoding="utf-8")
        self.assertIn("今日邮件", page)
        self.assertIn("今天 · 2026-10-28", page)
        self.assertIn("data-letters", page)
        self.assertIn(">GITHUB TRENDING</button>", page)
        self.assertIn(">DAILY THOUGHTS</button>", page)
        self.assertIn("没有把正文留在页面上", page)
        self.assertIn("每日想法 · &lt;测试&gt;", page)
        self.assertNotIn("<测试>", page)
        self.assertIn('target="_blank"', page)
        letter = (self.root / "docs" / "letters" / "2026-10-28" / "ideas-1201.html").read_text(encoding="utf-8")
        self.assertIn("三条已经发出的话。", letter)
        rows = collect_day(self.root, "2026-10-28")
        self.assertEqual([row["kind"] for row in rows], ["trending", "ideas"])
        (state / "events-0815").write_text(
            "2026-10-28T08:20:00+08:00\nto abcdef\n",
            encoding="utf-8",
        )
        noted = collect_day(self.root, "2026-10-28")
        events = next(row for row in noted if row["kind"] == "events")
        self.assertEqual(events["sentAt"], "2026-10-28T08:20:00+08:00")

    def test_a_day_with_no_mail_says_so(self) -> None:
        page = rebuild_site(self.root, NOW).read_text(encoding="utf-8")
        self.assertIn("今天还没有发出的邮件。", page)

    def test_index_page_uses_the_tech_theme(self) -> None:
        remember_letter(
            self.root,
            "trending",
            "08:00",
            datetime(2026, 10, 28, 8, 5, tzinfo=SHANGHAI),
            "GitHub 热门项目",
            "<!DOCTYPE html><html><head></head><body><a href='https://github.com/x'>x</a></body></html>",
            "x\n",
        )
        remember_letter(
            self.root,
            "nba",
            "08:45",
            datetime(2026, 10, 28, 8, 50, tzinfo=SHANGHAI),
            "NBA直播",
            "<!DOCTYPE html><html><body><td style=\"background:#1f2328;color:#c9d1d9\">NBA</td></body></html>",
            "nba\n",
        )
        rebuild_site(self.root, NOW)
        index = (self.root / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Space Grotesk", index)
        self.assertIn("Daily Thoughts", index)
        self.assertIn("--accent: #14b8a6", index)
        self.assertIn(">NBA LIVE</button>", index)
        letter = (self.root / "docs" / "letters" / "2026-10-28" / "nba-0845.html").read_text(encoding="utf-8")
        self.assertIn("data-daily-theme", letter)
        self.assertIn("#0c2430", letter)

    def test_theme_published_letter_rewrites_flat_black_headers(self) -> None:
        page = theme_published_letter(
            '<html><head></head><body style="background:#f6f8fa">'
            '<td style="background:#1f2328;color:#c9d1d9">X</td></body></html>'
        )
        self.assertIn("data-daily-theme", page)
        self.assertIn("linear-gradient(135deg,#0c2430", page)
        self.assertNotIn('style="background:#1f2328', page)

    def test_letter_links_open_in_a_new_tab(self) -> None:
        source = '<p><a href="https://github.com/example/repo">示例</a></p>'
        rewritten = open_links_in_new_tab(source)
        self.assertIn('target="_blank"', rewritten)
        self.assertIn('rel="noopener noreferrer"', rewritten)
        remember_letter(
            self.root,
            "trending",
            "08:00",
            datetime(2026, 10, 28, 8, 5, tzinfo=SHANGHAI),
            "GitHub 热门项目",
            f"<!DOCTYPE html><html><body>{source}</body></html>",
            "示例\n",
        )
        remember_letter(
            self.root,
            "events",
            "08:15",
            datetime(2026, 10, 28, 8, 20, tzinfo=SHANGHAI),
            "国内外大事",
            "<!DOCTYPE html><html><body><a href='https://example.com'>新闻</a></body></html>",
            "新闻\n",
        )
        rebuild_site(self.root, NOW)
        published = (self.root / "docs" / "letters" / "2026-10-28" / "trending-0800.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('target="_blank"', published)
        index = (self.root / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn(">MAJOR EVENTS</button>", index)
        self.assertIn(">GITHUB TRENDING</button>", index)

    def test_trending_boards_become_tabs_on_the_page_only(self) -> None:
        letter = """<!DOCTYPE html><html><body>
        <h2>今日热门</h2><table><tr><td>1</td></tr></table>
        <h2>本周热门</h2><table><tr><td>2</td></tr></table>
        <h2>本月热门</h2><p>这一榜暂时没有取到数据。</p>
        <h2>中文社区今日热门</h2><table><tr><td>4</td></tr></table>
        </body></html>"""
        remember_letter(
            self.root,
            "trending",
            "18:00",
            datetime(2026, 10, 28, 18, 56, tzinfo=SHANGHAI),
            "GitHub 热门项目",
            letter,
            "今日热门\n",
        )
        rebuild_site(self.root, NOW)
        archived = (self.root / "archive" / "2026-10-28" / "trending-1800.html").read_text(encoding="utf-8")
        published = (self.root / "docs" / "letters" / "2026-10-28" / "trending-1800.html").read_text(encoding="utf-8")
        self.assertNotIn("data-ranks", archived)
        self.assertEqual(published.count("data-ranks>"), 1)
        self.assertIn(">今日</button>", published)
        self.assertIn(">本周</button>", published)
        self.assertIn(">本月</button>", published)
        self.assertIn(">中文社区</button>", published)
        self.assertIn('style="display:none"', published)
        self.assertNotIn('hidden', with_rank_tabs(letter).split("<script>")[0])


if __name__ == "__main__":
    unittest.main()
