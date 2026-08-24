#!/usr/bin/env python3
"""
MsgRelay task tracker — local task lifecycle management.

Tracks every extracted task locally (independent of Google Tasks), keeping
status, source, grouping, keywords and notes. Mirrors the task_tracker.json
knowledge-base pattern.

Storage: <MSGRELAY_HOME>/scripts/msgrelay_task_tracker.json

CLI:
    python3 msgrelay_tracker.py --list [--status open|completed|all]
    python3 msgrelay_tracker.py --add --title "..." [--group KEY] [--chat "..."] [--sender "..."]
    python3 msgrelay_tracker.py --complete <TASK_ID>
    python3 msgrelay_tracker.py --notes <TASK_ID> --note "..."
    python3 msgrelay_tracker.py --stats
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime

from wacli_config import SCRIPTS_DIR
from msgrelay_groups import classify_task

TRACKER_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_task_tracker.json")


def _now() -> str:
    return datetime.now().isoformat()


def _load() -> dict:
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f:
                data = json.load(f)
            data.setdefault("tasks", {})
            return data
        except Exception:
            pass
    return {"tasks": {}}


def _save(data: dict):
    os.makedirs(os.path.dirname(TRACKER_FILE), exist_ok=True)
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _extract_keywords(title: str, text: str = "") -> list[str]:
    """Simple keyword extraction: meaningful tokens from title + text."""
    words = set()
    for chunk in (title or "").split():
        token = chunk.strip(".,:;!?()[]{}，。；：！？")
        if len(token) >= 3:
            words.add(token.lower())
    return sorted(words)[:12]


def add_task(title: str, group_key: str | None = None, chat: str = "",
             sender: str = "", text: str = "", status: str = "open") -> str:
    """Add a task to the tracker. Returns the task id."""
    data = _load()
    task_id = str(uuid.uuid4())
    if group_key is None:
        group_key = classify_task(title, text)
    data["tasks"][task_id] = {
        "title": title,
        "group_key": group_key,
        "status": status,
        "created_at": _now(),
        "source_chat": chat,
        "source_sender": sender,
        "keywords": _extract_keywords(title, text),
        "notes": "",
        "notes_updated": None,
        "completed_at": None,
    }
    _save(data)
    return task_id


def complete_task(task_id: str) -> bool:
    data = _load()
    t = data["tasks"].get(task_id)
    if not t:
        return False
    t["status"] = "completed"
    t["completed_at"] = _now()
    _save(data)
    return True


def set_notes(task_id: str, note: str) -> bool:
    data = _load()
    t = data["tasks"].get(task_id)
    if not t:
        return False
    t["notes"] = note
    t["notes_updated"] = _now()
    _save(data)
    return True


def list_tasks(status: str = "all") -> list[dict]:
    data = _load()
    tasks = []
    for tid, t in data["tasks"].items():
        if status != "all" and t.get("status") != status:
            continue
        tasks.append({"id": tid, **t})
    tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return tasks


def get_stats() -> dict:
    data = _load()
    tasks = data["tasks"]
    open_count = sum(1 for t in tasks.values() if t.get("status") == "open")
    completed = sum(1 for t in tasks.values() if t.get("status") == "completed")
    by_group: dict[str, int] = {}
    for t in tasks.values():
        g = t.get("group_key") or "(none)"
        by_group[g] = by_group.get(g, 0) + 1
    return {"total": len(tasks), "open": open_count, "completed": completed,
            "by_group": by_group}


def main():
    p = argparse.ArgumentParser(description="MsgRelay task tracker")
    p.add_argument("--list", action="store_true")
    p.add_argument("--status", default="all", choices=["all", "open", "completed"])
    p.add_argument("--add", action="store_true")
    p.add_argument("--title", default="")
    p.add_argument("--group", default=None)
    p.add_argument("--chat", default="")
    p.add_argument("--sender", default="")
    p.add_argument("--complete", metavar="TASK_ID")
    p.add_argument("--notes", metavar="TASK_ID")
    p.add_argument("--note", default="")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args()

    if args.stats:
        print(json.dumps(get_stats(), indent=2, ensure_ascii=False))
        return
    if args.complete:
        print("completed" if complete_task(args.complete) else "not found")
        return
    if args.notes:
        print("updated" if set_notes(args.notes, args.note) else "not found")
        return
    if args.add:
        if not args.title:
            p.error("--title required with --add")
        tid = add_task(args.title, args.group, args.chat, args.sender)
        print(f"added {tid} group={args.group or 'auto'}")
        return
    if args.list:
        for t in list_tasks(args.status):
            mark = "[x]" if t["status"] == "completed" else "[ ]"
            print(f"{mark} {t['id'][:8]} ({t.get('group_key') or 'ungrouped'}) {t['title'][:60]}")
        return
    p.print_help()


if __name__ == "__main__":
    main()
