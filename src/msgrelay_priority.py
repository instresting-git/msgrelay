#!/usr/bin/env python3
"""
MsgRelay priority learning engine.

Learns which senders (people/chats) produce high-priority work and stores a
sender_weights knowledge base — the same pattern as the original
wacli-priority-learning system, but self-contained and open-source.

Three ways to update weights:
  1. LLM learning (--learn): analyze recent messages with the configured LLM
     and merge the resulting sender weights (daily cron recommended).
  2. Manual (--set): explicitly set a sender's priority.
  3. Stats fallback (--learn-rules): without an LLM, derive weights from
     actual task-production statistics (no external calls).

Storage: <MSGRELAY_HOME>/scripts/msgrelay_priority_rules.json

CLI:
    python3 msgrelay_priority.py --list
    python3 msgrelay_priority.py --set "Alice" --priority high [--confidence 0.9]
    python3 msgrelay_priority.py --learn --messages-file msgs.json   # LLM
    python3 msgrelay_priority.py --learn-rules --messages-file msgs.json  # stats
    python3 msgrelay_priority.py --priority "Alice"   # quick lookup
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from wacli_config import SCRIPTS_DIR
from msgrelay_llm import get_llm_config

PRIORITY_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_priority_rules.json")

DEFAULT_WEIGHT = "medium"
LEARN_SYSTEM_PROMPT = """You are MsgRelay's priority learning engine.
Analyze the WhatsApp messages (each tagged with a sender) and produce sender priority weights.

For each sender output:
{"sender": "<name>", "default_priority": "high|medium|low", "confidence": 0.0-1.0, "reason": "<one line>"}

Criteria:
- high: consistently creates tasks/deadlines, escalations, operational impact, multi-step coordination
- medium: regular contributor with occasional action items
- low: chit-chat, rarely produces actionable items

Only include senders present in the messages. Output STRICT JSON only:
{"senders": [...]}
No markdown, no commentary."""


def _now() -> str:
    return datetime.now().isoformat()


def _load() -> dict:
    if os.path.exists(PRIORITY_FILE):
        try:
            with open(PRIORITY_FILE) as f:
                data = json.load(f)
            data.setdefault("sender_weights", {})
            data.setdefault("version", 0)
            return data
        except Exception:
            pass
    return {"version": 0, "updated_at": None, "sender_weights": {}}


def _save(data: dict):
    os.makedirs(os.path.dirname(PRIORITY_FILE), exist_ok=True)
    with open(PRIORITY_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_sender_priority(sender: str) -> dict:
    """
    Look up a sender's priority. Returns
    {"priority": "high|medium|low", "confidence": 0-1, "source": "learned|default"}.
    """
    data = _load()
    w = data["sender_weights"].get(sender)
    if w:
        return {"priority": w.get("default_priority", DEFAULT_WEIGHT),
                "confidence": w.get("confidence", 0.5),
                "source": "learned"}
    return {"priority": DEFAULT_WEIGHT, "confidence": 0.3, "source": "default"}


def set_sender_priority(sender: str, priority: str, confidence: float = 0.8,
                        reason: str = "") -> None:
    data = _load()
    data["sender_weights"][sender] = {
        "default_priority": priority,
        "confidence": confidence,
        "reason": reason,
        "updated_at": _now(),
    }
    data["updated_at"] = _now()
    data["version"] = data.get("version", 0) + 1
    _save(data)


def _merge_weights(existing: dict, new_weights: list[dict]) -> int:
    """Merge LLM/stats weights into the knowledge base. Newer higher-confidence wins."""
    updated = 0
    for w in new_weights:
        sender = w.get("sender", "")
        if not sender:
            continue
        priority = w.get("default_priority", DEFAULT_WEIGHT)
        if priority not in ("high", "medium", "low"):
            continue
        confidence = float(w.get("confidence", 0.5))
        old = existing.get(sender)
        if old is None or confidence >= float(old.get("confidence", 0)):
            existing[sender] = {
                "default_priority": priority,
                "confidence": confidence,
                "reason": w.get("reason", ""),
                "updated_at": _now(),
            }
            updated += 1
    return updated


def learn_with_llm(messages: list[dict]) -> dict:
    """
    Learn sender weights via the configured LLM.

    Args:
        messages: [{"sender": "...", "text": "..."}]

    Returns {"updated": n, "llm": bool} — llm False when LLM unavailable.
    """
    import requests

    config = get_llm_config()
    if config is None:
        return {"updated": 0, "llm": False}

    # Batch senders into one request (cap message size)
    lines = []
    for i, m in enumerate(messages[:40]):
        lines.append(f'[{i}] (sender: {m.get("sender","?")}) "{m.get("text","")[:200]}"')
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": LEARN_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ],
        "temperature": 0.0,
    }
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"

    resp = requests.post(config["base_url"], json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    import re
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
    data = json.loads(content)
    senders = data.get("senders", [])

    kb = _load()
    updated = _merge_weights(kb["sender_weights"], senders)
    kb["updated_at"] = _now()
    kb["version"] = kb.get("version", 0) + 1
    _save(kb)
    return {"updated": updated, "llm": True}


def learn_with_stats(messages: list[dict]) -> dict:
    """
    Fallback learning without an LLM: derive weights from task-production stats.

    A sender is high priority if they produce >= 3 task-like messages in the
    window; medium if >= 1; otherwise left unchanged (default medium).
    """
    from wacli_nlp_extract import analyze_message

    counts: dict[str, int] = {}
    for m in messages:
        items = analyze_message(m.get("text", ""), m.get("sender", ""), "",
                                "s", 0, False, "")
        if any(i["type"] == "task" for i in items):
            sender = m.get("sender", "?")
            counts[sender] = counts.get(sender, 0) + 1

    weights = []
    for sender, n in counts.items():
        if n >= 3:
            weights.append({"sender": sender, "default_priority": "high",
                            "confidence": min(0.5 + 0.1 * n, 0.9), "reason": f"{n} tasks in window"})
        elif n >= 1:
            weights.append({"sender": sender, "default_priority": "medium",
                            "confidence": 0.5, "reason": f"{n} tasks in window"})

    kb = _load()
    updated = _merge_weights(kb["sender_weights"], weights)
    if updated:
        kb["updated_at"] = _now()
        kb["version"] = kb.get("version", 0) + 1
        _save(kb)
    return {"updated": updated, "llm": False}


def main():
    p = argparse.ArgumentParser(description="MsgRelay priority learning")
    p.add_argument("--list", action="store_true", help="list all sender weights")
    p.add_argument("--priority", metavar="SENDER", help="lookup one sender")
    p.add_argument("--set", metavar="SENDER")
    p.add_argument("--priority-value", choices=["high", "medium", "low"])
    p.add_argument("--confidence", type=float, default=0.8)
    p.add_argument("--reason", default="")
    p.add_argument("--learn", action="store_true", help="LLM learning from messages file")
    p.add_argument("--learn-rules", action="store_true", help="stats fallback learning")
    p.add_argument("--messages-file", default="", help="JSON list of {sender, text}")
    args = p.parse_args()

    if args.list:
        kb = _load()
        for sender, w in sorted(kb["sender_weights"].items()):
            print(f"{sender:24} {w.get('default_priority','?'):6} "
                  f"conf={w.get('confidence',0):.2f}  {w.get('reason','')[:50]}")
        return
    if args.priority:
        r = get_sender_priority(args.priority)
        print(f"{args.priority}: {r['priority']} (conf={r['confidence']:.2f}, {r['source']})")
        return
    if args.set:
        if not args.priority_value:
            p.error("--priority-value required with --set")
        set_sender_priority(args.set, args.priority_value, args.confidence, args.reason)
        print(f"set {args.set} → {args.priority_value}")
        return
    if args.learn or args.learn_rules:
        if not args.messages_file:
            p.error("--messages-file required (JSON list of {sender, text})")
        with open(args.messages_file) as f:
            messages = json.load(f)
        if args.learn:
            result = learn_with_llm(messages)
            if not result["llm"]:
                print("LLM not configured — run with --learn-rules or configure MSGRELAY_LLM_*")
        else:
            result = learn_with_stats(messages)
        print(f"updated {result['updated']} sender weight(s)")
        return
    p.print_help()


if __name__ == "__main__":
    main()
