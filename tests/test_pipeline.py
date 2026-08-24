"""
MsgRelay test suite — runs inside Docker (or locally).

Covers:
  1. NLP engine: multi-language extraction, dates, times, confidence
  2. Config layer: multi-account resolution
  3. DB layer: get_new_messages (skips deleted/empty)
  4. Integration: DB → NLP → structured items
  5. Reports: daily report embed builds without network
  6. Modules: all source modules import cleanly

Run:
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

# ── Build mock environment BEFORE importing product code ──
TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TEST_ROOT)
from mock_env import setup_mock_env

setup_mock_env()

SRC = os.path.join(TEST_ROOT, "..", "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "modules"))

from wacli_nlp_extract import analyze_message, extract_date, extract_time, get_new_messages
from wacli_config import get_accounts, TIMEZONE, EVENT_PREFIX, _load_secrets
import wacli_reports


def _analyze(text: str, ts: int = 0) -> list:
    return analyze_message(text, "sender", "chat", "msg0", ts, False, "")


# ─────────────────────────── NLP engine ───────────────────────────

class TestNLPEngine(unittest.TestCase):

    def test_cantonese_meeting_with_datetime(self):
        items = _analyze("聽日下晝3點開會傾project進度")
        self.assertEqual(items[0]["type"], "event")
        self.assertEqual(items[0]["subtype"], "meeting")
        self.assertEqual(items[0]["time"], "15:00")  # 下晝3點 = 15:00
        self.assertIsNotNone(items[0]["date"])        # 聽日 = tomorrow

    def test_chinese_deadline_becomes_task(self):
        items = _analyze("下星期三deadline前要交report")
        self.assertEqual(items[0]["type"], "task")
        self.assertEqual(items[0]["subtype"], "deadline")
        self.assertIsNotNone(items[0]["due_date"])

    def test_english_meeting_bare_ampm(self):
        items = _analyze("tomorrow 2pm meeting with team")
        self.assertEqual(items[0]["type"], "event")
        self.assertEqual(items[0]["time"], "14:00")

    def test_english_deadline_with_weekday(self):
        items = _analyze("Friday 4pm deadline for the proposal")
        self.assertEqual(items[0]["type"], "task")
        self.assertEqual(items[0]["subtype"], "deadline")
        self.assertIsNotNone(items[0]["due_date"])  # next Friday resolved

    def test_cantonese_task(self):
        items = _analyze("記得跟進個client個case")
        self.assertEqual(items[0]["type"], "task")

    def test_chat_noise_extracts_nothing(self):
        items = _analyze("今日天氣好好")
        self.assertEqual(items, [])

    def test_empty_and_placeholder_text(self):
        self.assertEqual(_analyze(""), [])
        self.assertEqual(_analyze("(message)"), [])
        self.assertEqual(_analyze(None), [])

    def test_bare_chinese_hour_assumed_pm(self):
        self.assertEqual(extract_time("星期三 2點見面"), (14, 0))
        self.assertEqual(extract_time("星期五 10點開會"), (10, 0))

    def test_chinese_half_hour(self):
        self.assertEqual(extract_time("明天上午10點半見面"), (10, 30))
        self.assertEqual(extract_time("今晚8點半食飯"), (20, 30))

    def test_english_time_formats(self):
        self.assertEqual(extract_time("3:30pm call"), (15, 30))
        self.assertEqual(extract_time("9am start"), (9, 0))
        self.assertEqual(extract_time("14:30"), (14, 30))

    def test_date_extraction(self):
        from datetime import datetime, timedelta
        ref = datetime(2026, 8, 24)  # Monday
        self.assertEqual(extract_date("明天開會", ref), ref + timedelta(days=1))
        self.assertEqual(extract_date("後日見", ref), ref + timedelta(days=2))
        self.assertEqual(extract_date("下星期三", ref), datetime(2026, 9, 2))
        self.assertEqual(extract_date("next monday", ref), datetime(2026, 8, 31))
        self.assertEqual(extract_date("Friday", ref), datetime(2026, 8, 28))
        self.assertEqual(extract_date("2026-09-15", ref), datetime(2026, 9, 15))
        self.assertEqual(extract_date("普通消息", ref), None)

    def test_confidence_floor(self):
        """Calendar/Tasks use a 0.65 threshold — low-confidence noise must not pass."""
        items = _analyze("記得跟進個client個case")
        self.assertGreaterEqual(items[0]["confidence"], 0.65)


# ─────────────────────────── Config layer ─────────────────────────

class TestConfig(unittest.TestCase):

    def test_multi_account_resolution(self):
        accounts = get_accounts()
        self.assertEqual(len(accounts), 2)
        names = {a["name"] for a in accounts}
        self.assertEqual(names, {"personal", "work"})
        for a in accounts:
            self.assertTrue(os.path.exists(a["db"]), f"DB missing: {a['db']}")

    def test_timezone_and_branding(self):
        self.assertEqual(TIMEZONE, "Asia/Hong_Kong")
        self.assertEqual(EVENT_PREFIX, "[WA]")

    def test_secrets_loaded(self):
        secrets = _load_secrets()
        self.assertEqual(secrets["discord_webhook_url"], "https://discord.com/api/webhooks/test/test")


# ───────────────────────────── DB layer ───────────────────────────

class TestDBLayer(unittest.TestCase):

    def test_get_new_messages_skips_deleted_and_empty(self):
        accounts = get_accounts()
        personal = [a for a in accounts if a["name"] == "personal"][0]
        since = int(__import__("datetime").datetime.now().timestamp()) - 7200
        msgs = get_new_messages(personal["db"], since, limit=100)

        ids = {m["msg_id"] for m in msgs}
        self.assertIn("m1001", ids)
        self.assertIn("m1002", ids)
        self.assertNotIn("m1007", ids)   # deleted_at set → excluded
        self.assertNotIn("m1008", ids)   # "(message)" placeholder → excluded
        self.assertTrue(all(m["text"] for m in msgs))


# ─────────────────────────── Integration ──────────────────────────

class TestIntegration(unittest.TestCase):

    def test_db_to_structured_items(self):
        accounts = get_accounts()
        personal = [a for a in accounts if a["name"] == "personal"][0]
        since = int(__import__("datetime").datetime.now().timestamp()) - 7200
        msgs = get_new_messages(personal["db"], since, limit=100)

        events = []
        tasks = []
        for m in msgs:
            items = analyze_message(m["text"], m["sender"], m["chat"],
                                    m["msg_id"], m["ts"], bool(m["from_me"]), m["media_type"])
            for it in items:
                if it["type"] == "event" and it["confidence"] >= 0.65:
                    events.append(it)
                elif it["type"] == "task" and it["confidence"] >= 0.65:
                    tasks.append(it)

        self.assertGreaterEqual(len(events), 2)   # 聽日下晝3點開會 + tomorrow 2pm
        self.assertGreaterEqual(len(tasks), 3)    # deadline x2 + 記得跟進

        # Events must carry calendar-ready fields
        for ev in events:
            self.assertIn("title", ev)
            self.assertIn("source_chat", ev)
            self.assertIn("source_sender", ev)

        # Tasks with deadlines must carry due_date
        deadlines = [t for t in tasks if t.get("subtype") == "deadline"]
        for d in deadlines:
            self.assertIsNotNone(d["due_date"], f"deadline missing due_date: {d['title']}")


# ───────────────────────────── Reports ────────────────────────────

class TestReports(unittest.TestCase):

    def test_daily_report_builds_embed(self):
        embed = wacli_reports.build_daily_report()
        self.assertIn("title", embed)
        self.assertIn("fields", embed)
        self.assertEqual(len(embed["fields"]), 2)  # one per account
        for f in embed["fields"]:
            self.assertIn("name", f)
            self.assertIn("value", f)

    def test_weekly_report_builds_embed(self):
        embed = wacli_reports.build_weekly_report()
        self.assertIn("fields", embed)
        self.assertEqual(len(embed["fields"]), 2)


# ─────────────────────────── Modules ──────────────────────────────

class TestModules(unittest.TestCase):

    def test_all_modules_import(self):
        import wacli_calendar, wacli_tasks, wacli_notify, wacli_config
        import wacli_lark_calendar, wacli_lark_tasks, wacli_lark_create, wacli_lark_oauth
        for mod in (wacli_calendar, wacli_tasks, wacli_notify, wacli_config,
                    wacli_lark_calendar, wacli_lark_tasks, wacli_lark_create,
                    wacli_lark_oauth):
            self.assertIsNotNone(mod)


if __name__ == "__main__":
    unittest.main(verbosity=2)
