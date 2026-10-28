import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from site_page import collect_day, remember_letter, rebuild_site  # noqa: E402

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
        self.assertIn("GitHub 热门项目", page)
        self.assertIn("没有把正文留在页面上", page)
        self.assertIn("每日想法 · &lt;测试&gt;", page)
        self.assertNotIn("<测试>", page)
        letter = (self.root / "docs" / "letters" / "2026-10-28" / "ideas-1201.html").read_text(encoding="utf-8")
        self.assertIn("三条已经发出的话。", letter)
        rows = collect_day(self.root, "2026-10-28")
        self.assertEqual([row["kind"] for row in rows], ["trending", "ideas"])

    def test_a_day_with_no_mail_says_so(self) -> None:
        page = rebuild_site(self.root, NOW).read_text(encoding="utf-8")
        self.assertIn("今天还没有发出的邮件。", page)


if __name__ == "__main__":
    unittest.main()
