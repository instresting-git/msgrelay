#!/usr/bin/env python3
"""
Lark (Feishu International) Tasks integration for wacli.
Reads extracted tasks from NLP engine and creates Lark Tasks.
"""
from __future__ import annotations

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wacli_config import (
    _load_secrets, load_processed, save_processed,
    SCRIPTS_DIR, get_accounts
)
from wacli_nlp_extract import get_new_messages, analyze_message

# Lark API base URL (international)
LARK_BASE = "https://open.larksuite.com/open-apis"
TASK_BASE = f"{LARK_BASE}/task/v2"  # v2 is the working version
AUTH_URL = f"{LARK_BASE}/auth/v3/tenant_access_token/internal"

# Target user (for task assignment)
LARK_USER_ID = os.environ.get("MSGRELAY_LARK_USER_ID", "") or _load_secrets().get("lark_user_id", "")

# Token cache
_token_cache = {"token": None, "expires_at": 0}


def get_tenant_token() -> str:
    """Get or refresh Lark tenant access token."""
    global _token_cache
    now = time.time()

    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    secrets = _load_secrets()
    app_id = secrets.get("lark_app_id", "")
    app_secret = secrets.get("lark_app_secret", "")

    if not app_id or not app_secret:
        raise RuntimeError("Lark credentials missing in wacli_secrets.json")

    resp = requests.post(AUTH_URL, json={
        "app_id": app_id,
        "app_secret": app_secret,
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Lark auth failed: {data.get('msg', 'unknown')}")

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = now + data.get("expire", 7200) - 300
    return _token_cache["token"]


def lark_headers() -> dict:
    """Standard Lark API headers."""
    return {
        "Authorization": f"Bearer {get_tenant_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def get_or_create_task_list() -> str:
    """Get or create the WhatsApp Tasks task list."""
    # Lark Tasks don't have a "task list" concept like Google Tasks.
    # Tasks are flat per-app. We'll use a custom field or list_name.
    # For now, just return a fixed identifier.
    return "wacli_tasks"


def task_exists(title: str) -> bool:
    """Check if a similar task already exists."""
    try:
        resp = requests.get(
            f"{TASK_BASE}/tasks",
            headers=lark_headers(),
            params={"page_size": 20},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            return False

        for t in data.get("data", {}).get("items", []):
            if title[:40] in (t.get("summary", "") or ""):
                return True
    except Exception:
        pass
    return False


def create_task(item: dict) -> str | None:
    """Create a Lark Task. Returns task ID or None."""
    try:
        title = f"[WA] {item['title'][:80]}"
        source = item.get("source_chat", "WhatsApp")

        if task_exists(title):
            return None

        task_body = {
            "summary": title,
            "description": (
                f"From: {item.get('source_sender', 'Unknown')} ({source})\n"
                f"---\n{item.get('source_text', '')[:200]}"
            ),
            "members": [
                {"id": LARK_USER_ID, "type": "user", "role": "assignee"}
            ],
        }

        # Add due date if available
        if item.get("due_date"):
            due_date = item["due_date"].split("T")[0]  # YYYY-MM-DD
            due_ts = int(datetime.strptime(due_date, "%Y-%m-%d").timestamp())
            task_body["due"] = {
                "timestamp": str(due_ts),  # v2 uses "timestamp" not "time"
            }

        resp = requests.post(
            f"{TASK_BASE}/tasks",
            headers=lark_headers(),
            json=task_body,
            timeout=15,
        )
        data = resp.json()

        if data.get("code") != 0:
            print(f"  ⚠️  Create task failed ({data.get('code')}): {data.get('msg')}")
            return None

        return data["data"]["task"]["guid"]  # v2 uses guid

    except Exception as e:
        print(f"  ⚠️  Failed to create task: {e}")
        return None


def process_account(db_path: str, account_name: str, processed: dict):
    """Process one wacli account for tasks."""
    since_ts = processed.get(account_name, {}).get("last_tasks_ts", 0)
    if since_ts == 0:
        since_ts = int((datetime.now() - timedelta(hours=4)).timestamp())

    messages = get_new_messages(db_path, since_ts, limit=100)
    if not messages:
        return 0

    created = 0
    max_ts = since_ts

    for msg in messages:
        msg_id = msg["msg_id"]
        if msg_id in processed.get(account_name, {}).get("task_msg_ids", {}):
            continue

        items = analyze_message(
            msg["text"], msg["sender"], msg["chat"],
            msg_id, msg["ts"], bool(msg["from_me"]), msg["media_type"]
        )

        for item in items:
            if item["type"] != "task" or item["confidence"] < 0.65:
                continue

            task_id = create_task(item)
            if task_id:
                created += 1
                print(f"  ✅ Created: {item['title'][:60]}")

            processed.setdefault(account_name, {}).setdefault(
                "task_msg_ids", {})[msg_id] = True

        max_ts = max(max_ts, msg["ts"])

    processed.setdefault(account_name, {})["last_tasks_ts"] = max_ts
    return created


def main():
    parser = argparse.ArgumentParser(description="wacli → Lark Tasks")
    args = parser.parse_args()

    print("🔐 Authenticating Lark...")
    token = get_tenant_token()
    print(f"✅ Connected (token: {token[:10]}...)")

    # Get or create task list
    list_id = get_or_create_task_list()
    print(f"✅ Task list ready")

    processed = load_processed()

    for acct in get_accounts():
        name, db_path = acct["name"], acct["db"]
        if not os.path.exists(db_path):
            print(f"  ⚠️  {name} DB not found: {db_path}")
            continue
        print(f"\n📱 Processing {name} account...")
        created = process_account(db_path, name, processed)
        print(f"  ✅ {name}: {created} task(s) created")

    save_processed(processed)
    print("\n✨ Done!")


if __name__ == "__main__":
    main()
