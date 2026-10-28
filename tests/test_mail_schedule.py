import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mail_schedule import begin_send, mark_sent  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
