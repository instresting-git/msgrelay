#!/usr/bin/env python3
"""
Lark Calendar + Tasks creator with parent/sub-task grouping.
Usage:
  echo '{"events":[...],"tasks":[...]}' | python3 wacli_lark_create.py [--output-ids FILE]
  python3 wacli_lark_create.py --mark-completed TASK_GUID
  python3 wacli_lark_create.py --mark-reopened TASK_GUID
"""
import argparse, fcntl, os, sys, json, time, requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wacli_config import _load_secrets

LARK_BASE = "https://open.larksuite.com/open-apis"
AUTH_URL = f"{LARK_BASE}/auth/v3/tenant_access_token/internal"
TASK_BASE = f"{LARK_BASE}/task/v2"
LARK_USER_ID = os.environ.get("MSGRELAY_LARK_USER_ID", "") or _load_secrets().get("lark_user_id", "")
CALENDAR_ID = "primary"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lark_user_token.json")
TOKEN_LOCK_FILE = TOKEN_FILE + ".lock"
PARENT_MAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wacli_lark_parents.json")

_token_cache = {"token": None, "expires_at": 0}
_parent_map = None


def get_token():
    """Get user access token (preferred) or fall back to app token."""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    # Try user token first (supports parent_task_guid)
    if os.path.exists(TOKEN_FILE):
        lock_fd = None
        try:
            # Acquire lock to prevent concurrent refresh races
            lock_fd = open(TOKEN_LOCK_FILE, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            with open(TOKEN_FILE) as f:
                ut = json.load(f)
            # Re-check expiry under lock (another process may have refreshed)
            if ut.get("expires_at", 0) > now + 60:
                _token_cache["token"] = ut["access_token"]
                _token_cache["expires_at"] = ut["expires_at"]
                return ut["access_token"]
            # Try refresh
            secrets = _load_secrets()
            r = requests.post(f"{LARK_BASE}/authen/v1/refresh_access_token",
                            json={"grant_type": "refresh_token", "refresh_token": ut.get("refresh_token", ""),
                                  "app_id": secrets.get("lark_app_id", ""), "app_secret": secrets.get("lark_app_secret", "")},
                            timeout=10)
            if r.json().get("code") == 0:
                data = r.json()["data"]
                ut["access_token"] = data["access_token"]
                ut["refresh_token"] = data.get("refresh_token", ut.get("refresh_token"))
                ut["expires_at"] = now + data.get("expires_in", 7200) - 300
                with open(TOKEN_FILE, "w") as f:
                    json.dump(ut, f)
                _token_cache["token"] = ut["access_token"]
                _token_cache["expires_at"] = ut["expires_at"]
                return ut["access_token"]
        except Exception:
            pass
        finally:
            if lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

    # Fall back to app token
    secrets = _load_secrets()
    resp = requests.post(AUTH_URL, json={
        "app_id": secrets.get("lark_app_id", ""),
        "app_secret": secrets.get("lark_app_secret", ""),
    }, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Lark auth failed: {data.get('msg')}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = now + data.get("expire", 7200) - 300
    return _token_cache["token"]


def hdrs():
    return {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json; charset=utf-8"}


def load_parent_map():
    """Load group_key → parent_task_guid mapping. Creates parent tasks if needed."""
    global _parent_map
    if _parent_map is not None:
        return _parent_map
    if os.path.exists(PARENT_MAP_FILE):
        with open(PARENT_MAP_FILE) as f:
            _parent_map = json.load(f)
    else:
        _parent_map = {}
    return _parent_map


def save_parent_map():
    with open(PARENT_MAP_FILE, "w") as f:
        json.dump(_parent_map, f, indent=2, ensure_ascii=False)


def find_or_create_parent(group_key: str, group_name: str) -> str:
    """Find existing parent task for group, or create one. Returns parent_task_guid."""
    mapping = load_parent_map()
    if group_key in mapping:
        # Verify parent still exists
        try:
            r = requests.get(f"{TASK_BASE}/tasks/{mapping[group_key]}", headers=hdrs(), timeout=10)
            if r.json().get("code") == 0:
                return mapping[group_key]
        except Exception:
            pass

    # Create new parent task (milestone)
    body = {"summary": group_name, "is_milestone": True}
    resp = requests.post(f"{TASK_BASE}/tasks", headers=hdrs(), json=body, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        print(f"  ⚠️ Failed to create parent '{group_name}': {data.get('msg')}")
        return ""

    guid = data["data"]["task"]["guid"]
    mapping[group_key] = guid
    save_parent_map()
    print(f"  📁 Parent group: {group_name}")
    return guid


def _format_title(item, max_len=60):
    return item["title"][:max_len]


def create_event(item):
    try:
        title = _format_title(item, max_len=80)
        group_name = item.get("group_name", "")
        source = item.get("source_chat", "WhatsApp")
        if item.get("date") and item.get("time"):
            dt_str = f"{item['date'].split('T')[0]}T{item['time']}:00"
            start_dt = datetime.fromisoformat(dt_str)
            end_dt = start_dt + timedelta(hours=1)
        elif item.get("date"):
            start_dt = datetime.fromisoformat(item["date"]).replace(hour=9, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(hours=1)
        else:
            tmr = datetime.now() + timedelta(days=1)
            start_dt = tmr.replace(hour=9, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(hours=1)
        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())
        body = {
            "summary": f"[{group_name}] {title}" if group_name else title,
            "description": f"From WhatsApp: {source}\nSender: {item.get('source_sender', 'Unknown')}\nGroup: {group_name}\n---\n{item.get('source_text', '')[:200]}",
            "start_time": {"timestamp": str(start_ts)},
            "end_time": {"timestamp": str(end_ts)},
            "attendees": [{"type": "user", "user_id": LARK_USER_ID}],
        }
        resp = requests.post(f"{LARK_BASE}/calendar/v4/calendars/{CALENDAR_ID}/events", headers=hdrs(), json=body, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            return None, f"API error: {data.get('msg')}"
        return data["data"]["event"]["event_id"], None
    except Exception as e:
        return None, str(e)


def to_day_start_ts(date_str: str) -> int:
    dt = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d")
    return int(dt.replace(hour=0, minute=0, second=0).timestamp() * 1000)


def to_day_end_ts(date_str: str) -> int:
    dt = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d")
    return int(dt.replace(hour=23, minute=59, second=59).timestamp() * 1000)


def create_task(item):
    try:
        title = _format_title(item, max_len=60)
        source = item.get("source_chat", "WhatsApp")
        group_key = item.get("group_key", "")
        group_name = item.get("group_name", "")

        # Get parent task GUID for grouping
        parent_guid = ""
        if group_key and group_name:
            parent_guid = find_or_create_parent(group_key, group_name)

        body = {
            "summary": title,
            "description": f"From: {item.get('source_sender', 'Unknown')} ({source})\nGroup: {group_name}\n---\n{item.get('source_text', '')[:200]}",
            "members": [{"id": LARK_USER_ID, "type": "user", "role": "assignee"}],
        }

        if parent_guid:
            body["parent_task_guid"] = parent_guid

        today = datetime.now().strftime("%Y-%m-%d")
        tmr = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = item.get("start_date") or today
        due_date = item.get("due_date") or tmr
        body["start"] = {"timestamp": str(to_day_start_ts(start_date))}
        body["due"] = {"timestamp": str(to_day_end_ts(due_date))}

        resp = requests.post(f"{TASK_BASE}/tasks", headers=hdrs(), json=body, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            return None, f"API error ({data.get('code')}): {data.get('msg')}"
        return data["data"]["task"]["guid"], None
    except Exception as e:
        return None, str(e)


def update_task_status(task_guid: str, is_completed: bool = True):
    try:
        body = {"task": {"is_completed": is_completed}, "update_fields": ["is_completed"]}
        resp = requests.patch(f"{TASK_BASE}/tasks/{task_guid}", headers=hdrs(), json=body, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            return False, f"API error ({data.get('code')}): {data.get('msg')}"
        return True, f"Task {task_guid[:12]}... {'completed' if is_completed else 'reopened'}"
    except Exception as e:
        return False, str(e)


def cmd_mark_completed(task_guid: str):
    ok, msg = update_task_status(task_guid, True)
    print(f"{'✅' if ok else '❌'} {msg}")
    sys.exit(0 if ok else 1)


def cmd_mark_reopened(task_guid: str):
    ok, msg = update_task_status(task_guid, False)
    print(f"{'✅' if ok else '❌'} {msg}")
    sys.exit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser(description="Lark Calendar + Tasks creator with parent/sub-task grouping")
    parser.add_argument("--output-ids", type=str, default=None, help="Write created IDs to JSON file")
    parser.add_argument("--mark-completed", type=str, default=None)
    parser.add_argument("--mark-reopened", type=str, default=None)
    args = parser.parse_args()

    if args.mark_completed:
        cmd_mark_completed(args.mark_completed)
    if args.mark_reopened:
        cmd_mark_reopened(args.mark_reopened)

    raw = sys.stdin.read()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        sys.exit(1)

    events = items.get("events", [])
    tasks = items.get("tasks", [])

    if not events and not tasks:
        print("ℹ️  Nothing to create.")
        if args.output_ids:
            with open(args.output_ids, "w") as f:
                json.dump({"events": [], "tasks": [], "created_at": datetime.now().isoformat()}, f)
        return

    print(f"🔐 Authenticated Lark")
    print(f"📅 {len(events)} event(s), 📋 {len(tasks)} task(s) to create\n")

    # Pre-warm parent tasks for all groups
    seen_groups = set()
    for item in events + tasks:
        gk = item.get("group_key", "")
        gn = item.get("group_name", "")
        if gk and gn and gk not in seen_groups:
            seen_groups.add(gk)
            find_or_create_parent(gk, gn)

    created_ids = {"events": [], "tasks": [], "created_at": datetime.now().isoformat()}
    ev_ok = ev_fail = 0
    for ev in events:
        eid, err = create_event(ev)
        if eid:
            print(f"  ✅ [Event] {ev['title'][:50]}")
            created_ids["events"].append({"id": eid, "title": ev["title"], "group_key": ev.get("group_key", ""), "group_name": ev.get("group_name", "")})
            ev_ok += 1
        else:
            print(f"  ❌ [Event] {ev['title'][:40]}... ({err})")
            ev_fail += 1

    t_ok = t_fail = 0
    for t in tasks:
        tid, err = create_task(t)
        if tid:
            gn = t.get("group_name", "")
            start = t.get("start_date", "today")
            due = t.get("due_date", "tomorrow")
            print(f"  ✅ [Task]  {gn} › {t['title'][:40]} ({start} → {due})")
            created_ids["tasks"].append({
                "id": tid, "title": t["title"], "group_key": t.get("group_key", ""), "group_name": gn,
                "start_date": t.get("start_date", ""), "due_date": t.get("due_date", ""),
                "source_chat": t.get("source_chat", ""), "source_sender": t.get("source_sender", "")
            })
            t_ok += 1
        else:
            print(f"  ❌ [Task]  {t['title'][:40]}... ({err})")
            t_fail += 1

    print(f"\n✨ Done! Events: {ev_ok}✓/{ev_fail}✗ | Tasks: {t_ok}✓/{t_fail}✗ | Groups: {len(seen_groups)}")

    if args.output_ids:
        with open(args.output_ids, "w") as f:
            json.dump(created_ids, f, ensure_ascii=False)
        print(f"📝 IDs written to {args.output_ids}")


if __name__ == "__main__":
    main()
