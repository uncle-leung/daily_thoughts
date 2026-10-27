import pathlib
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from daily_ideas import select_ideas, sentence_count, slot_for  # noqa: E402
from ideas_bank import IDEAS  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


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

    def test_each_delivery_has_ten_distinct_ideas(self) -> None:
        morning = datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI)
        evening = datetime(2026, 10, 28, 18, 30, tzinfo=SHANGHAI)
        for moment in (morning, evening):
            ideas = select_ideas(moment)
            self.assertEqual(len(ideas), 10)
            self.assertEqual(len({idea["title"] for idea in ideas}), 10)
            self.assertGreaterEqual(len({idea["category"] for idea in ideas}), 5)

    def test_morning_and_evening_differ(self) -> None:
        morning = select_ideas(datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI))
        evening = select_ideas(datetime(2026, 10, 28, 18, 30, tzinfo=SHANGHAI))
        self.assertNotEqual(
            [idea["title"] for idea in morning],
            [idea["title"] for idea in evening],
        )
        self.assertEqual(
            {idea["title"] for idea in morning} & {idea["title"] for idea in evening},
            set(),
        )

    def test_slot_labels(self) -> None:
        self.assertEqual(slot_for(datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI)), "09:30")
        self.assertEqual(slot_for(datetime(2026, 10, 28, 18, 30, tzinfo=SHANGHAI)), "18:30")


if __name__ == "__main__":
    unittest.main()
