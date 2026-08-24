#!/usr/bin/env python3
"""
Google Tasks integration for wacli.
Reads extracted tasks from NLP engine and creates Google Tasks.
"""
from __future__ import annotations

import os
import sys
import json
import pickle
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wacli_config import (
    get_google_credentials, load_processed, save_processed,
    TOKEN_FILE, get_accounts, EVENT_PREFIX
)
from wacli_nlp_extract import get_new_messages
from msgrelay_extract import extract_all
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

TASK_SCOPES = ["https://www.googleapis.com/auth/tasks"]
TASK_LIST_NAME = "WhatsApp Tasks"


def get_tasks_service():
    """Authenticate and return Google Tasks service."""
    creds = None
    task_token = TOKEN_FILE.replace("google_token.json", "google_token_tasks.json")

    if os.path.exists(task_token):
        with open(task_token, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials = get_google_credentials()
            flow = InstalledAppFlow.from_client_config(credentials, TASK_SCOPES)
            creds = flow.run_local_server(host="localhost", port=5678, open_browser=True)

        with open(task_token, "wb") as token:
            pickle.dump(creds, token)

    return build("tasks", "v1", credentials=creds)


def get_or_create_task_list(service) -> str:
    """Get or create the WhatsApp Tasks list."""
    lists = service.tasklists().list(maxResults=50).execute()
    for tl in lists.get("items", []):
        if tl["title"] == TASK_LIST_NAME:
            return tl["id"]

    # Create new list
    new_list = service.tasklists().insert(
        body={"title": TASK_LIST_NAME}
    ).execute()
    print(f"  📋 Created task list: {TASK_LIST_NAME}")
    return new_list["id"]


def task_exists(service, task_list_id: str, title: str) -> bool:
    """Check if a similar task already exists."""
    try:
        tasks = service.tasks().list(
            tasklist=task_list_id, maxResults=20
        ).execute()
        for t in tasks.get("items", []):
            if t.get("title", "") == title:
                return True
    except Exception:
        pass
    return False


def create_task(service, task_list_id: str, item: dict) -> str | None:
    """Create a Google Task. Returns task ID or None."""
    try:
        title = f"{EVENT_PREFIX} {item['title'][:80]}"
        source = item.get("source_chat", "WhatsApp")

        if task_exists(service, task_list_id, title):
            return None

        task_body = {
            "title": title,
            "notes": (
                f"From: {item.get('source_sender', 'Unknown')} ({source})\n"
                f"---\n{item.get('source_text', '')[:200]}"
            ),
        }

        if item.get("due_date"):
            # Google Tasks API uses RFC 3339 with date-only for due dates
            due = item["due_date"].split("T")[0] + "T00:00:00.000Z"
            task_body["due"] = due

        task = service.tasks().insert(tasklist=task_list_id, body=task_body).execute()
        return task.get("id")

    except Exception as e:
        print(f"  ⚠️  Failed to create task: {e}")
        return None


def process_account(service, task_list_id: str, db_path: str,
                    account_name: str, processed: dict):
    """Process one wacli account for tasks."""
    since_ts = processed.get(account_name, {}).get("last_tasks_ts", 0)
    if since_ts == 0:
        since_ts = int((datetime.now() - timedelta(hours=4)).timestamp())

    messages = get_new_messages(db_path, since_ts, limit=100)
    if not messages:
        return 0

    # Unified extraction: rules + optional LLM + learned penalties
    all_items = extract_all(messages)

    created = 0
    max_ts = since_ts

    for msg in messages:
        msg_id = msg["msg_id"]
        if msg_id in processed.get(account_name, {}).get("task_msg_ids", {}):
            continue

        items = all_items.get(msg_id, [])

        for item in items:
            if item["type"] != "task" or item["confidence"] < 0.65:
                continue

            task_id = create_task(service, task_list_id, item)
            if task_id:
                created += 1
                print(f"  ✅ Created: {item['title'][:60]}")

            processed.setdefault(account_name, {}).setdefault("task_msg_ids", {})[msg_id] = True

        max_ts = max(max_ts, msg["ts"])

    processed.setdefault(account_name, {})["last_tasks_ts"] = max_ts
    return created


def main():
    parser = argparse.ArgumentParser(description="wacli → Google Tasks")
    parser.add_argument("--auth", action="store_true", help="Run OAuth flow only")
    parser.add_argument("--init", action="store_true", help="Create task list")
    args = parser.parse_args()

    print("🔐 Authenticating Google Tasks...")
    service = get_tasks_service()

    if args.auth:
        print("✅ OAuth complete.")
        return

    task_list_id = get_or_create_task_list(service)
    print(f"✅ Task list ready (ID: {task_list_id[:20]}...)")

    if args.init:
        return

    processed = load_processed()

    accounts = get_accounts()
    if not accounts:
        print("  ⚠️  No accounts found. Check ~/.wacli/config.yaml")
        return

    for acct in accounts:
        db_path = acct["db"]
        name = acct["name"]
        if not os.path.exists(db_path):
            print(f"  ⚠️  {name} DB not found: {db_path}")
            continue
        print(f"\n📱 Processing {name} account...")
        created = process_account(service, task_list_id, db_path, name, processed)
        print(f"  ✅ {name}: {created} task(s) created")

    save_processed(processed)
    print("\n✨ Done!")


if __name__ == "__main__":
    main()
