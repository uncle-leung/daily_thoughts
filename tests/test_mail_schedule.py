import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import daily_ideas  # noqa: E402
import github_trending_digest  # noqa: E402
import major_events  # noqa: E402
from mail_schedule import (  # noqa: E402
    begin_send,
    letters_due,
    mailbox_key,
    main,
    mark_sent,
    pending_recipients,
    recipient_list,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class MailScheduleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("MAIL_STATE_DIR")
        os.environ["MAIL_STATE_DIR"] = self._tmp.name
        os.environ.pop("MAIL_FORCE", None)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("MAIL_STATE_DIR", None)
        else:
            os.environ["MAIL_STATE_DIR"] = self._old
        os.environ.pop("DIGEST_TO", None)
        os.environ.pop("DIGEST_ALSO", None)
        os.environ.pop("QQ_SMTP_USER", None)
        os.environ.pop("QQ_SMTP_AUTH_CODE", None)
        self._tmp.cleanup()

    def test_each_morning_slot_opens_on_time_and_stays_open_for_one_catch_up(self) -> None:
        early = datetime(2026, 10, 28, 8, 2, tzinfo=SHANGHAI)
        self.assertEqual(begin_send("trending", early), "08:00")
        self.assertIsNone(begin_send("events", early))
        self.assertIsNone(begin_send("ideas", early))
        late_morning = datetime(2026, 10, 28, 9, 9, tzinfo=SHANGHAI)
        self.assertEqual(begin_send("trending", late_morning), "08:00")
        self.assertEqual(begin_send("events", late_morning), "08:15")
        self.assertEqual(begin_send("ideas", late_morning), "08:30")

    def test_a_sent_slot_is_not_repeated(self) -> None:
        now = datetime(2026, 10, 28, 8, 20, tzinfo=SHANGHAI)
        mark_sent("trending", now, "08:00")
        self.assertIsNone(begin_send("trending", now))
        self.assertEqual(begin_send("events", now), "08:15")

    def test_a_late_night_runner_does_not_send_the_evening_letter(self) -> None:
        late = datetime(2026, 10, 27, 23, 45, tzinfo=SHANGHAI)
        self.assertIsNone(begin_send("trending", late))
        self.assertIsNone(begin_send("events", late))
        self.assertIsNone(begin_send("ideas", late))

    def test_before_the_slot_nothing_is_due(self) -> None:
        now = datetime(2026, 10, 28, 7, 50, tzinfo=SHANGHAI)
        self.assertIsNone(begin_send("trending", now))
        self.assertIsNone(begin_send("ideas", now))

    def test_a_delayed_morning_runner_still_sends_until_noon(self) -> None:
        late = datetime(2026, 10, 29, 10, 40, tzinfo=SHANGHAI)
        self.assertEqual(letters_due(late), ["trending", "events", "ideas"])
        almost_noon = datetime(2026, 10, 29, 11, 59, tzinfo=SHANGHAI)
        self.assertEqual(begin_send("trending", almost_noon), "08:00")
        afternoon = datetime(2026, 10, 29, 13, 0, tzinfo=SHANGHAI)
        self.assertEqual(letters_due(afternoon), [])

    def test_a_delayed_evening_runner_still_sends_until_23(self) -> None:
        delayed = datetime(2026, 10, 28, 20, 30, tzinfo=SHANGHAI)
        self.assertEqual(letters_due(delayed), ["trending", "events", "ideas"])
        closed = datetime(2026, 10, 28, 23, 0, tzinfo=SHANGHAI)
        self.assertEqual(letters_due(closed), [])

    def test_missing_recipient_does_not_start_the_letters(self) -> None:
        os.environ.pop("DIGEST_TO", None)
        now = datetime(2026, 10, 29, 10, 40, tzinfo=SHANGHAI)
        with patch("mail_schedule._stamp", return_value=now):
            with patch("mail_schedule.subprocess.run") as run:
                code = main()
        self.assertEqual(code, 1)
        run.assert_not_called()

    def test_only_the_open_letter_is_started(self) -> None:
        os.environ["DIGEST_TO"] = "reader@example.com"
        now = datetime(2026, 10, 29, 8, 2, tzinfo=SHANGHAI)
        with patch("mail_schedule._stamp", return_value=now):
            with patch("mail_schedule.subprocess.run", return_value=type("Proc", (), {"returncode": 0})()) as run:
                code = main()
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn("github_trending_digest.py", command[1])

    def test_a_letter_refuses_before_fetching_when_the_mailbox_is_missing(self) -> None:
        os.environ.pop("DIGEST_TO", None)
        os.environ.pop("MAIL_FORCE", None)
        now = datetime(2026, 10, 29, 10, 40, tzinfo=SHANGHAI)
        with patch.object(github_trending_digest, "_stamp", return_value=now):
            with patch.object(github_trending_digest, "collect") as collect:
                self.assertEqual(github_trending_digest.main(["--send"]), 3)
                collect.assert_not_called()
        with patch.object(major_events, "_stamp", return_value=now):
            with patch.object(major_events, "load_cursor_events") as load_events:
                self.assertEqual(major_events.main(["--send"]), 3)
                load_events.assert_not_called()
        with patch.object(daily_ideas, "_stamp", return_value=now):
            with patch.object(daily_ideas, "load_cursor_ideas") as load_ideas:
                self.assertEqual(daily_ideas.main(["--send"]), 3)
                load_ideas.assert_not_called()

    def test_extra_mailbox_is_appended_and_duplicates_are_dropped(self) -> None:
        os.environ["DIGEST_TO"] = " owner@example.com, not-an-email "
        os.environ["DIGEST_ALSO"] = "one@example.com, two@example.com，three@example.com owner@example.com"
        self.assertEqual(
            recipient_list(),
            ["owner@example.com", "one@example.com", "two@example.com", "three@example.com"],
        )

    def test_a_new_mailbox_stays_due_until_that_copy_is_delivered(self) -> None:
        now = datetime(2026, 10, 28, 8, 20, tzinfo=SHANGHAI)
        os.environ["DIGEST_TO"] = "owner@example.com"
        os.environ["DIGEST_ALSO"] = "extra@example.com"
        mark_sent("trending", now, "08:00", ["owner@example.com"])
        self.assertEqual(begin_send("trending", now), "08:00")
        self.assertEqual(pending_recipients("trending", now, "08:00"), ["extra@example.com"])
        marker = Path(os.environ["MAIL_STATE_DIR"]) / "2026-10-28" / "trending-0800"
        text = marker.read_text(encoding="utf-8")
        self.assertNotIn("owner@example.com", text)
        self.assertNotIn("extra@example.com", text)
        self.assertIn("to " + mailbox_key("owner@example.com"), text)
        mark_sent("trending", now, "08:00", ["extra@example.com"])
        self.assertIsNone(begin_send("trending", now))

    def test_an_older_marker_is_not_reopened_for_a_new_mailbox(self) -> None:
        now = datetime(2026, 10, 28, 8, 20, tzinfo=SHANGHAI)
        os.environ["DIGEST_TO"] = "owner@example.com"
        os.environ["DIGEST_ALSO"] = "extra@example.com"
        mark_sent("trending", now, "08:00")
        self.assertIsNone(begin_send("trending", now))
        self.assertEqual(pending_recipients("trending", now, "08:00"), [])

    def test_a_rejected_extra_mailbox_does_not_resend_the_one_that_arrived(self) -> None:
        os.environ["DIGEST_TO"] = "owner@example.com"
        os.environ["DIGEST_ALSO"] = "extra@example.com"
        os.environ["QQ_SMTP_AUTH_CODE"] = "secret-code"
        now = datetime(2026, 10, 28, 8, 20, tzinfo=SHANGHAI)

        def fake_send(**kwargs: object) -> tuple[list[str], list[str]]:
            targets = list(kwargs["recipients"])  # type: ignore[index]
            return [targets[0]], targets[1:]

        with patch.object(github_trending_digest, "send_qq_smtp", side_effect=fake_send):
            with patch.object(github_trending_digest, "publish_sent_letter"):
                code = github_trending_digest.finish_delivery(
                    "trending",
                    now,
                    "08:00",
                    "subject",
                    "<p>hello</p>",
                    "hello\n",
                    "GitHub Trending Digest",
                )
        self.assertEqual(code, 3)
        self.assertEqual(pending_recipients("trending", now, "08:00"), ["extra@example.com"])
        marker = Path(os.environ["MAIL_STATE_DIR"]) / "2026-10-28" / "trending-0800"
        self.assertNotIn("owner@example.com", marker.read_text(encoding="utf-8"))

    def test_idle_hour_does_not_start_letters(self) -> None:
        os.environ["DIGEST_TO"] = "reader@example.com"
        now = datetime(2026, 10, 29, 7, 50, tzinfo=SHANGHAI)
        with patch("mail_schedule._stamp", return_value=now):
            with patch("mail_schedule.subprocess.run") as run:
                code = main()
        self.assertEqual(code, 0)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
