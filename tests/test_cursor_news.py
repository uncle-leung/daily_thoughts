import json
import os
import pathlib
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from cursor_agent import (  # noqa: E402
    CursorResearchError,
    completed_search_tools,
    model_selection,
    parse_sse,
    require_live_search,
    result_text,
)
from cursor_news import (  # noqa: E402
    load_cursor_events,
    load_cursor_ideas,
    parse_events,
    parse_ideas,
    usable_link,
)
from daily_ideas import render_text as render_ideas  # noqa: E402
from major_events import material_note, render_text as render_events  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
BODY = "第一句说明已经发生的事。第二句补充地点和人物。第三句交代目前的结果。"


def story(scope_key: str, number: int) -> dict[str, str]:
    return {
        "title": f"{scope_key}标题{number}已经发生",
        "source": "测试社",
        "link": f"https://example.com/{scope_key}/{number}",
        "body": BODY,
    }


def idea(number: int, category: str, topic: str) -> dict[str, str]:
    return {
        "category": category,
        "title": f"想法标题{number}",
        "body": BODY + "第四句只留下一个今天用得上的判断。",
        "source": "测试社",
        "link": f"https://example.com/idea/{number}",
        "topic": topic,
    }


SSE = """event: status
data: {"status":"RUNNING","runId":"run-1"}

event: tool_call
data: {"name":"web_search","status":"completed","args":{"searchTerm":"today"}}

event: tool_call
data: {"name":"web_fetch","status":"completed","args":{"url":"https://example.com/a"}}

event: tool_call
data: {"name":"web_search","status":"running"}

event: result
data: {"status":"FINISHED","text":"{\\"ok\\":true}"}

"""


class CursorNewsTest(unittest.TestCase):
    def test_model_defaults_to_grok_4_7(self) -> None:
        previous = os.environ.pop("CURSOR_MODEL", None)
        try:
            selection = model_selection()
        finally:
            if previous is not None:
                os.environ["CURSOR_MODEL"] = previous
        self.assertEqual(selection["id"], "grok-4.7")
        params = {item["id"]: item["value"] for item in selection["params"]}
        self.assertEqual(params["reasoning_effort"], "high")
        self.assertEqual(params["fast"], "true")

    def test_stream_requires_search_and_fetch(self) -> None:
        events = parse_sse(SSE)
        tools = completed_search_tools(events)
        require_live_search(tools)
        self.assertEqual(result_text(events), '{"ok":true}')
        with self.assertRaises(CursorResearchError):
            require_live_search(["web_search"])

    def test_memory_only_reply_is_dropped(self) -> None:
        payload = {
            "domestic": [
                {
                    "title": "没有链接的旧闻",
                    "source": "记忆",
                    "link": "",
                    "body": BODY,
                },
                {
                    "title": "搜索跳转不能当原文",
                    "source": "谷歌",
                    "link": "https://news.google.com/rss/articles/abc",
                    "body": BODY,
                },
            ],
            "world": [story("world", 1)],
        }
        domestic, world = parse_events(json_of(payload))
        self.assertEqual(domestic, [])
        self.assertEqual(len(world), 1)
        self.assertFalse(usable_link("https://news.google.com/rss/articles/abc"))
        self.assertTrue(usable_link("https://www.reuters.com/world/story"))

    def test_fenced_json_and_sentence_clip(self) -> None:
        row = story("domestic", 1)
        row["body"] = BODY + "第四句还在。第五句应该被剪掉。"
        text = "```json\n" + json_of({"domestic": [row], "world": []}) + "\n```"
        domestic, world = parse_events(text)
        self.assertEqual(world, [])
        self.assertEqual(domestic[0]["body"].count("。"), 4)
        self.assertNotIn("第五句", domestic[0]["body"])
        self.assertEqual(domestic[0]["via"], "cursor")

    def test_loader_rejects_a_thin_search(self) -> None:
        os.environ["CURSOR_API_KEY"] = "test-key-not-real"
        try:
            def runner(prompt: str, name: str) -> tuple[str, list[str]]:
                self.assertIn("web_search", prompt)
                self.assertIn("web_fetch", prompt)
                self.assertIn(name[:2], name)
                return json_of({"domestic": [story("domestic", 1)], "world": [story("world", 1)]}), [
                    "web_search",
                    "web_fetch",
                ]

            self.assertIsNone(load_cursor_events(datetime(2026, 10, 28, 9, 15, tzinfo=SHANGHAI), runner))
        finally:
            os.environ.pop("CURSOR_API_KEY", None)

    def test_loader_keeps_a_full_search(self) -> None:
        os.environ["CURSOR_API_KEY"] = "test-key-not-real"
        try:
            topics = (
                ("知识", "ai"),
                ("知识", "ai"),
                ("知识", "ai"),
                ("世间", "world"),
                ("世间", "world"),
                ("工作", "work"),
                ("世间", "climate"),
                ("健康", "health"),
                ("财富", "wealth"),
                ("人生", "society"),
            )

            def events_runner(prompt: str, name: str) -> tuple[str, list[str]]:
                del prompt, name
                return json_of(
                    {
                        "domestic": [story("domestic", number) for number in range(1, 11)],
                        "world": [story("world", number) for number in range(1, 11)],
                    }
                ), ["web_search", "web_fetch"]

            def ideas_runner(prompt: str, name: str) -> tuple[str, list[str]]:
                del prompt, name
                return json_of({"ideas": [idea(number, category, topic) for number, (category, topic) in enumerate(topics, start=1)]}), [
                    "web_search",
                    "web_fetch",
                ]

            loaded = load_cursor_events(datetime(2026, 10, 28, 18, 15, tzinfo=SHANGHAI), events_runner)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            domestic, world = loaded
            self.assertEqual(len(domestic), 10)
            self.assertEqual(len(world), 10)
            letter = render_events(domestic, world, datetime(2026, 10, 28, 18, 15, tzinfo=SHANGHAI))
            self.assertIn("不使用模型记忆", letter)
            self.assertIn("Grok 4.7", letter)
            self.assertIn("Grok 4.7", material_note(domestic))

            ideas = load_cursor_ideas(datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI), ideas_runner)
            self.assertIsNotNone(ideas)
            assert ideas is not None
            self.assertEqual(len(ideas), 10)
            text = render_ideas(ideas, datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI))
            self.assertIn("不使用模型记忆", text)
            self.assertNotIn("仍然成立的判断", text)
        finally:
            os.environ.pop("CURSOR_API_KEY", None)

    def test_missing_key_does_not_call_the_agent(self) -> None:
        os.environ.pop("CURSOR_API_KEY", None)

        def boom(prompt: str, name: str) -> tuple[str, list[str]]:
            del prompt, name
            raise AssertionError("agent should not run")

        now = datetime(2026, 10, 28, 9, 30, tzinfo=SHANGHAI)
        self.assertIsNone(load_cursor_events(now, boom))
        self.assertIsNone(load_cursor_ideas(now, boom))

    def test_ideas_drop_bad_categories(self) -> None:
        raw = idea(1, "娱乐", "ai")
        kept = parse_ideas(json_of({"ideas": [raw, idea(2, "知识", "ai")]}))
        self.assertEqual([item["title"] for item in kept], ["想法标题2"])


def json_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
