#!/usr/bin/env python3
"""
Google Calendar integration for wacli.
Reads extracted events from NLP engine and creates Google Calendar events.
Deduplicates to avoid creating the same event twice.
"""
from __future__ import annotations

import os
import sys
import json
import pickle
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wacli_config import (
    get_google_credentials, load_processed, save_processed,
    TOKEN_FILE, SCRIPTS_DIR, get_accounts, TIMEZONE, EVENT_PREFIX
)
from wacli_nlp_extract import get_new_messages
from msgrelay_extract import extract_all
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    """Authenticate and return Google Calendar service."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials = get_google_credentials()
            flow = InstalledAppFlow.from_client_config(credentials, SCOPES)
            creds = flow.run_local_server(host="localhost", port=5678, open_browser=True)

        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    return build("calendar", "v3", credentials=creds)


def event_exists(service, title: str, date_str: str) -> bool:
    """Check if a similar event already exists to avoid duplicates."""
    try:
        d = datetime.fromisoformat(date_str)
        tmin = (d - timedelta(hours=1)).isoformat() + "Z"
        tmax = (d + timedelta(hours=1)).isoformat() + "Z"

        events = service.events().list(
            calendarId="primary",
            timeMin=tmin,
            timeMax=tmax,
            q=title[:30],
            maxResults=5,
        ).execute()

        for ev in events.get("items", []):
            if title[:20] in (ev.get("summary", "") or ""):
                return True
    except Exception:
        pass
    return False


def create_calendar_event(service, item: dict) -> str | None:
    """Create a Google Calendar event from an extracted item. Returns event ID or None."""
    try:
        title = item["title"]
        source = item.get("source_chat", "WhatsApp")

        # Determine start/end time
        if item.get("date") and item.get("time"):
            start_dt = datetime.fromisoformat(
                f"{item['date'].split('T')[0]}T{item['time']}:00"
            )
            end_dt = start_dt + timedelta(hours=1)
        elif item.get("date"):
            start_dt = datetime.fromisoformat(item["date"]).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            end_dt = start_dt + timedelta(hours=1)
        else:
            # No date: create a 1-hour event tomorrow at 9am as placeholder
            tmr = datetime.now() + timedelta(days=1)
            start_dt = tmr.replace(hour=9, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(hours=1)

        # Skip if already exists
        if event_exists(service, title, start_dt.isoformat()):
            return None

        event_body = {
            "summary": f"{EVENT_PREFIX} {title[:80]}",
            "description": (
                f"From WhatsApp chat: {source}\n"
                f"Sender: {item.get('source_sender', 'Unknown')}\n"
                f"---\n{item.get('source_text', '')[:200]}"
            ),
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": TIMEZONE,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": TIMEZONE,
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        event = service.events().insert(calendarId="primary", body=event_body).execute()
        return event.get("id")

    except Exception as e:
        print(f"  ⚠️  Failed to create event: {e}")
        return None


def process_account(service, db_path: str, account_name: str, processed: dict):
    """Process one wacli account for events."""
    since_ts = processed.get(account_name, {}).get("last_calendar_ts", 0)
    if since_ts == 0:
        since_ts = int((datetime.now() - timedelta(hours=1)).timestamp())

    messages = get_new_messages(db_path, since_ts, limit=100)
    if not messages:
        return 0

    # Unified extraction: rules + optional LLM + learned penalties
    all_items = extract_all(messages)

    created = 0
    max_ts = since_ts

    for msg in messages:
        msg_id = msg["msg_id"]
        if msg_id in processed.get(account_name, {}).get("calendar_msg_ids", {}):
            continue

        items = all_items.get(msg_id, [])

        for item in items:
            if item["type"] != "event" or item["confidence"] < 0.65:
                continue

            event_id = create_calendar_event(service, item)
            if event_id:
                created += 1
                print(f"  📅 Created: {item['title'][:60]}")

            # Mark as processed
            processed.setdefault(account_name, {}).setdefault("calendar_msg_ids", {})[msg_id] = True

        max_ts = max(max_ts, msg["ts"])

    processed.setdefault(account_name, {})["last_calendar_ts"] = max_ts
    return created


def main():
    parser = argparse.ArgumentParser(description="wacli → Google Calendar")
    parser.add_argument("--auth", action="store_true", help="Run OAuth flow only")
    parser.add_argument("--once", action="store_true", help="Single scan then exit")
    args = parser.parse_args()

    print("🔐 Authenticating Google Calendar...")
    service = get_calendar_service()
    print("✅ Connected")

    if args.auth:
        print("OAuth complete. Token saved.")
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
        created = process_account(service, db_path, name, processed)
        print(f"  ✅ {name}: {created} event(s) created")

    save_processed(processed)
    print("\n✨ Done!")


if __name__ == "__main__":
    main()
