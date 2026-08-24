"""
Tests for the LLM engine + auto-learn engine.

LLM tests mock the HTTP layer — no real API calls, no API key needed.
"""
from __future__ import annotations

import os
import sys
import json
import unittest
from unittest import mock

TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TEST_ROOT)
from mock_env import setup_mock_env

setup_mock_env()

SRC = os.path.join(TEST_ROOT, "..", "src")
sys.path.insert(0, SRC)

from wacli_config import SCRIPTS_DIR
import msgrelay_llm
import msgrelay_learn

LEARN_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_learn.json")


class TestLLMConfig(unittest.TestCase):

    def tearDown(self):
        for k in ("MSGRELAY_LLM_API_KEY", "MSGRELAY_LLM_BASE_URL", "MSGRELAY_LLM_MODEL"):
            os.environ.pop(k, None)

    def test_disabled_by_default(self):
        os.environ.pop("MSGRELAY_LLM_API_KEY", None)
        os.environ.pop("MSGRELAY_LLM_BASE_URL", None)
        self.assertIsNone(msgrelay_llm.get_llm_config())

    def test_enabled_via_env(self):
        os.environ["MSGRELAY_LLM_API_KEY"] = "sk-test"
        os.environ["MSGRELAY_LLM_BASE_URL"] = "https://api.deepseek.com/v1"
        os.environ["MSGRELAY_LLM_MODEL"] = "deepseek-chat"
        cfg = msgrelay_llm.get_llm_config()
        self.assertIsNotNone(cfg)
        self.assertIn("chat/completions", cfg["base_url"])
        self.assertEqual(cfg["model"], "deepseek-chat")

    def test_llm_extract_returns_none_when_disabled(self):
        os.environ.pop("MSGRELAY_LLM_API_KEY", None)
        os.environ.pop("MSGRELAY_LLM_BASE_URL", None)
        self.assertIsNone(msgrelay_llm.llm_extract([{"id": "1", "text": "hi", "sender": "a"}]))


class TestLLMParsing(unittest.TestCase):

    def test_parse_strict_json(self):
        content = '{"m1": [{"type": "event", "subtype": "meeting", "confidence": 0.95, "title": "開會", "date": "2026-08-25", "time": "15:00", "due_date": null}]}'
        parsed = msgrelay_llm._parse_response(content)
        self.assertIn("m1", parsed)
        self.assertEqual(parsed["m1"][0]["type"], "event")

    def test_parse_with_markdown_fences(self):
        content = '```json\n{"m1": []}\n```'
        parsed = msgrelay_llm._parse_response(content)
        self.assertEqual(parsed, {"m1": []})

    def test_parse_garbage_returns_none(self):
        self.assertIsNone(msgrelay_llm._parse_response("not json at all"))
        self.assertIsNone(msgrelay_llm._parse_response(""))

    def test_parse_embedded_json(self):
        content = 'Sure! Here is the result:\n{"a": [{"type": "task", "confidence": 0.8, "title": "x"}]}'
        parsed = msgrelay_llm._parse_response(content)
        self.assertIn("a", parsed)

    def test_merge_with_rules_llm_wins(self):
        llm = [{"type": "event", "subtype": "meeting", "confidence": 0.95,
                "title": "開會", "date": None, "time": None, "due_date": None}]
        rules = [{"type": "event", "subtype": "meeting", "confidence": 0.8,
                  "title": "開會", "date": None, "time": None}]
        merged = msgrelay_llm.merge_with_rules(llm, rules)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["confidence"], 0.95)

    def test_merge_with_rules_empty_llm_uses_rules(self):
        rules = [{"type": "task", "confidence": 0.8, "title": "x"}]
        self.assertEqual(msgrelay_llm.merge_with_rules([], rules), rules)
        self.assertEqual(msgrelay_llm.merge_with_rules(None, rules), rules)

    def test_merge_clamps_confidence(self):
        llm = [{"type": "event", "confidence": 1.7, "title": "x"}]
        merged = msgrelay_llm.merge_with_rules(llm, [])
        self.assertLessEqual(merged[0]["confidence"], 1.0)


class TestLLMHttpFailureFallback(unittest.TestCase):

    def test_http_error_returns_none(self):
        """API failure must NOT crash — returns None so caller falls back to rules."""
        os.environ["MSGRELAY_LLM_API_KEY"] = "sk-test"
        with mock.patch("msgrelay_llm.requests.post",
                        side_effect=Exception("connection refused")):
            result = msgrelay_llm.llm_extract(
                [{"id": "1", "text": "明天開會", "sender": "a"}])
        self.assertIsNone(result)


class TestLearnEngine(unittest.TestCase):

    def setUp(self):
        msgrelay_learn.reset()

    def tearDown(self):
        msgrelay_learn.reset()

    def test_record_and_stats(self):
        self.assertTrue(msgrelay_learn.record_feedback(
            "m1", "confirmed", "明天開會", "event", "開會"))
        self.assertFalse(msgrelay_learn.record_feedback(
            "m1", "confirmed", "明天開會", "event", "開會"))  # duplicate
        stats = msgrelay_learn.get_stats()
        self.assertEqual(stats["confirmed"], 1)
        self.assertEqual(stats["positive_examples"], 1)

    def test_record_ignored(self):
        msgrelay_learn.record_feedback("m2", "ignored", "今日天氣好好", "event", "今日天氣好好")
        stats = msgrelay_learn.get_stats()
        self.assertEqual(stats["ignored"], 1)

    def test_few_shot_examples_shape(self):
        msgrelay_learn.record_feedback("m1", "confirmed", "明天開會", "event", "開會")
        msgrelay_learn.record_feedback("m2", "ignored", "今日天氣好好", "event", "今日天氣好好")
        ex = msgrelay_learn.get_few_shot_examples()
        self.assertEqual(len(ex["positive"]), 1)
        self.assertEqual(len(ex["negative"]), 1)
        self.assertIn("items", ex["positive"][0])
        self.assertEqual(ex["negative"][0]["items"], [])

    def test_pattern_penalty_applied_after_two_ignores(self):
        item = {"type": "event", "confidence": 0.8, "title": "今日天氣好好"}
        # One ignore → no penalty
        msgrelay_learn.record_feedback("m1", "ignored", "今日天氣好好", "event", "今日天氣好好")
        out = msgrelay_learn.apply_pattern_penalties([dict(item)], "今日天氣好好")
        self.assertEqual(out[0]["confidence"], 0.8)
        # Second ignore of same title → penalty
        msgrelay_learn.record_feedback("m2", "ignored", "今日天氣好好呀", "event", "今日天氣好好")
        out = msgrelay_learn.apply_pattern_penalties([dict(item)], "今日天氣好好呀")
        self.assertLess(out[0]["confidence"], 0.8)

    def test_penalty_does_not_affect_unrelated(self):
        msgrelay_learn.record_feedback("m1", "ignored", "今日天氣好好", "event", "今日天氣好好")
        msgrelay_learn.record_feedback("m2", "ignored", "今日天氣好好呀", "event", "今日天氣好好")
        item = {"type": "task", "confidence": 0.9, "title": "交report"}
        out = msgrelay_learn.apply_pattern_penalties([item], "交report")
        self.assertEqual(out[0]["confidence"], 0.9)


class TestUnifiedExtraction(unittest.TestCase):

    def test_extract_all_rules_only(self):
        """Without LLM config, extract_all uses rules and returns sane output."""
        os.environ.pop("MSGRELAY_LLM_API_KEY", None)
        os.environ.pop("MSGRELAY_LLM_BASE_URL", None)
        import msgrelay_extract
        msgs = [
            {"msg_id": "a1", "text": "聽日下晝3點開會傾project進度", "sender": "A",
             "chat": "c", "ts": 0, "from_me": 0, "media_type": ""},
            {"msg_id": "a2", "text": "今日天氣好好", "sender": "B",
             "chat": "c", "ts": 0, "from_me": 0, "media_type": ""},
        ]
        out = msgrelay_extract.extract_all(msgs)
        self.assertIn("a1", out)
        self.assertTrue(any(i["type"] == "event" for i in out["a1"]))
        self.assertEqual(out["a2"], [])  # noise stays empty

    def test_extract_all_with_llm_mock(self):
        """When LLM is enabled, its output merges with rules."""
        os.environ["MSGRELAY_LLM_API_KEY"] = "sk-test"
        import msgrelay_extract
        fake_response = {"b1": [{"type": "event", "subtype": "meeting",
                                 "confidence": 0.97, "title": "Team sync",
                                 "date": None, "time": None, "due_date": None}]}
        with mock.patch("msgrelay_llm.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": json.dumps(fake_response)}}]}
            msgs = [{"msg_id": "b1", "text": "tomorrow 2pm meeting with team",
                     "sender": "A", "chat": "c", "ts": 0, "from_me": 0, "media_type": ""}]
            out = msgrelay_extract.extract_all(msgs)
        self.assertIn("b1", out)
        self.assertTrue(any(i["type"] == "event" for i in out["b1"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
