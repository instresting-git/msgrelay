#!/usr/bin/env python3
"""
NLP extraction engine for WhatsApp messages.
Detects calendar events, tasks/action items, and deadlines from message text.
Supports Chinese (Traditional/Simplified), English, and Cantonese.
"""
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

# ── Time pattern helpers ──────────────────────────────────────────

WEEKDAY_CN = {
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3,
    "星期五": 4, "星期六": 5, "星期日": 6, "星期天": 6,
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    "禮拜一": 0, "禮拜二": 1, "禮拜三": 2, "禮拜四": 3,
    "禮拜五": 4, "禮拜六": 5, "禮拜日": 6,
}
WEEKDAY_EN = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

# ── Event trigger patterns ────────────────────────────────────────

EVENT_PATTERNS = [
    # Chinese: meeting / appointment
    (r"(?:開會|開個會|會議|meeting|call|傾(?:吓|下)|見面|見(?:一|個)見)",
     "meeting", 0.8),
    # Specific time mentioned
    (r"(?:下[午昼晝]|上[午昼晝]|朝早|晏晝|夜晚|中午)\s*\d{1,2}[點点:：]\d{0,2}",
     "meeting", 0.9),
    (r"\d{1,2}[點点:：]\d{2}(?:\s*(?:am|pm|AM|PM))?",
     "meeting", 0.8),
    (r"\d{1,2}\s*(?:am|pm)\b",
     "meeting", 0.8),
    # Lunch / dinner plans
    (r"(?:lunch|dinner|食[飯饭]|食晏|食晚|飲茶|饮茶|食[嘢野])",
     "meal", 0.7),
]

# ── Task trigger patterns ─────────────────────────────────────────

TASK_PATTERNS = [
    # Deadline — highest priority, becomes a task with due date
    (r"(?:deadline|截止|限期|due\s*(?:date)?|到期|之前要|before\s+\w+day)\s*(?:前)?\s*(?:要|需)?\s*(.{2,50})", 0.9),
    (r"(?:記得|remember|唔好唔記得|don'?t\s+forget)\s*(?:要\s*)?(?:跟進|follow\s*up|check|處理|搞)?\s*(.{3,50})", 0.9),
    (r"(?:需要|need\s+to|have\s+to|must|mustn'?t)\s+(.{3,50})", 0.8),
    (r"(?:跟進|follow\s*up|followup|check\s*(?:on|up)?)\s+(.{3,50})", 0.85),
    (r"(?:處理|handle|deal\s+with|搞[掂定])\s+(.{3,50})", 0.8),
    (r"(?:todo|task|action\s*item|待辦|待办)\s*[:：]?\s*(.{3,50})", 0.9),
    (r"(?:要做|做[咗左]未|done\?)", 0.6),  # general action
    (r"@\S+\s+(?:pl(?:ease|s)|plz)\s+(.{3,60})", 0.75),
]

# ── Date extraction ───────────────────────────────────────────────

DATE_PATTERNS = [
    (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", "ymd"),
    (r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?", "mdy"),
    (r"(?:明天|聽日|tomorrow)", "tomorrow"),
    (r"(?:今天|今日|today)", "today"),
    (r"(?:後天|後日|day after tomorrow)", "day_after"),
    (r"(?:今晚|今夜|tonight|今朝|今早|this\s+(?:morning|evening)|明早|明[天日](?:早上|上午)?|tomorrow\s+(?:morning|evening))", "tonight_or_morning"),
    (r"(?:下(?:星期|週|周))([一二三四五六日天])", "next_week_cn"),
    (r"(?:next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", "next_week_en"),
    (r"(?:今(?:星期|週|周))([一二三四五六日天])", "this_week_cn"),
    (r"(?:this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", "this_week_en"),
    # Bare weekday → next occurrence: "Friday 4pm", "星期五 3點"
    (r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "weekday_en"),
    (r"(?:星期|週|周)([一二三四五六日天])", "weekday_cn"),
]


def extract_date(text: str, ref_date: datetime = None) -> Optional[datetime]:
    """Extract a date from text. Returns datetime or None."""
    if ref_date is None:
        ref_date = datetime.now()

    for pattern, kind in DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue

        if kind == "ymd":
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif kind == "mdy":
            yr = int(m.group(3) or ref_date.year)
            return datetime(yr, int(m.group(1)), int(m.group(2)))
        elif kind == "today":
            return ref_date
        elif kind == "tomorrow":
            return ref_date + timedelta(days=1)
        elif kind == "day_after":
            return ref_date + timedelta(days=2)
        elif kind == "tonight_or_morning":
            return ref_date
        elif kind == "next_week_cn":
            target = WEEKDAY_CN.get(f"星期{m.group(1)}")
            if target is not None:
                # "下星期三" = the Wednesday of NEXT week, not the nearest one
                days_ahead = 7 - ref_date.weekday() + target
                return ref_date + timedelta(days=days_ahead)
        elif kind == "next_week_en":
            target = WEEKDAY_EN.get(m.group(1).lower())
            if target is not None:
                days_ahead = 7 - ref_date.weekday() + target
                return ref_date + timedelta(days=days_ahead)
        elif kind == "this_week_cn":
            target = WEEKDAY_CN.get(f"星期{m.group(1)}")
            if target is not None:
                days_ahead = target - ref_date.weekday()
                if days_ahead < 0:
                    days_ahead += 7
                return ref_date + timedelta(days=days_ahead)
        elif kind == "this_week_en":
            target = WEEKDAY_EN.get(m.group(1).lower())
            if target is not None:
                days_ahead = target - ref_date.weekday()
                if days_ahead < 0:
                    days_ahead += 7
                return ref_date + timedelta(days=days_ahead)
        elif kind == "weekday_en":
            target = WEEKDAY_EN.get(m.group(1).lower())
            if target is not None:
                days_ahead = target - ref_date.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                return ref_date + timedelta(days=days_ahead)
        elif kind == "weekday_cn":
            target = WEEKDAY_CN.get(f"星期{m.group(1)}")
            if target is not None:
                days_ahead = target - ref_date.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                return ref_date + timedelta(days=days_ahead)

    return None


def extract_time(text: str) -> Optional[tuple]:
    """Extract time (hour, minute) from text. Supports EN/CN/Cantonese."""
    t = text.lower()
    hour = minute = None
    ampm = None

    # 1) HH:MM with optional am/pm — "2:30pm", "14:30", "3點半"
    m = re.search(r"(\d{1,2})[:：點点](\d{2})\s*(am|pm)?", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        ampm = m.group(3)
    else:
        # 2) Bare "2pm" / "3am" — no colon
        m = re.search(r"(\d{1,2})\s*(am|pm)\b", t)
        if m:
            hour, minute = int(m.group(1)), 0
            ampm = m.group(2)
        else:
            # 3) Chinese period + hour: 下午3點 / 下晝3點 / 夜晚9點半 / 今晚7點
            m = re.search(
                r"(下[午昼晝]|上[午昼晝]|朝早|晏晝|夜晚|中午|今晚|今朝|明早)\s*(\d{1,2})[點点](?:(半|\d{1,2}))?", t)
            if m:
                period, hour = m.group(1), int(m.group(2))
                minute = 30 if m.group(3) == "半" else (int(m.group(3)) if m.group(3) else 0)
                if period in ("下午", "下昼", "下晝", "晏晝", "夜晚", "今晚"):
                    if hour < 12:
                        hour += 12
                elif period == "中午" and hour < 11:
                    hour += 12  # 中午1點 = 13:00
                # 上午/朝早/今朝/明早 stay AM
                return (hour, minute)

    if hour is not None:
        if ampm:
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
        return (hour, minute)

    # 4) Bare Chinese hour: "星期三 2點見面" → assume business hours.
    #    Hours 1-7 are almost always PM in conversation context (2點 → 14:00).
    m = re.search(r"(\d{1,2})[點点](?:半|(\d{1,2}))?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else (30 if "半" in m.group(0) else 0)
        if hour < 8:
            hour += 12
        return (hour, minute)

    return None


def analyze_message(text: str, sender: str, chat: str, msg_id: str,
                    ts: int, from_me: bool, media_type: str) -> list[dict]:
    """
    Analyze a single message and return a list of extracted items.
    Each item is a dict with type, confidence, details.
    """
    if not text or text == "(message)":
        return []

    results = []

    # ── Deadline detection — highest priority, becomes a task with due date ──
    deadline_m = re.search(
        r"(?:deadline|截止|限期|due\s*(?:date)?|到期|之前要|before\s+\w+day)",
        text, re.IGNORECASE)
    if deadline_m:
        # Try to capture the deliverable near the deadline mention
        desc_m = re.search(
            r"(?:前要|之前要|要交|需要交|交|submit|deliver)\s*([^，。,.]{2,50})",
            text, re.IGNORECASE)
        task_desc = desc_m.group(1).strip() if desc_m else text[:80]
        due_date = extract_date(text)
        return [{
            "type": "task",
            "subtype": "deadline",
            "confidence": 0.9,
            "title": task_desc,
            "due_date": due_date.isoformat() if due_date else None,
            "source_text": text,
            "source_chat": chat,
            "source_sender": sender,
            "source_msg_id": msg_id,
            "source_ts": ts,
            "from_me": from_me,
        }]

    # ── Event detection ──
    for pattern, event_type, confidence in EVENT_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            event_date = extract_date(text)
            event_time = extract_time(text)

            # Boost confidence if both date and time found
            if event_date or event_time:
                confidence = min(confidence + 0.15, 1.0)

            results.append({
                "type": "event",
                "subtype": event_type,
                "confidence": confidence,
                "date": event_date.isoformat() if event_date else None,
                "time": f"{event_time[0]:02d}:{event_time[1]:02d}" if event_time else None,
                "title": text[:100],
                "source_text": text,
                "source_chat": chat,
                "source_sender": sender,
                "source_msg_id": msg_id,
                "source_ts": ts,
                "from_me": from_me,
            })
            break  # One classification per message

    # ── Task detection ── (run even if event found with low confidence)
    if not results or results[0]["confidence"] < 0.7:
        for pattern, confidence in TASK_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                task_desc = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else text[:80]
                due_date = extract_date(text)

                results.append({
                    "type": "task",
                    "confidence": confidence,
                    "title": task_desc,
                    "due_date": due_date.isoformat() if due_date else None,
                    "source_text": text,
                    "source_chat": chat,
                    "source_sender": sender,
                    "source_msg_id": msg_id,
                    "source_ts": ts,
                    "from_me": from_me,
                })
                break

    return results


def get_new_messages(db_path: str, since_ts: int, limit: int = 200) -> list[dict]:
    """Get new messages from wacli SQLite DB since a timestamp."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT m.chat_jid, COALESCE(m.chat_name, c.name, m.chat_jid) as chat,
                   COALESCE(m.sender_name, m.sender_jid) as sender,
                   m.msg_id, m.ts, m.from_me, m.media_type,
                   COALESCE(m.display_text, m.text, '') as text
            FROM messages m
            LEFT JOIN chats c ON c.jid = m.chat_jid
            WHERE m.deleted_at IS NULL
              AND m.ts > ?
              AND COALESCE(m.display_text, m.text, '') NOT IN ('', '(message)')
            ORDER BY m.ts ASC
            LIMIT ?
        """, (since_ts, limit)).fetchall()

        return [dict(r) for r in rows]
    except Exception as e:
        print(f"  DB error ({db_path}): {e}")
        return []
    finally:
        try:
            conn.close()
        except:
            pass


if __name__ == "__main__":
    # Quick test
    test_texts = [
        "聽日下晝3點開會傾project進度",
        "下星期三deadline前要交report",
        "記得跟進個client個case",
        "tomorrow 2pm meeting with team",
        "follow up on the SOC alert",
        "今晚7點食飯？",
    ]
    for t in test_texts:
        items = analyze_message(t, "test", "test", "0", int(datetime.now().timestamp()), False, "")
        if items:
            for item in items:
                subtype = item.get('subtype', '')
                label = f"{item['type']}/{subtype}" if subtype else item['type']
                print(f"  [{label}] ({item['confidence']:.0%}) {item['title'][:60]}")
                if item.get('date'):
                    print(f"    Date: {item['date']}, Time: {item.get('time')}")
        else:
            print(f"  (no match) {t}")
