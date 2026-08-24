#!/usr/bin/env python3
"""
Unified extraction pipeline for MsgRelay.

Combines:
  1. Regex engine (wacli_nlp_extract.analyze_message) — always runs, fast, offline.
  2. LLM engine (msgrelay_llm.llm_extract) — optional, enabled by config;
     adds real language understanding. Falls back to rules on any failure.
  3. Auto-learn (msgrelay_learn) — applies learned pattern penalties and
     feeds few-shot examples to the LLM.

Usage (Calendar/Tasks/Reports all use this):
    from msgrelay_extract import extract_all
    items_by_msg = extract_all(messages)
"""
from __future__ import annotations

from wacli_nlp_extract import analyze_message
from msgrelay_llm import llm_extract, merge_with_rules, get_llm_config
from msgrelay_learn import apply_pattern_penalties, get_few_shot_examples
from msgrelay_priority import get_sender_priority
from msgrelay_groups import classify_task


def extract_all(messages: list[dict]) -> dict[str, list[dict]]:
    """
    Extract structured items from a list of messages.

    Pipeline: rules → optional LLM merge → learned penalties → enrichment
    (sender priority + task grouping).

    Returns:
        {msg_id: [item dicts]} — items include priority / group_key.
    """
    if not messages:
        return {}

    # 1) Rule extraction (always)
    result: dict[str, list[dict]] = {}
    for m in messages:
        result[m["msg_id"]] = analyze_message(
            m["text"], m.get("sender", ""), m.get("chat", ""),
            m["msg_id"], m.get("ts", 0), bool(m.get("from_me", False)),
            m.get("media_type", "")
        )

    # 2) LLM enhancement (optional, opt-in)
    if get_llm_config() is not None:
        examples = get_few_shot_examples()
        batch = [{"id": m["msg_id"], "text": m["text"], "sender": m.get("sender", "")}
                 for m in messages]
        llm_results = llm_extract(batch, examples)
        if llm_results:
            for m in messages:
                mid = m["msg_id"]
                rule_items = result.get(mid, [])
                result[mid] = merge_with_rules(llm_results.get(mid), rule_items)

    # 3) Learned pattern penalties (rules correction)
    for m in messages:
        result[m["msg_id"]] = apply_pattern_penalties(result.get(m["msg_id"], []), m["text"])

    # 4) Enrichment: sender priority + task grouping
    for m in messages:
        sender = m.get("sender", "")
        pr = get_sender_priority(sender)
        for it in result.get(m["msg_id"], []):
            it["priority"] = pr["priority"]
            it["priority_confidence"] = pr["confidence"]
            if it["type"] == "task":
                it["group_key"] = classify_task(it.get("title", ""), m.get("text", ""))

    return result


if __name__ == "__main__":
    # Quick demo
    sample = [
        {"msg_id": "d1", "text": "聽日下晝3點開會傾project進度", "sender": "A",
         "chat": "demo", "ts": 0, "from_me": 0, "media_type": ""},
        {"msg_id": "d2", "text": "今日天氣好好", "sender": "B",
         "chat": "demo", "ts": 0, "from_me": 0, "media_type": ""},
    ]
    out = extract_all(sample)
    for mid, items in out.items():
        print(f"{mid}: {[(i['type'], i.get('subtype',''), i.get('confidence')) for i in items]}")
