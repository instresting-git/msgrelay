#!/usr/bin/env python3
"""
MsgRelay LLM extraction engine (optional).

Uses any OpenAI-compatible chat API (OpenAI, DeepSeek, Ollama, LM Studio, ...)
to extract events/tasks from WhatsApp messages with real language understanding —
beyond what the regex engine can do.

Design:
- OPT-IN: only active when an API key/base URL is configured (secrets or env).
- Batch: multiple messages per request to save tokens.
- Strict JSON output, parsed defensively.
- Fail-safe: any error → returns None, caller falls back to the regex engine.
- Privacy: message text is sent to YOUR configured API provider only when you
  enable this feature. Local models (Ollama) keep data on your machine.

Env / secrets config (secrets file wins):
    MSGRELAY_LLM_BASE_URL  or secrets["llm_base_url"]   default: https://api.openai.com/v1
    MSGRELAY_LLM_API_KEY   or secrets["llm_api_key"]
    MSGRELAY_LLM_MODEL     or secrets["llm_model"]     default: gpt-4o-mini
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

import requests

from wacli_config import _load_secrets

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
TIMEOUT_SECONDS = 20
MAX_BATCH = 10  # messages per request

SYSTEM_PROMPT = """You are MsgRelay, an information extraction engine for WhatsApp messages.
Extract calendar events and tasks (with deadlines) from each message.

Rules:
- Languages: Simplified/Traditional Chinese, Cantonese, English, or mixed.
- Output STRICT JSON only — an object keyed by message id, no markdown, no commentary:
  {"<msg_id>": [{"type": "event|task", "subtype": "meeting|meal|deadline|action", "confidence": 0.0-1.0, "title": "short title", "date": "YYYY-MM-DD or null", "time": "HH:MM or null", "due_date": "YYYY-MM-DD or null"}]}
- Only extract when intent is clear; otherwise use an empty array for that id.
- Chit-chat ("how are you", "weather is nice", "今日天氣好好") → empty array.
- Resolve relative dates (tomorrow, 聽日, 下星期三, 今晚) to concrete dates relative to today: {today}
- Resolve relative times (下晝3點 → 15:00, 2pm → 14:00, 10點半 → 10:30).
- A deadline ("deadline", "截止", "之前要") is a TASK with due_date, not an event.
- Keep title short (<= 40 chars), in the original language."""


def get_llm_config() -> dict | None:
    """Return LLM config, or None if the feature is not enabled."""
    secrets = {}
    try:
        secrets = _load_secrets()
    except Exception:
        pass

    api_key = os.environ.get("MSGRELAY_LLM_API_KEY") or secrets.get("llm_api_key", "")
    base_url = os.environ.get("MSGRELAY_LLM_BASE_URL") or secrets.get("llm_base_url", "")
    model = os.environ.get("MSGRELAY_LLM_MODEL") or secrets.get("llm_model", "")

    if not api_key and not base_url:
        return None  # feature off by default

    return {
        "api_key": api_key,
        "base_url": (base_url or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions",
        "model": model or DEFAULT_MODEL,
    }


def _build_messages(batch: list[dict], examples: dict | None = None) -> list[dict]:
    """Build the chat messages array for one batch."""
    today = datetime.now().strftime("%Y-%m-%d")
    system = SYSTEM_PROMPT.format(today=today)

    user_parts = []
    if examples:
        pos = examples.get("positive", [])
        neg = examples.get("negative", [])
        if pos:
            lines = "\n".join(f'- "{p["text"]}" → {json.dumps(p["items"], ensure_ascii=False)}'
                              for p in pos[-3:])
            user_parts.append(f"Recent CONFIRMED examples (learn from them):\n{lines}")
        if neg:
            lines = "\n".join(f'- "{n["text"]}" → []' for n in neg[-2:])
            user_parts.append(f"Recent IGNORED examples (do NOT extract these):\n{lines}")

    for m in batch:
        sender = m.get("sender", "unknown")
        text = m.get("text", "")[:500]
        user_parts.append(f'[{m["id"]}] (sender: {sender}) "{text}"')

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def _parse_response(content: str) -> dict | None:
    """Defensively parse the model's JSON response."""
    content = content.strip()
    # Strip markdown fences if present
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try to find the first {...} block
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None

    cleaned = {}
    for k, v in data.items():
        if isinstance(v, list):
            items = []
            for it in v:
                if isinstance(it, dict) and "type" in it:
                    it = {kk: (vv if vv not in (None, "") else None)
                          for kk, vv in it.items()}
                    items.append(it)
            cleaned[str(k)] = items
    return cleaned or None


def llm_extract(messages: list[dict], examples: dict | None = None) -> dict | None:
    """
    Extract items from messages using the configured LLM.

    Args:
        messages: [{"id": "...", "text": "...", "sender": "..."}]
        examples: {"positive": [{"text","items"}], "negative": [{"text","items"}]}

    Returns:
        {"<msg_id>": [items...]} or None on any failure (caller falls back).
    """
    config = get_llm_config()
    if config is None:
        return None

    results: dict[str, list] = {}
    try:
        for i in range(0, len(messages), MAX_BATCH):
            batch = messages[i:i + MAX_BATCH]
            payload = {
                "model": config["model"],
                "messages": _build_messages(batch, examples),
                "temperature": 0.0,
            }
            headers = {"Content-Type": "application/json"}
            if config["api_key"]:
                headers["Authorization"] = f"Bearer {config['api_key']}"

            resp = requests.post(config["base_url"], json=payload,
                                 headers=headers, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = _parse_response(content)
            if parsed:
                results.update(parsed)
            time.sleep(0.2)  # gentle rate limiting
        return results or None
    except Exception as e:
        print(f"  ⚠️  LLM extraction failed (falling back to rules): {e}")
        return None


def merge_with_rules(llm_items: list[dict] | None, rule_items: list[dict]) -> list[dict]:
    """
    Merge LLM and rule results. LLM wins when both exist; rules are the fallback.
    Ensures the final list is non-empty and confidence values are sane.
    """
    if not llm_items:
        return rule_items
    # Normalize LLM items into the same shape as rule items
    out = []
    for it in llm_items:
        if it.get("type") not in ("event", "task"):
            continue
        conf = float(it.get("confidence", 0.5))
        out.append({
            "type": it["type"],
            "subtype": it.get("subtype", ""),
            "confidence": max(0.0, min(1.0, conf)),
            "title": it.get("title") or "",
            "date": it.get("date"),
            "time": it.get("time"),
            "due_date": it.get("due_date"),
            "source_text": it.get("source_text", ""),
        })
    return out or rule_items


if __name__ == "__main__":
    import sys
    cfg = get_llm_config()
    if cfg is None:
        print("LLM not configured — set MSGRELAY_LLM_API_KEY / MSGRELAY_LLM_BASE_URL")
        print("or add llm_api_key / llm_base_url / llm_model to wacli_secrets.json")
        sys.exit(0)
    print(f"LLM enabled: {cfg['model']} @ {cfg['base_url']}")
    test = [{"id": "t1", "text": "聽日下晝3點開會傾project進度", "sender": "A"}]
    r = llm_extract(test)
    print(json.dumps(r, ensure_ascii=False, indent=2) if r else "(failed)")
