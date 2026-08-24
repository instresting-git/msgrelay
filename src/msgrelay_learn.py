#!/usr/bin/env python3
"""
MsgRelay auto-learn engine.

Learns from user feedback (confirmed / ignored) and personalizes extraction:

1. Feedback recording — a user tells MsgRelay whether an extracted item was
   right (confirmed) or wrong (ignored).
2. Few-shot library — confirmed/ignored examples are injected into the LLM
   prompt so the model learns the user's preferences.
3. Pattern penalties — regex results that repeatedly match ignored examples
   get their confidence reduced (rules engine correction).

Storage: <MSGRELAY_HOME>/scripts/msgrelay_learn.json  (local, private)

CLI:
    python3 msgrelay_learn.py --feedback <msg_id> --action confirmed|ignored \
        [--type event|task] [--title "..."]
    python3 msgrelay_learn.py --stats
    python3 msgrelay_learn.py --reset
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from wacli_config import SCRIPTS_DIR

LEARN_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_learn.json")

EMPTY = {"positive": [], "negative": [], "stats": {"confirmed": 0, "ignored": 0}}


def _load() -> dict:
    if os.path.exists(LEARN_FILE):
        try:
            with open(LEARN_FILE) as f:
                data = json.load(f)
            data.setdefault("positive", [])
            data.setdefault("negative", [])
            data.setdefault("stats", {"confirmed": 0, "ignored": 0})
            return data
        except Exception:
            pass
    return json.loads(json.dumps(EMPTY))


def _save(data: dict):
    os.makedirs(os.path.dirname(LEARN_FILE), exist_ok=True)
    with open(LEARN_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def record_feedback(msg_id: str, action: str, text: str = "",
                    item_type: str = "", title: str = "") -> bool:
    """
    Record one piece of user feedback.

    Args:
        msg_id:   source WhatsApp message id
        action:   "confirmed" or "ignored"
        text:     original message text
        item_type: "event" / "task"
        title:    extracted title

    Returns True if recorded (new), False if duplicate.
    """
    if action not in ("confirmed", "ignored"):
        print(f"  ✗ unknown action: {action} (use confirmed|ignored)", file=sys.stderr)
        return False

    data = _load()
    bucket = "positive" if action == "confirmed" else "negative"

    # Dedupe: same msg_id + type already recorded → update instead of append
    for entry in data[bucket]:
        if entry.get("msg_id") == msg_id and entry.get("type", "") == item_type:
            entry.update({"text": text, "title": title, "ts": int(time.time())})
            _save(data)
            return False

    data[bucket].append({
        "msg_id": msg_id, "text": text, "type": item_type,
        "title": title, "ts": int(time.time()),
    })
    data["stats"]["confirmed" if action == "confirmed" else "ignored"] += 1
    _save(data)
    return True


def get_few_shot_examples(n_pos: int = 3, n_neg: int = 2) -> dict:
    """
    Return recent examples for LLM few-shot prompting.

    Returns:
        {"positive": [{"text": ..., "items": [item...]}],
         "negative": [{"text": ..., "items": []}]}
    """
    data = _load()
    pos = []
    for e in data["positive"][-n_pos:]:
        pos.append({"text": e.get("text", ""), "items": [{
            "type": e.get("type", "event"),
            "subtype": "",
            "confidence": 0.9,
            "title": e.get("title", ""),
        }]})
    neg = [{"text": e.get("text", ""), "items": []}
           for e in data["negative"][-n_neg:]]
    return {"positive": pos, "negative": neg}


def apply_pattern_penalties(items: list[dict], text: str) -> list[dict]:
    """
    Apply learned penalties to regex-engine results.

    If the same extracted title appears >= 2 times in the ignored bucket,
    penalize its confidence (the user keeps rejecting this pattern).
    """
    if not items:
        return items
    data = _load()
    if not data["negative"]:
        return items

    # Count ignored titles (normalized)
    ignored_counts: dict[str, int] = {}
    for e in data["negative"]:
        t = (e.get("title") or "").strip().lower()
        if t:
            ignored_counts[t] = ignored_counts.get(t, 0) + 1

    out = []
    for it in items:
        title = (it.get("title") or "").strip().lower()
        if ignored_counts.get(title, 0) >= 2:
            it["confidence"] = round(it.get("confidence", 0.5) * 0.6, 2)
            print(f"  🧠 learned: '{title}' was ignored before, penalized to {it['confidence']}")
        out.append(it)
    return out


def get_stats() -> dict:
    data = _load()
    return {
        "confirmed": data["stats"].get("confirmed", 0),
        "ignored": data["stats"].get("ignored", 0),
        "positive_examples": len(data["positive"]),
        "negative_examples": len(data["negative"]),
        "learn_file": LEARN_FILE,
    }


def reset() -> None:
    _save(json.loads(json.dumps(EMPTY)))
    print("🧠 Learning data reset.")


def main():
    p = argparse.ArgumentParser(description="MsgRelay auto-learn engine")
    p.add_argument("--feedback", metavar="MSG_ID")
    p.add_argument("--action", choices=["confirmed", "ignored"])
    p.add_argument("--text", default="", help="original message text")
    p.add_argument("--type", default="", help="event or task")
    p.add_argument("--title", default="", help="extracted title")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()

    if args.reset:
        reset()
        return
    if args.stats:
        print(json.dumps(get_stats(), indent=2, ensure_ascii=False))
        return
    if args.feedback and args.action:
        ok = record_feedback(args.feedback, args.action, args.text,
                             args.type, args.title)
        print("✅ recorded" if ok else "ℹ️  duplicate — updated")
        return
    p.print_help()


if __name__ == "__main__":
    main()
