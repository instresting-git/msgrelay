"""
Tests for the LLM agent runner (prompt workflows).
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

import msgrelay_agent


class TestPromptAssets(unittest.TestCase):

    def test_all_workflow_files_exist(self):
        d = msgrelay_agent.prompts_dir()
        for name, fname in msgrelay_agent.WORKFLOWS.items():
            path = os.path.join(d, fname)
            self.assertTrue(os.path.exists(path), f"missing {fname}")
            content = open(path).read()
            self.assertGreater(len(content), 200, f"{fname} too short")

    def test_load_prompt(self):
        p = msgrelay_agent.load_prompt("calendar-tasks")
        self.assertIsNotNone(p)
        self.assertIn("STRICT JSON", p)
        self.assertIsNone(msgrelay_agent.load_prompt("nope"))


class TestResponseParsing(unittest.TestCase):

    def test_parse_action_list(self):
        content = '[{"action": "create_event", "title": "開會", "date": "2026-08-25", "time": "15:00", "due_date": null, "priority": "high", "group": null, "confidence": 0.95, "source_id": "m1"}]'
        data = msgrelay_agent._parse_json_response(content)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["action"], "create_event")

    def test_parse_with_fences(self):
        content = '```json\n{"senders": [{"sender": "A", "default_priority": "high"}]}\n```'
        data = msgrelay_agent._parse_json_response(content)
        self.assertEqual(data["senders"][0]["sender"], "A")

    def test_parse_empty_array(self):
        self.assertEqual(msgrelay_agent._parse_json_response("[]"), [])

    def test_parse_garbage(self):
        self.assertIsNone(msgrelay_agent._parse_json_response("nothing here"))


class TestAgentRunner(unittest.TestCase):

    def test_run_workflow_not_configured(self):
        os.environ.pop("MSGRELAY_LLM_API_KEY", None)
        os.environ.pop("MSGRELAY_LLM_BASE_URL", None)
        result = msgrelay_agent.run_workflow("calendar-tasks", [{"id": "1", "text": "hi"}])
        self.assertIsNone(result)  # LLM off → None (caller can fall back)

    def test_run_workflow_mock_success(self):
        os.environ["MSGRELAY_LLM_API_KEY"] = "sk-test"
        os.environ["MSGRELAY_LLM_BASE_URL"] = "https://api.deepseek.com/v1"
        fake = [{"action": "create_event", "title": "開會", "date": "2026-08-25",
                 "time": "15:00", "due_date": None, "priority": "high",
                 "group": None, "confidence": 0.95, "source_id": "m1"}]
        with mock.patch("msgrelay_agent.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": json.dumps(fake)}}]}
            result = msgrelay_agent.run_workflow(
                "calendar-tasks",
                [{"id": "m1", "sender": "A", "chat": "c", "text": "聽日下晝3點開會"}])
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"][0]["action"], "create_event")

    def test_run_workflow_http_error(self):
        os.environ["MSGRELAY_LLM_API_KEY"] = "sk-test"
        with mock.patch("msgrelay_agent.requests.post",
                        side_effect=Exception("timeout")):
            result = msgrelay_agent.run_workflow("extract", [{"id": "1", "text": "x"}])
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_unknown_workflow(self):
        os.environ["MSGRELAY_LLM_API_KEY"] = "sk-test"
        result = msgrelay_agent.run_workflow("nope", [])
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
