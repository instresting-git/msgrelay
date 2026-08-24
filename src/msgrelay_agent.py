#!/usr/bin/env python3
"""
MsgRelay LLM agent runner — executes the prompt workflows in prompts/.

This is the "LLM-first" path: the prompts in prompts/ drive the whole
judgement pipeline (extract → classify → priority → group → action), with the
regex engine remaining as the offline fallback.

Workflows:
    calendar-tasks    full pipeline: messages → action list (create_event/create_task/skip)
    extract           batch extraction (used by msgrelay_extract.py)
    priority-learn    sender priority learning (used by msgrelay_priority.py)
    summarize         daily digest (markdown)
    weekly-report     weekly report (markdown)

Prompts dir resolution:
    1. $MSGRELAY_PROMPTS_DIR
    2. <repo>/prompts
    3. <SCRIPTS_DIR>/prompts   (after setup.sh install)

CLI:
    python3 msgrelay_agent.py --run calendar-tasks --messages-file msgs.json
    python3 msgrelay_agent.py --run summarize --messages-file msgs.json
    python3 msgrelay_agent.py --list-workflows
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import requests

from wacli_config import SCRIPTS_DIR
from msgrelay_llm import get_llm_config

WORKFLOWS = {
    "calendar-tasks": "calendar-tasks.md",
    "extract": "extract.md",
    "priority-learn": "priority-learn.md",
    "summarize": "summarize.md",
    "weekly-report": "weekly-report.md",
}


def prompts_dir() -> str:
    env = os.environ.get("MSGRELAY_PROMPTS_DIR")
    if env:
        return env
    # repo layout: <root>/prompts  (this file is in <root>/src)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_prompts = os.path.join(os.path.dirname(here), "prompts")
    if os.path.isdir(repo_prompts):
        return repo_prompts
    installed = os.path.join(SCRIPTS_DIR, "prompts")
    if os.path.isdir(installed):
        return installed
    return repo_prompts


def load_prompt(name: str) -> str | None:
    fname = WORKFLOWS.get(name)
    if not fname:
        return None
    path = os.path.join(prompts_dir(), fname)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def _parse_json_response(content: str):
    """Defensive JSON parse (strip markdown fences, find first JSON block)."""
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"(\[|\{).*(\]|\})", content, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def run_workflow(name: str, messages: list[dict], extra_context: str = "") -> dict | None:
    """
    Run a prompt workflow against the configured LLM.

    Returns {"ok": bool, "data": <parsed JSON>, "workflow": name, "error": str?}
    or None when the LLM is not configured / unavailable.
    """
    config = get_llm_config()
    if config is None:
        return None

    prompt = load_prompt(name)
    if prompt is None:
        return {"ok": False, "error": f"unknown workflow: {name}", "data": None,
                "workflow": name}

    # Build a compact message list for the prompt
    lines = []
    for i, m in enumerate(messages[:40]):
        lines.append(
            f'[{i}] {{"id": "{m.get("id", m.get("msg_id", i))}", '
            f'"sender": "{m.get("sender", "?")}", '
            f'"chat": "{m.get("chat", "")}", '
            f'"text": "{m.get("text", "")[:300]}"}}')
    user_content = "Input messages:\n" + "\n".join(lines)
    if extra_context:
        user_content += "\n\nAdditional context:\n" + extra_context

    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
    }
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"

    try:
        resp = requests.post(config["base_url"], json=payload,
                             headers=headers, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _parse_json_response(content)
        return {"ok": data is not None, "data": data,
                "error": None if data is not None else "unparseable LLM response",
                "workflow": name}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None, "workflow": name}


def main():
    p = argparse.ArgumentParser(description="MsgRelay LLM agent runner")
    p.add_argument("--run", metavar="WORKFLOW",
                   choices=sorted(WORKFLOWS.keys()), help="workflow to run")
    p.add_argument("--messages-file", default="", help="JSON list of messages")
    p.add_argument("--context", default="", help="extra context appended to the prompt")
    p.add_argument("--output", default="", help="write raw result JSON to file")
    p.add_argument("--list-workflows", action="store_true")
    args = p.parse_args()

    if args.list_workflows:
        for name in sorted(WORKFLOWS):
            path = os.path.join(prompts_dir(), WORKFLOWS[name])
            exists = os.path.exists(path)
            print(f"{name:16} {'✓' if exists else '✗ missing'}  {WORKFLOWS[name]}")
        return

    if not args.run:
        p.print_help()
        return

    if not args.messages_file:
        p.error("--messages-file required")
    with open(args.messages_file) as f:
        messages = json.load(f)

    result = run_workflow(args.run, messages, args.context)
    if result is None:
        print("LLM not configured — set MSGRELAY_LLM_API_KEY / MSGRELAY_LLM_BASE_URL "
              "(or use the regex engine, which always works offline)")
        sys.exit(1)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"written: {args.output}")

    if not result["ok"]:
        print(f"workflow failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result["data"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
