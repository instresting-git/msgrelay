#!/usr/bin/env python3
"""
Lark (Feishu International) Calendar integration for wacli.
Reads extracted events from NLP engine and creates events on Lark primary calendar.
"""
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
AUTH_URL = f"{LARK_BASE}/auth/v3/tenant_access_token/internal"
# Target user (for calendar event attendees)
LARK_USER_ID = os.environ.get("CHATFLOW_LARK_USER_ID", "") or _load_secrets().get("lark_user_id", "")
CALENDAR_ID = "primary"  # Use primary calendar directly

# Token cache
_token_cache = {"token": None, "expires_at": 0, "type": "tenant"}

TOKEN_FILE = os.path.join(SCRIPTS_DIR, "lark_user_token.json")


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


def get_token() -> str:
    """Get Lark access token. Prefers user token for Calendar visibility."""
    global _token_cache
    now = time.time()

    # Try user token first (events will appear in user's calendar)
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE) as f:
                user_token = json.load(f)
            if user_token.get("expires_at", 0) > now + 60:
                return user_token["access_token"]
            # Try refresh
            if user_token.get("refresh_token"):
                resp = requests.post(
                    f"{LARK_BASE}/authen/v1/oidc/refresh_token",
                    json={"grant_type": "refresh_token", "refresh_token": user_token["refresh_token"]},
                    timeout=10,
                )
                data = resp.json()
                if data.get("code") == 0:
                    user_token["access_token"] = data["access_token"]
                    user_token["refresh_token"] = data.get("refresh_token", user_token["refresh_token"])
                    user_token["expires_at"] = now + data.get("expires_in", 7200) - 300
                    with open(TOKEN_FILE, "w") as f:
                        json.dump(user_token, f, indent=2)
                    return user_token["access_token"]
        except Exception:
            pass

    # Fallback to tenant token
    return get_tenant_token()


def lark_headers() -> dict:
    """Standard Lark API headers."""
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def event_exists(title: str, start_ts: int) -> bool:
    """Check if a similar event already exists to avoid duplicates."""
    try:
        resp = requests.get(
            f"{LARK_BASE}/calendar/v4/calendars/{CALENDAR_ID}/events",
            headers=lark_headers(),
            params={
                "start_time": str(start_ts - 3600),
                "end_time": str(start_ts + 7200),
                "page_size": 50,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            return False

        for ev in data.get("data", {}).get("items", []):
            if title[:20] in (ev.get("summary", "") or ""):
                return True
    except Exception:
        pass
    return False


def create_calendar_event(item: dict) -> str | None:
    """Create a Lark Calendar event on primary calendar. Returns event ID or None."""
    try:
        title = f"[WA] {item['title'][:100]}"
        source = item.get("source_chat", "WhatsApp")

        # Determine start/end time
        if item.get("date") and item.get("time"):
            dt_str = f"{item['date'].split('T')[0]}T{item['time']}:00"
            start_dt = datetime.fromisoformat(dt_str)
            end_dt = start_dt + timedelta(hours=1)
        elif item.get("date"):
            start_dt = datetime.fromisoformat(item["date"]).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            end_dt = start_dt + timedelta(hours=1)
        else:
            tmr = datetime.now() + timedelta(days=1)
            start_dt = tmr.replace(hour=9, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(hours=1)

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        # Skip duplicate
        if event_exists(title, start_ts):
            return None

        event_body = {
            "summary": title,
            "description": (
                f"From WhatsApp: {source}\n"
                f"Sender: {item.get('source_sender', 'Unknown')}\n"
                f"---\n{item.get('source_text', '')[:200]}"
            ),
            "start_time": {"timestamp": str(start_ts)},
            "end_time": {"timestamp": str(end_ts)},
            "attendees": [
                {
                    "type": "user",
                    "user_id": LARK_USER_ID,
                }
            ],
        }

        resp = requests.post(
            f"{LARK_BASE}/calendar/v4/calendars/{CALENDAR_ID}/events",
            headers=lark_headers(),
            json=event_body,
            timeout=15,
        )
        data = resp.json()

        if data.get("code") != 0:
            print(f"  ⚠️  Create event failed: {data.get('msg')}")
            return None

        return data["data"]["event"]["event_id"]

    except Exception as e:
        print(f"  ⚠️  Failed to create event: {e}")
        return None


def process_account(db_path: str, account_name: str, processed: dict):
    """Process one wacli account for events."""
    since_ts = processed.get(account_name, {}).get("last_calendar_ts", 0)
    if since_ts == 0:
        since_ts = int((datetime.now() - timedelta(hours=1)).timestamp())

    messages = get_new_messages(db_path, since_ts, limit=100)
    if not messages:
        return 0

    created = 0
    max_ts = since_ts

    for msg in messages:
        msg_id = msg["msg_id"]
        if msg_id in processed.get(account_name, {}).get("calendar_msg_ids", {}):
            continue

        items = analyze_message(
            msg["text"], msg["sender"], msg["chat"],
            msg_id, msg["ts"], bool(msg["from_me"]), msg["media_type"]
        )

        for item in items:
            if item["type"] != "event" or item["confidence"] < 0.65:
                continue

            event_id = create_calendar_event(item)
            if event_id:
                created += 1
                print(f"  📅 Created: {item['title'][:60]}")

            processed.setdefault(account_name, {}).setdefault(
                "calendar_msg_ids", {})[msg_id] = True

        max_ts = max(max_ts, msg["ts"])

    processed.setdefault(account_name, {})["last_calendar_ts"] = max_ts
    return created


def main():
    parser = argparse.ArgumentParser(description="wacli → Lark Calendar")
    parser.add_argument("--once", action="store_true", help="Single scan then exit")
    args = parser.parse_args()

    print("🔐 Authenticating Lark...")
    token = get_token()
    print(f"✅ Connected")

    processed = load_processed()

    for acct in get_accounts():
        name, db_path = acct["name"], acct["db"]
        if not os.path.exists(db_path):
            print(f"  ⚠️  {name} DB not found: {db_path}")
            continue
        print(f"\n📱 Processing {name} account...")
        created = process_account(db_path, name, processed)
        print(f"  ✅ {name}: {created} event(s) created")

    save_processed(processed)
    print("\n✨ Done!")


if __name__ == "__main__":
    main()
