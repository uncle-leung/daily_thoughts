import pathlib
import sys
import unittest
import unittest.mock
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import bilingual  # noqa: E402
from bilingual import annotate_study_letter, attach_study_english, glossary_hits, usable_english  # noqa: E402
from major_events import render_html  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
LETTER = """<!DOCTYPE html><html><body>
<div style="font-size:13px;">MAJOR EVENTS</div>
<div style="font-size:22px;font-weight:700;margin-top:6px;">国内 10 条 · 国外 10 条</div>
<h2 style="margin:18px 0 0;font-size:16px;">国内大事</h2>
<div style="padding:16px 0;border-bottom:1px solid #e6e8eb;"><div style="font-size:18px;font-weight:700;color:#1f2328;">1. 冷空气带来降温</div><p style="margin:8px 0 0;font-size:15px;line-height:1.75;color:#24292f;">冷空气继续影响中东部，部分地区有降雪。</p></div>
<h2 style="margin:22px 0 0;font-size:16px;">国外大事</h2>
</body></html>
"""
CACHE = {
    "冷空气带来降温": "Cold air brings a sharp drop in temperature",
    "冷空气继续影响中东部，部分地区有降雪。": "Cold air will keep affecting central and eastern China, with snow in some areas.",
}


class BilingualTest(unittest.TestCase):
    def test_glossary_prefers_the_longer_phrase(self) -> None:
        hits = dict(glossary_hits("供应链中断之后，人工智能进入开放权重模型"))
        self.assertEqual(hits["供应链中断"], "supply-chain disruption")
        self.assertNotIn("供应链", hits)
        self.assertEqual(hits["人工智能"], "artificial intelligence")
        self.assertIn("开放权重", hits)

    def test_usable_english_rejects_a_chinese_line(self) -> None:
        self.assertEqual(usable_english("  Cold   air  "), "Cold air")
        self.assertEqual(usable_english("这不是英文"), "")
        self.assertEqual(usable_english(""), "")

    def test_archived_letter_gains_a_study_pair_once(self) -> None:
        page = annotate_study_letter(LETTER, cache=CACHE)
        self.assertIn("Cold air brings a sharp drop in temperature", page)
        self.assertIn("snow in some areas", page)
        self.assertIn(">EN</span>", page)
        self.assertIn("cold air", page)
        self.assertIn("· China", page)
        self.assertIn("Ten from China, ten from abroad", page)
        self.assertIn('data-study="note"', page)
        self.assertEqual(annotate_study_letter(page, cache=CACHE), page)

    def test_new_letter_renders_the_pair_without_translating(self) -> None:
        item = {
            "title": "冷空气带来降温",
            "title_en": "Cold air brings a sharp drop in temperature",
            "body": "冷空气继续影响中东部，部分地区有降雪。",
            "body_en": "Cold air will keep affecting central and eastern China, with snow in some areas.",
            "link": "https://www.chinanews.com.cn/1",
            "source": "中国新闻网",
        }
        page = render_html([item], [], datetime(2026, 11, 16, 9, 20, tzinfo=SHANGHAI))
        self.assertIn("冷空气带来降温", page)
        self.assertIn("Cold air brings a sharp drop in temperature", page)
        self.assertIn("生词", page)
        self.assertIn("中国新闻网", page)
        again = annotate_study_letter(page, cache=CACHE)
        self.assertEqual(again.count("Cold air brings a sharp drop"), 1)

    def test_google_429_stops_further_calls(self) -> None:
        bilingual._google_paused = False
        calls = {"n": 0}

        def boom(*_args, **_kwargs):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                "https://translate.example", 429, "Too Many Requests", hdrs=None, fp=None
            )

        with unittest.mock.patch("bilingual.urllib.request.urlopen", boom):
            self.assertEqual(bilingual._google_one("冷空气"), "")
            self.assertEqual(bilingual._google_one("冷空气"), "")
        self.assertEqual(calls["n"], 1)
        self.assertTrue(bilingual._google_paused)
        bilingual._google_paused = False

    def test_study_translate_uses_the_backup(self) -> None:
        with (
            unittest.mock.patch("bilingual.google_translate", return_value=""),
            unittest.mock.patch("bilingual.mymemory_translate", return_value="Cold air arrives."),
        ):
            self.assertEqual(bilingual.study_translate("冷空气"), "Cold air arrives.")

    def test_failed_fact_still_keeps_the_reflection(self) -> None:
        item = {
            "title": "一条新消息",
            "body": "事实句子。值得留下的是一件具体事实。",
            "fact": "事实句子。",
            "reflection_en": "What is worth keeping is one concrete fact.",
        }
        attach_study_english([item], translator=lambda _text: "", cache={}, write_cache=False)
        self.assertEqual(item["body_en"], "What is worth keeping is one concrete fact.")
        self.assertFalse(item.get("title_en"))


if __name__ == "__main__":
    unittest.main()
