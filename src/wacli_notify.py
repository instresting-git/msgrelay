#!/usr/bin/env python3
"""
Standardized Discord webhook sender for wacli cron jobs.

Why this exists:
  - Single, deterministic send path (replaces hand-rolled `curl` inside LLM prompts).
  - Webhook URL read from secrets (never hardcoded in prompts → not exposed to the model).
  - At-most-once per run: content-hash dedup suppresses an identical notification
    re-sent within DEDUP_WINDOW seconds (stops the LLM from double-firing in one run).

Usage:
  echo '{"content":"hello"}' | python3 wacli_notify.py
  echo '{"embeds":[...]}'    | python3 wacli_notify.py
  python3 wacli_notify.py --content "hello"
  python3 wacli_notify.py --file /tmp/wacli_notify.json

Exit codes:
  0  sent OK (or identical duplicate suppressed)
  1  discord_webhook_url missing in secrets
  2  no content/embeds provided
  3  Discord API returned an error
"""
import argparse
import fcntl
import hashlib
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wacli_config import _load_secrets  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SENTINEL_FILE = os.path.join(SCRIPTS_DIR, ".discord_notify_sentinel.json")
SENTINEL_LOCK = SENTINEL_FILE + ".lock"
DEDUP_WINDOW = 300  # seconds


def get_webhook_url() -> str:
    return _load_secrets().get("discord_webhook_url", "")


def _read_sentinel() -> dict:
    try:
        with open(SENTINEL_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_sentinel(data: dict) -> None:
    with open(SENTINEL_FILE, "w") as f:
        json.dump(data, f)


def _with_lock(fn):
    os.makedirs(os.path.dirname(SENTINEL_LOCK), exist_ok=True)
    with open(SENTINEL_LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _is_duplicate(payload_hash: str, now: float) -> bool:
    def check():
        sentinel = _read_sentinel()
        last_ts = sentinel.get(payload_hash, 0)
        return (now - last_ts) < DEDUP_WINDOW

    return _with_lock(check)


def _record(payload_hash: str, now: float) -> None:
    def record():
        sentinel = _read_sentinel()
        # prune entries older than 24h to keep the file tiny
        sentinel = {h: ts for h, ts in sentinel.items() if now - ts < 86400}
        sentinel[payload_hash] = now
        _write_sentinel(sentinel)

    _with_lock(record)


def send(payload: dict) -> None:
    webhook_url = get_webhook_url()
    if not webhook_url:
        print("NO_WEBHOOK: discord_webhook_url missing in wacli_secrets.json")
        sys.exit(1)

    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    now = time.time()

    if _is_duplicate(payload_hash, now):
        print("DUPLICATE_SKIPPED: identical notification already sent within dedup window")
        sys.exit(0)

    resp = requests.post(webhook_url, json=payload, timeout=15)
    if resp.status_code in (200, 204):
        _record(payload_hash, now)
        print(f"SENT: Discord {resp.status_code}")
        sys.exit(0)

    print(f"ERROR: Discord {resp.status_code}: {resp.text[:200]}")
    sys.exit(3)


def main() -> None:
    global DEDUP_WINDOW
    p = argparse.ArgumentParser(description="Standardized Discord webhook sender (dedup + single send)")
    p.add_argument("--content", help="plain markdown text content")
    p.add_argument("--file", help="JSON file containing content/embeds")
    p.add_argument("--dedup-window", type=int, default=DEDUP_WINDOW, help="dedup window in seconds")
    args = p.parse_args()
    DEDUP_WINDOW = args.dedup_window

    payload = None
    if args.file:
        with open(args.file) as f:
            payload = json.load(f)
    elif args.content:
        payload = {"content": args.content}
    else:
        raw = sys.stdin.read().strip()
        if raw:
            payload = json.loads(raw)

    if not payload:
        print("NO_CONTENT: nothing to send")
        sys.exit(2)

    # accept {"text": ...} as an alias for {"content": ...}
    if "text" in payload and "content" not in payload:
        payload["content"] = payload.pop("text")

    if not payload.get("content") and not payload.get("embeds"):
        print("NO_CONTENT: payload must contain 'content' or 'embeds'")
        sys.exit(2)

    send(payload)


if __name__ == "__main__":
    main()
