"""
Tests for priority learning, task grouping, and task tracker engines.
"""
from __future__ import annotations

import os
import sys
import unittest

TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TEST_ROOT)
from mock_env import setup_mock_env

setup_mock_env()

SRC = os.path.join(TEST_ROOT, "..", "src")
sys.path.insert(0, SRC)

import msgrelay_groups
import msgrelay_tracker
import msgrelay_priority
from wacli_config import SCRIPTS_DIR

import json

GROUPS_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_task_groups.json")
TRACKER_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_task_tracker.json")
PRIORITY_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_priority_rules.json")


def _wipe(f):
    if os.path.exists(f):
        os.remove(f)


class TestGroups(unittest.TestCase):

    def setUp(self):
        _wipe(GROUPS_FILE)

    def test_default_groups_exist(self):
        groups = msgrelay_groups.get_groups()
        self.assertIn("soc-alerts", groups)
        self.assertIn("infra-maintain", groups)

    def test_classify_by_keyword(self):
        # "follow up" (in title, x2) beats "client" (in text, x1)
        g = msgrelay_groups.classify_task("ArcSight migration follow up", "client migration")
        self.assertIn(g, ("follow-up", "client-request"))

    def test_classify_infra(self):
        g = msgrelay_groups.classify_task("Wazuh disk cleanup on server", "disk full on server")
        self.assertEqual(g, "infra-maintain")

    def test_classify_no_match(self):
        g = msgrelay_groups.classify_task("完全無關的隨意內容 zzz", "")
        self.assertIsNone(g)

    def test_add_group(self):
        ok = msgrelay_groups.add_group("myproj", "My Project", "project", ["myproj", "xyz"])
        self.assertTrue(ok)
        self.assertFalse(msgrelay_groups.add_group("myproj", "x", "project", []))  # dup
        g = msgrelay_groups.classify_task("xyz task here", "")
        self.assertEqual(g, "myproj")


class TestTracker(unittest.TestCase):

    def setUp(self):
        _wipe(TRACKER_FILE)

    def test_add_and_complete(self):
        tid = msgrelay_tracker.add_task("Wazuh cleanup", chat="Team", sender="Alice",
                                        text="Wazuh disk cleanup on server")
        tasks = msgrelay_tracker.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "open")
        self.assertEqual(tasks[0]["source_sender"], "Alice")
        self.assertTrue(msgrelay_tracker.complete_task(tid))
        self.assertFalse(msgrelay_tracker.complete_task("nope"))
        self.assertEqual(msgrelay_tracker.list_tasks("completed")[0]["status"], "completed")

    def test_auto_grouping(self):
        tid = msgrelay_tracker.add_task("disk full on server", text="disk full on server")
        t = msgrelay_tracker.list_tasks()[0]
        self.assertEqual(t["group_key"], "infra-maintain")

    def test_notes_and_stats(self):
        tid = msgrelay_tracker.add_task("Follow up client")
        self.assertTrue(msgrelay_tracker.set_notes(tid, "called, waiting reply"))
        t = msgrelay_tracker.list_tasks()[0]
        self.assertEqual(t["notes"], "called, waiting reply")
        msgrelay_tracker.complete_task(tid)
        stats = msgrelay_tracker.get_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["completed"], 1)


class TestPriority(unittest.TestCase):

    def setUp(self):
        _wipe(PRIORITY_FILE)

    def test_default_medium(self):
        r = msgrelay_priority.get_sender_priority("Unknown Person")
        self.assertEqual(r["priority"], "medium")
        self.assertEqual(r["source"], "default")

    def test_set_and_get(self):
        msgrelay_priority.set_sender_priority("Alice", "high", 0.9, "escalates a lot")
        r = msgrelay_priority.get_sender_priority("Alice")
        self.assertEqual(r["priority"], "high")
        self.assertEqual(r["confidence"], 0.9)
        self.assertEqual(r["source"], "learned")

    def test_merge_higher_confidence_wins(self):
        kb = {"sender_weights": {}}
        updated = msgrelay_priority._merge_weights(kb["sender_weights"], [
            {"sender": "Bob", "default_priority": "medium", "confidence": 0.4},
            {"sender": "Bob", "default_priority": "high", "confidence": 0.9},
        ])
        self.assertEqual(updated, 2)  # 1 insert + 1 override
        self.assertEqual(kb["sender_weights"]["Bob"]["default_priority"], "high")

    def test_merge_lower_confidence_keeps_old(self):
        kb = {"sender_weights": {
            "Bob": {"default_priority": "high", "confidence": 0.9}}}
        updated = msgrelay_priority._merge_weights(kb["sender_weights"], [
            {"sender": "Bob", "default_priority": "low", "confidence": 0.3},
        ])
        self.assertEqual(updated, 0)
        self.assertEqual(kb["sender_weights"]["Bob"]["default_priority"], "high")

    def test_learn_with_stats(self):
        """No LLM configured → stats fallback derives weights from task counts."""
        os.environ.pop("MSGRELAY_LLM_API_KEY", None)
        os.environ.pop("MSGRELAY_LLM_BASE_URL", None)
        messages = [
            {"sender": "Busy", "text": "記得跟進個client個case"},
            {"sender": "Busy", "text": "need to fix the login bug"},
            {"sender": "Busy", "text": "follow up on the SOC alert"},
            {"sender": "Chatty", "text": "今日天氣好好"},
        ]
        result = msgrelay_priority.learn_with_stats(messages)
        self.assertEqual(result["llm"], False)
        self.assertGreaterEqual(result["updated"], 1)
        r = msgrelay_priority.get_sender_priority("Busy")
        self.assertEqual(r["priority"], "high")
        # Chatty produced no tasks → default remains
        self.assertEqual(msgrelay_priority.get_sender_priority("Chatty")["priority"], "medium")


class TestExtractionEnrichment(unittest.TestCase):

    def test_items_have_priority_and_group(self):
        os.environ.pop("MSGRELAY_LLM_API_KEY", None)
        os.environ.pop("MSGRELAY_LLM_BASE_URL", None)
        _wipe(PRIORITY_FILE)
        _wipe(GROUPS_FILE)
        msgrelay_priority.set_sender_priority("Boss", "high", 0.95, "test")

        import msgrelay_extract
        msgs = [{"msg_id": "e1", "text": "記得跟進個client個case",
                 "sender": "Boss", "chat": "Team", "ts": 0, "from_me": 0, "media_type": ""}]
        out = msgrelay_extract.extract_all(msgs)
        task = [i for i in out["e1"] if i["type"] == "task"][0]
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["priority_confidence"], 0.95)
        self.assertIn("group_key", task)  # may be None or a real group


if __name__ == "__main__":
    unittest.main(verbosity=2)
