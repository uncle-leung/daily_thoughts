import pathlib
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from github_trending_digest import (  # noqa: E402
    formsubmit_needs_activation,
    parse_trending_html,
    render_text,
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

    def test_subject_uses_shanghai_slot(self) -> None:
        morning = datetime(2026, 10, 27, 9, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        evening = datetime(2026, 10, 27, 18, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertIn("09:00", subject_for(morning))
        self.assertIn("18:00", subject_for(evening))
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
