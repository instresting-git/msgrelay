#!/usr/bin/env python3
"""
MsgRelay task grouping engine.

Classifies extracted tasks into project groups using keyword matching
(mirrors the task_groups.json knowledge base pattern).

Storage: <MSGRELAY_HOME>/scripts/msgrelay_task_groups.json

Default template ships with generic categories (project/soc/infra/client/
personal); users can add their own groups with keywords.

CLI:
    python3 msgrelay_groups.py --list
    python3 msgrelay_groups.py --classify "ArcSight migration follow up"
    python3 msgrelay_groups.py --add-group myproject --name "My Project" \
        --category project --keywords "myproj,xyz"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from wacli_config import SCRIPTS_DIR

GROUPS_FILE = os.path.join(SCRIPTS_DIR, "msgrelay_task_groups.json")

DEFAULT_GROUPS = {
    "categories": {
        "project": {"name": "Project", "color": "blue"},
        "soc": {"name": "SOC", "color": "red"},
        "infra": {"name": "Infrastructure", "color": "orange"},
        "client": {"name": "Client", "color": "purple"},
        "personal": {"name": "Personal", "color": "green"},
    },
    "groups": {
        "soc-alerts": {"name": "SOC Alerts", "category": "soc",
                       "keywords": ["alert", "incident", "SIEM", "escalation", "告警", "事件"]},
        "detection-eng": {"name": "Detection Engineering", "category": "soc",
                          "keywords": ["detection", "rule", "correlation", "query", "检测", "规则"]},
        "infra-maintain": {"name": "Maintenance", "category": "infra",
                           "keywords": ["server", "disk", "maintenance", "patch", "reboot",
                                        "维护", "磁盘", "补丁"]},
        "client-request": {"name": "Client Requests", "category": "client",
                           "keywords": ["client", "request", "requirement", "audit",
                                        "客户", "需求", "审计"]},
        "follow-up": {"name": "Follow-ups", "category": "soc",
                      "keywords": ["follow up", "check", "review", "跟進", "跟进", "待跟"]},
        "personal": {"name": "Personal", "category": "personal",
                     "keywords": ["family", "home", "personal", "家庭", "个人"]},
    },
}


def _load() -> dict:
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE) as f:
                data = json.load(f)
            data.setdefault("categories", DEFAULT_GROUPS["categories"])
            data.setdefault("groups", {})
            return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_GROUPS))


def _save(data: dict):
    os.makedirs(os.path.dirname(GROUPS_FILE), exist_ok=True)
    with open(GROUPS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_groups() -> dict:
    return _load()["groups"]


def classify_task(title: str, text: str = "") -> str | None:
    """
    Classify a task into a group key by keyword matching.
    Returns the best-matching group key, or None if no match.

    Scoring: each keyword hit adds 1; a title hit counts double.
    """
    data = _load()
    groups = data.get("groups", {})
    if not groups:
        return None

    haystack_title = (title or "").lower()
    haystack_text = (text or "").lower()

    best_key, best_score = None, 0
    for key, g in groups.items():
        score = 0
        for kw in g.get("keywords", []):
            kw = kw.lower()
            if kw and kw in haystack_title:
                score += 2
            elif kw and kw in haystack_text:
                score += 1
        if score > best_score:
            best_key, best_score = key, score

    return best_key if best_key and best_score > 0 else None


def add_group(key: str, name: str, category: str, keywords: list[str]) -> bool:
    data = _load()
    if key in data["groups"]:
        return False
    data["groups"][key] = {
        "name": name, "category": category, "keywords": keywords, "task_count": 0,
    }
    _save(data)
    return True


def main():
    p = argparse.ArgumentParser(description="MsgRelay task grouping")
    p.add_argument("--list", action="store_true", help="list all groups")
    p.add_argument("--classify", metavar="TEXT", help="classify text into a group")
    p.add_argument("--add-group", metavar="KEY")
    p.add_argument("--name", default="")
    p.add_argument("--category", default="project")
    p.add_argument("--keywords", default="", help="comma-separated keywords")
    args = p.parse_args()

    if args.list:
        for key, g in get_groups().items():
            print(f"{key:20} [{g.get('category','')}] {g.get('name','')} "
                  f"kw={','.join(g.get('keywords', []))}")
        return
    if args.classify:
        print(classify_task(args.classify) or "(no group match)")
        return
    if args.add_group:
        kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
        ok = add_group(args.add_group, args.name or args.add_group, args.category, kws)
        print("added" if ok else "already exists")
        return
    p.print_help()


if __name__ == "__main__":
    main()
