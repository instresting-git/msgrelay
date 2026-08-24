#!/usr/bin/env python3
"""
Discord webhook report generator for wacli WhatsApp data.
Generates daily and weekly summary reports and sends to Discord webhook.
"""
from __future__ import annotations

import os
import sys
import json
import argparse
import sqlite3
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wacli_config import (
    REPORTS_DIR, _load_secrets, get_accounts, REPORT_FOOTER, PRODUCT_NAME
)


def query_messages(db_path: str, since_hours: int = 24) -> list[dict]:
    """Get messages from the last N hours."""
    since_ts = int((datetime.now() - timedelta(hours=since_hours)).timestamp())
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT m.chat_jid, COALESCE(m.chat_name, c.name, m.chat_jid) as chat,
                   COALESCE(m.sender_name, m.sender_jid) as sender,
                   m.ts, m.from_me,
                   COALESCE(m.display_text, m.text, '') as text,
                   m.media_type
            FROM messages m
            LEFT JOIN chats c ON c.jid = m.chat_jid
            WHERE m.deleted_at IS NULL
              AND m.ts > ?
              AND COALESCE(m.display_text, m.text, '') NOT IN ('', '(message)')
            ORDER BY m.ts DESC
        """, (since_ts,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"  DB error: {e}")
        return []
    finally:
        try:
            conn.close()
        except:
            pass


def generate_daily_stats(db_path: str, account_name: str) -> dict:
    """Generate statistics for the past 24 hours."""
    msgs = query_messages(db_path, since_hours=24)
    if not msgs:
        return None

    chats = defaultdict(list)
    total_from_me = 0
    total_from_others = 0
    media_count = 0

    for m in msgs:
        chat = m["chat"]
        chats[chat].append(m)
        if m["from_me"]:
            total_from_me += 1
        else:
            total_from_others += 1
        if m["media_type"]:
            media_count += 1

    # Top active chats
    top_chats = sorted(chats.items(), key=lambda x: len(x[1]), reverse=True)[:10]

    return {
        "total": len(msgs),
        "from_me": total_from_me,
        "from_others": total_from_others,
        "media": media_count,
        "active_chats": len(chats),
        "top_chats": [(name, len(hist)) for name, hist in top_chats],
        "latest": msgs[:5] if msgs else [],
    }


def build_daily_report() -> dict:
    """Build the daily report as Discord embed with content summaries."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    accounts = get_accounts()
    account_queries = []
    for acct in accounts:
        account_queries.append((acct["name"], query_messages(acct["db"], since_hours=24), acct["label"]))

    fields = []

    for account_name, msgs, label in account_queries:
        if not msgs:
            fields.append({"name": label, "value": "No new messages", "inline": False})
            continue

        # Group by chat
        chats = defaultdict(list)
        for m in msgs:
            chats[m["chat"]].append(m)

        total = len(msgs)
        chat_count = len(chats)

        # Build summary lines
        lines = []
        for chat_name, chat_msgs in sorted(chats.items(), key=lambda x: len(x[1]), reverse=True)[:8]:
            # Extract key content from messages
            previews = []
            for m in chat_msgs[:3]:
                text = m["text"][:60].replace("\n", " ")
                if text:
                    sender = m["sender"][:10] if m["sender"] else "?"
                    previews.append(f"_{sender}_: {text}")

            preview_str = "\n".join(previews) if previews else "(media)"
            lines.append(f"**{chat_name}** ({len(chat_msgs)} msgs)\n{preview_str}")

        summary = f"📨 **{total}** msgs | 💬 **{chat_count}** chats\n\n" + "\n\n".join(lines)
        if len(summary) > 1000:
            summary = summary[:997] + "..."

        fields.append({"name": label, "value": summary, "inline": False})

    embed = {
        "title": f"📊 {PRODUCT_NAME} 日報 — {date_str}",
        "color": 0x25D366,
        "fields": fields,
        "footer": {"text": f"{REPORT_FOOTER} · {now.strftime('%Y-%m-%d %H:%M')}"},
        "timestamp": now.isoformat(),
    }

    return embed


def build_weekly_report() -> dict:
    """Build the weekly report as Discord embed."""
    now = datetime.now()
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")

    accounts = get_accounts()
    fields = []
    for acct in accounts:
        msgs = query_messages(acct["db"], since_hours=168)
        chat_count = len(set(m['chat'] for m in msgs))
        fields.append({
            "name": f"💬 {acct['label']}",
            "value": f"📨 **{len(msgs)}** msgs | 💬 **{chat_count}** chats",
            "inline": True,
        })

    embed = {
        "title": f"📊 {PRODUCT_NAME} 週報 — {week_start} ~ {week_end}",
        "color": 0x128C7E,
        "fields": fields,
        "footer": {"text": f"{REPORT_FOOTER} · {now.strftime('%Y-%m-%d %H:%M')}"},
        "timestamp": now.isoformat(),
    }

    return embed


def get_webhook_url() -> str:
    """Get Discord webhook URL from secrets."""
    return _load_secrets().get("discord_webhook_url", "")


def send_discord(embed: dict):
    """Send report to Discord webhook."""
    webhook_url = get_webhook_url()
    if not webhook_url:
        print("❌ Discord webhook URL not configured in wacli_secrets.json")
        sys.exit(1)

    payload = {
        "embeds": [embed],
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        if resp.status_code == 204:
            print(f"✅ Sent to Discord")
        else:
            print(f"❌ Discord error {resp.status_code}: {resp.text[:200]}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=f"{PRODUCT_NAME} → Discord Reports")
    parser.add_argument("--mode", choices=["daily", "weekly"], required=True)
    args = parser.parse_args()

    now = datetime.now()

    if args.mode == "daily":
        print("📊 Generating daily report...")
        embed = build_daily_report()
    else:
        print("📊 Generating weekly report...")
        embed = build_weekly_report()

    # Save local copy
    os.makedirs(REPORTS_DIR, exist_ok=True)
    subdir = "daily" if args.mode == "daily" else "weekly"
    path = os.path.join(REPORTS_DIR, subdir,
                        f"{args.mode}_{now.strftime('%Y%m%d_%H%M')}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(embed, f, indent=2, ensure_ascii=False)
    print(f"📁 Saved: {path}")

    # Send to Discord
    send_discord(embed)


if __name__ == "__main__":
    main()
