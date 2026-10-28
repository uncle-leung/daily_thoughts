import pathlib
import re
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from github_trending_digest import (  # noqa: E402
    draft_summary,
    formsubmit_needs_activation,
    limit_to_three,
    parse_gtx_payload,
    parse_trending_html,
    render_text,
    shape_summary,
    subject_for,
)

SAMPLE = """
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/Nutlope/hallmark" class="Link">
      <span class="text-normal">Nutlope /</span>
      hallmark
    </a>
  </h2>
  <p class="col-9 color-fg-muted my-1 tmp-pr-4">
    Anti-AI-slop design skill for Claude &amp; Cursor.
  </p>
  <div class="f6 color-fg-muted mt-2">
    <span itemprop="programmingLanguage">CSS</span>
    <a href="/Nutlope/hallmark/stargazers" class="Link Link--muted">
      <svg class="octicon octicon-star"></svg>
      37,548
    </a>
    <a href="/Nutlope/hallmark/forks" class="Link Link--muted">
      <svg class="octicon octicon-repo-forked"></svg>
      1,955
    </a>
    <span class="d-inline-block float-sm-right">
      <svg class="octicon octicon-star"></svg>
      2,244 stars today
    </span>
  </div>
</article>
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/octo/widget" class="Link">widget</a>
  </h2>
</article>
"""


class ParseTrendingTest(unittest.TestCase):
    def test_extracts_rank_metadata_and_unescapes_description(self) -> None:
        repos = parse_trending_html(SAMPLE, limit=15)
        self.assertEqual(len(repos), 2)
        first = repos[0]
        self.assertEqual(first["owner"], "Nutlope")
        self.assertEqual(first["name"], "hallmark")
        self.assertEqual(first["url"], "https://github.com/Nutlope/hallmark")
        self.assertEqual(first["description"], "Anti-AI-slop design skill for Claude & Cursor.")
        self.assertEqual(first["language"], "CSS")
        self.assertEqual(first["stars"], "37,548")
        self.assertEqual(first["forks"], "1,955")
        self.assertEqual(first["gained"], "2,244")
        self.assertEqual(first["gained_period"], "今日")
        self.assertEqual(repos[1]["description"], "")
        self.assertEqual(repos[1]["stars"], "")

    def test_limit(self) -> None:
        self.assertEqual(len(parse_trending_html(SAMPLE, limit=1)), 1)

    def test_subject_uses_the_actual_shanghai_clock(self) -> None:
        morning = datetime(2026, 10, 27, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        evening = datetime(2026, 10, 27, 18, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertIn("09:05", subject_for(morning))
        self.assertIn("18:05", subject_for(evening))
        self.assertNotIn("09:00", subject_for(morning))
        self.assertIn("2026-10-27", subject_for(evening))

    def test_text_contains_each_board(self) -> None:
        sections = {
            "daily": parse_trending_html(SAMPLE, limit=1),
            "weekly": [],
            "monthly": [],
            "daily_zh": [],
            "_errors": [],
        }
        text = render_text(sections, datetime(2026, 10, 27, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertIn("今日热门", text)
        self.assertIn("本周热门", text)
        self.assertIn("Nutlope/hallmark", text)
        self.assertIn("这一榜暂时没有取到数据", text)
        sections["daily"][0]["summary"] = "这是一套给编程代理用的界面设计技能。它专门压低生成结果里的模板感。适合 Cursor 和 Claude Code。"
        text = render_text(sections, datetime(2026, 10, 27, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertIn("这是一套给编程代理用的界面设计技能", text)

    def test_draft_summary_uses_two_or_three_sentences(self) -> None:
        readme = """
        # Hallmark
        A design skill for Claude Code, Codex, Cursor and OpenCode that refuses to look AI-generated.
        It ships forty-eight themes and checks the finished interface against a written design bar.
        The skill is meant for agents that write UI, not for a hosted design tool.
        ## Installation
        npm install hallmark
        """
        summary = draft_summary(
            "Anti-AI-slop design skill for Claude and Cursor.",
            readme,
        )
        self.assertGreaterEqual(summary.count("."), 1)
        self.assertLessEqual(summary.count("."), 3)
        self.assertNotIn("npm install", summary)
        self.assertNotIn("Installation", summary)

    def test_draft_summary_skips_changelog_and_nav(self) -> None:
        readme = """
        # TradingAgents
        TradingAgents is a multi-agent LLM framework for financial trading research.
        It lets several analyst agents debate a ticker and then produce a trading brief.
        The desk runs on your own model provider.
        [2026-10] TradingAgents v0.7.0 released with backtests.
        简体中文 | English | 日本語
        """
        summary = draft_summary("TradingAgents: Multi-Agents LLM Financial Trading Framework.", readme)
        self.assertNotIn("2026-10", summary)
        self.assertNotIn("日本語", summary)
        self.assertIn("framework", summary)

    def test_shape_summary_makes_two_or_three_sentences(self) -> None:
        shaped = shape_summary("这是一个本地语音项目，支持声音克隆，也支持视频配音，还能做有声书，并且完全离线")
        self.assertGreaterEqual(shaped.count("。"), 2)
        self.assertLessEqual(shaped.count("。"), 3)
        self.assertTrue(shaped.endswith("。"))
        kept = shape_summary("TradingAgents 是一个多智能体交易框架，反映了真实交易公司的分工。")
        self.assertEqual(kept.count("。"), 1)

    def test_limit_and_translation_payload(self) -> None:
        self.assertEqual(
            limit_to_three("第一句。第二句。第三句。第四句。"),
            "第一句。第二句。第三句。",
        )
        self.assertEqual(
            parse_gtx_payload([[["你好。", "Hello."], ["第二句。", "Second."]]]),
            "你好。第二句。",
        )

    def test_formsubmit_activation_is_not_a_hard_failure(self) -> None:
        self.assertTrue(
            formsubmit_needs_activation(
                {
                    "success": "false",
                    "message": "This form needs Activation. We've sent you an email.",
                }
            )
        )
        self.assertFalse(
            formsubmit_needs_activation(
                {"success": "false", "message": "Make sure you open this page through a web server."}
            )
        )


if __name__ == "__main__":
    unittest.main()
