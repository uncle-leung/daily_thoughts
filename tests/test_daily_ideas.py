import pathlib
import sys
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from current_signals import classify, parse_rss, prepare_signals  # noqa: E402
from daily_ideas import select_ideas, sentence_count, slot_for  # noqa: E402
from ideas_bank import IDEAS  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>IBM CEO 称开放权重模型性能优秀成本低廉 - Solidot</title>
  <description>IBM CEO 表示在企业内部部署开放权重模型极具价值。他指出闭源与开放权重的差距已经明显缩小。</description>
  <link>https://www.solidot.org/story?sid=1</link>
  <pubDate>Tue, 27 Oct 2026 07:44:22 GMT</pubDate>
</item>
<item>
  <title>理学院举办图论与人工智能学术报告 - 某大学</title>
  <description>理学院举办了一场学术报告，讨论图论与人工智能的课程安排和报名方式。</description>
  <link>https://example.edu/talk</link>
  <pubDate>Tue, 27 Oct 2026 08:00:00 GMT</pubDate>
</item>
<item>
  <title>母蝙蝠听到幼崽叫声心跳会加速</title>
  <description>日本的一项研究观察了母蝙蝠如何识别幼崽叫声，发现心跳会加速。</description>
  <link>https://www.solidot.org/story?sid=2</link>
  <pubDate>Mon, 26 Oct 2026 14:48:44 GMT</pubDate>
</item>
</channel></rss>
""".encode()


def signal(topic: str, category: str, number: int) -> dict[str, str]:
    return {
        "title": f"{category}信号{number}：一件已经发生的变化",
        "summary": f"编号{number}的{category}变化已经出现在公开报道里，而且会碰到普通人的安排。",
        "source": "测试来源",
        "link": "https://example.com/story",
        "category": category,
        "topic": topic,
    }


def sample_signals() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    topics = (
        ("ai", "知识"),
        ("world", "世间"),
        ("work", "工作"),
        ("health", "健康"),
        ("wealth", "财富"),
        ("society", "人生"),
    )
    for topic, category in topics:
        for number in range(1, 5):
            rows.append(signal(topic, category, number))
    return rows


class DailyIdeasTest(unittest.TestCase):
    def test_bank_entries_have_three_or_four_sentences(self) -> None:
        categories = {idea["category"] for idea in IDEAS}
        self.assertEqual(categories, {"世间", "人生", "工作", "健康", "财富", "知识"})
        self.assertGreaterEqual(len(IDEAS), 60)
        for idea in IDEAS:
            count = sentence_count(idea["body"])
            self.assertGreaterEqual(count, 3, idea["title"])
            self.assertLessEqual(count, 4, idea["title"])
            self.assertTrue(idea["body"].endswith("。"), idea["title"])

    def test_reporting_is_kept_and_campus_noise_is_dropped(self) -> None:
        now = datetime(2026, 10, 27, 18, 30, tzinfo=SHANGHAI)
        parsed = parse_rss(SAMPLE_RSS, "Solidot")
        self.assertEqual(parsed[0]["source"], "Solidot")
        self.assertNotIn(" - ", parsed[0]["title"])
        prepared = prepare_signals(parsed, now)
        titles = [item["title"] for item in prepared]
        self.assertEqual(titles, ["IBM CEO 称开放权重模型性能优秀成本低廉"])
        self.assertEqual(classify(parsed[0]["title"]), "知识")
        self.assertEqual(prepared[0]["topic"], "ai")

    def test_each_delivery_uses_today_and_stays_short(self) -> None:
        morning = datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI)
        evening = datetime(2026, 10, 28, 18, 30, tzinfo=SHANGHAI)
        signals = sample_signals()
        for moment in (morning, evening):
            ideas = select_ideas(moment, signals)
            self.assertEqual(len(ideas), 10)
            self.assertEqual(len({idea["title"] for idea in ideas}), 10)
            self.assertGreaterEqual(len({idea["category"] for idea in ideas}), 5)
            self.assertTrue(all(idea["grounded"] == "yes" for idea in ideas))
            for idea in ideas:
                count = sentence_count(idea["body"])
                self.assertGreaterEqual(count, 3, idea["body"])
                self.assertLessEqual(count, 4, idea["body"])
                self.assertIn("测试来源报道", idea["body"])

    def test_morning_and_evening_use_different_reports(self) -> None:
        signals = sample_signals()
        morning = select_ideas(datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI), signals)
        evening = select_ideas(datetime(2026, 10, 28, 18, 30, tzinfo=SHANGHAI), signals)
        self.assertNotEqual([idea["title"] for idea in morning], [idea["title"] for idea in evening])
        self.assertEqual(
            {idea["title"] for idea in morning} & {idea["title"] for idea in evening},
            set(),
        )

    def test_missing_news_still_fills_ten_era_ideas(self) -> None:
        ideas = select_ideas(datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI), [])
        self.assertEqual(len(ideas), 10)
        self.assertTrue(all(idea["grounded"] == "no" for idea in ideas))
        for idea in ideas:
            self.assertGreaterEqual(sentence_count(idea["body"]), 3)
            self.assertLessEqual(sentence_count(idea["body"]), 4)

    def test_slot_labels(self) -> None:
        self.assertEqual(slot_for(datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI)), "09:30")
        self.assertEqual(slot_for(datetime(2026, 10, 28, 18, 30, tzinfo=SHANGHAI)), "18:30")

    def test_old_headlines_are_left_out(self) -> None:
        old = {
            "title": "去年的人工智能融资已经冷却",
            "summary": "这是一条过期的人工智能融资报道，不该再出现在今天的信里。",
            "source": "旧闻",
            "link": "",
            "published": "Mon, 01 Jan 2024 00:00:00 GMT",
        }
        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(prepare_signals([old], now), [])


if __name__ == "__main__":
    unittest.main()
