import pathlib
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from major_events import (  # noqa: E402
    article_sentences,
    body_from_sentences,
    choose_slot,
    parse_rss,
    rank_stories,
    sentence_count,
    slot_for,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>塞尔维亚议会选举初步结果公布</title>
  <link>https://www.chinanews.com.cn/gj/2026/10-27/1.shtml</link>
  <description>学生名单得票领先。</description>
  <pubDate>Tue, 27 Oct 2026 09:39:00 GMT</pubDate>
</item>
<item>
  <title>泰国灯船节：湄公河畔灯火璀璨 传统文化焕发旅游活力</title>
  <link>https://www.chinanews.com.cn/gj/2026/10-27/2.shtml</link>
  <description>灯船节开幕。</description>
  <pubDate>Tue, 27 Oct 2026 02:42:00 GMT</pubDate>
</item>
<item>
  <title>俄乌在奥列什基地区实施停火</title>
  <link>https://www.chinanews.com.cn/gj/2026/10-27/3.shtml</link>
  <description>双方同日宣布停火。</description>
  <pubDate>Tue, 27 Oct 2026 09:28:00 GMT</pubDate>
</item>
</channel></rss>
"""
PAGE = """
<div class="left_zw">
  <p>中新社北京10月27日电 塞尔维亚选举委员会公布议会选举初步结果。学生团体以过半得票领先。</p>
  <p>该名单预计取得一百四十个席位，具备独立组建政府的条件。</p>
  <p>选举委员会表示计票仍在继续，最终议席以官方公报为准。</p>
  <p>多个政党表示将在结果确认后发表声明。</p>
  <p>图为投票站外的民众。</p>
  <!--正文end-->
  <div class="recommend_news_newlist"><p>单兵坚守、刺刀见红，志愿军战斗英雄事迹令人热血沸腾。</p></div>
</div>
"""


def ready(scope: str, number: int) -> dict[str, str]:
    return {
        "title": f"{scope}事件{number}",
        "link": f"https://www.chinanews.com.cn/{number}",
        "body": "第一句说明发生了什么。第二句补充人物和地点。第三句交代目前的结果。",
        "scope": scope,
        "source": "中国新闻网",
    }


class MajorEventsTest(unittest.TestCase):
    def test_soft_stories_are_dropped_and_major_ones_stay(self) -> None:
        now = datetime(2026, 10, 27, 18, 15, tzinfo=SHANGHAI)
        ranked = rank_stories(parse_rss(RSS, "国外"), now)
        self.assertEqual([item["title"] for item in ranked], ["塞尔维亚议会选举初步结果公布", "俄乌在奥列什基地区实施停火"])

    def test_article_body_is_three_or_four_sentences(self) -> None:
        sentences = article_sentences(PAGE)
        body = body_from_sentences(sentences)
        self.assertGreaterEqual(sentence_count(body), 3)
        self.assertLessEqual(sentence_count(body), 4)
        self.assertIn("独立组建政府", body)
        self.assertNotIn("图为", body)
        self.assertNotIn("志愿军", body)

    def test_morning_and_evening_split_the_same_pool(self) -> None:
        domestic = [ready("国内", number) for number in range(1, 21)]
        world = [ready("国外", number) for number in range(1, 21)]
        morning_d = choose_slot(domestic, "09:15")
        evening_d = choose_slot(domestic, "18:15")
        morning_w = choose_slot(world, "09:15")
        evening_w = choose_slot(world, "18:15")
        self.assertEqual(len(morning_d), 10)
        self.assertEqual(len(evening_w), 10)
        self.assertEqual({item["title"] for item in morning_d} & {item["title"] for item in evening_d}, set())
        self.assertEqual({item["title"] for item in morning_w} & {item["title"] for item in evening_w}, set())
        for item in morning_d + evening_w:
            self.assertGreaterEqual(sentence_count(item["body"]), 3)
            self.assertLessEqual(sentence_count(item["body"]), 4)

    def test_slot_labels(self) -> None:
        self.assertEqual(slot_for(datetime(2026, 10, 28, 9, 15, tzinfo=SHANGHAI)), "09:15")
        self.assertEqual(slot_for(datetime(2026, 10, 28, 18, 15, tzinfo=SHANGHAI)), "18:15")


if __name__ == "__main__":
    unittest.main()
