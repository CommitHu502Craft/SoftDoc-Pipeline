"""
Runtime skill compiler.

Compile runtime skill constraints into executable rule graph used by lint and gate.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modules.runtime_skill_engine import resolve_external_script_policy


DEFAULT_CRITICAL_RULE_IDS = [
    "copy.first_sentence_prefix",
    "copy.overview_ban_topics",
    "action.button_action_unique",
    "action.showmodal_dom_sequence",
]


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def compile_runtime_rule_graph(runtime_skill_plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = runtime_skill_plan if isinstance(runtime_skill_plan, dict) else {}
    constraints = plan.get("constraints") or {}
    if not isinstance(constraints, dict):
        constraints = {}

    page_narration = constraints.get("page_narration") or {}
    overview_copy = constraints.get("overview_copy") or {}
    frontend = constraints.get("frontend") or {}
    orchestration = plan.get("orchestration") or {}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []

    def add_rule(rule_id: str, category: str, severity: str, params: Dict[str, Any]) -> None:
        nodes.append(
            {
                "rule_id": rule_id,
                "category": category,
                "severity": severity,
                "params": params,
            }
        )

    add_rule(
        "copy.first_sentence_prefix",
        "copy",
        "critical",
        {"prefix": str(page_narration.get("first_sentence_prefix") or "本页面")},
    )
    add_rule(
        "copy.forbid_phrase_after_first",
        "copy",
        "major",
        {"phrase": str(page_narration.get("forbid_phrase_after_first") or "本页面").strip()},
    )
    add_rule(
        "copy.sentence_count",
        "copy",
        "major",
        {"required": int(page_narration.get("sentence_count_per_page") or 6)},
    )
    add_rule(
        "copy.min_chars",
        "copy",
        "major",
        {"required": int(page_narration.get("min_chars_per_page") or 300)},
    )
    add_rule(
        "copy.ban_words",
        "copy",
        "major",
        {"ban_words": [str(x) for x in (page_narration.get("ban_words") or []) if str(x).strip()]},
    )
    add_rule(
        "copy.avoid_terms",
        "copy",
        "minor",
        {"terms": [str(x) for x in (page_narration.get("avoid_terms") or []) if str(x).strip()]},
    )
    add_rule(
        "copy.page_ban_topics",
        "copy",
        "major",
        {
            "ban_topics": [str(x) for x in (page_narration.get("ban_topics") or ["AI", "智能", "导航栏", "页脚"]) if str(x).strip()]
        },
    )
    add_rule(
        "copy.no_date_mentions",
        "copy",
        "major",
        {"required": bool(page_narration.get("ban_date_mentions", True))},
    )
    add_rule(
        "copy.page_similarity_diversity",
        "copy",
        "major",
        {"max_similarity": float(page_narration.get("max_cross_page_similarity") or 0.98)},
    )
    add_rule(
        "copy.overview_target_chars",
        "copy",
        "major",
        {"required": int(overview_copy.get("target_chars") or 250)},
    )
    add_rule(
        "copy.overview_ban_words",
        "copy",
        "major",
        {"ban_words": [str(x) for x in (overview_copy.get("ban_words") or []) if str(x).strip()]},
    )
    add_rule(
        "copy.overview_ban_topics",
        "copy",
        "critical",
        {"ban_topics": [str(x) for x in (overview_copy.get("ban_topics") or []) if str(x).strip()]},
    )
    add_rule(
        "copy.chart_append_sentence",
        "copy",
        "major",
        {"value": str(page_narration.get("chart_append_sentence") or "").strip()},
    )

    add_rule(
        "html.no_comments",
        "html",
        "major",
        {"required": bool(frontend.get("no_comments_required", True))},
    )
    add_rule(
        "html.no_rounded_rectangles",
        "html",
        "major",
        {"required": bool(frontend.get("no_rounded_rectangles", True))},
    )
    add_rule(
        "html.external_script_policy",
        "html",
        "major",
        resolve_external_script_policy(frontend),
    )
    add_rule(
        "html.chart_responsive_false",
        "html",
        "major",
        {"required": bool(frontend.get("chart_required", True)), "value": bool(frontend.get("chart_responsive", False))},
    )
    add_rule(
        "html.chart_maintain_aspect_ratio_true",
        "html",
        "major",
        {"required": bool(frontend.get("chart_required", True)), "value": bool(frontend.get("chart_maintain_aspect_ratio", True))},
    )

    add_rule(
        "action.button_action_unique",
        "action",
        "critical",
        {"required": bool(frontend.get("button_action_unique", True))},
    )
    add_rule(
        "action.showmodal_dom_sequence",
        "action",
        "critical",
        {"api": str(frontend.get("modal_api_required") or "showModal")},
    )
    add_rule(
        "action.button_id_coverage",
        "action",
        "major",
        {"required": bool(frontend.get("button_action_required", True))},
    )

    ordered_categories = ["copy", "html", "action"]
    for left, right in zip(ordered_categories, ordered_categories[1:]):
        edges.append({"from": left, "to": right})

    critical_ids = []
    for rid in DEFAULT_CRITICAL_RULE_IDS:
        if any(node.get("rule_id") == rid for node in nodes):
            critical_ids.append(rid)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "skillpack": plan.get("skillpack") or {},
        "orchestration": {
            "trigger_order": list(orchestration.get("trigger_order") or []),
            "conflict_priority": list(orchestration.get("conflict_priority") or []),
            "degrade_path": list(orchestration.get("degrade_path") or []),
            "stages": list(orchestration.get("stages") or []),
        },
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "summary": {
                "rule_count": len(nodes),
                "critical_rule_count": len([x for x in nodes if str(x.get("severity")) == "critical"]),
            },
        },
        "policy": {
            "min_rule_pass_ratio": 0.85,
            "critical_rule_ids": critical_ids,
            "max_auto_repair_rounds": 2,
            "repair_scope": "failed_pages_or_files_only",
        },
    }


def build_runtime_rule_graph(project_dir: Path, runtime_skill_plan: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
    payload = compile_runtime_rule_graph(runtime_skill_plan=runtime_skill_plan or {})
    path = Path(project_dir) / "runtime_rule_graph.json"
    _save_json(path, payload)
    return path, payload
