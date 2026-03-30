"""
Runtime skill policy engine.

Builds conflict-resolution decisions for failed rules and outputs
skill_policy_decision_report.json.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


DEFAULT_CONFLICT_PRIORITY = [
    "evidence_auditability",
    "functional_completeness",
    "visual_expression",
    "token_saving",
]


def _action_for_rule(rule_id: str, category: str) -> str:
    rid = str(rule_id or "")
    if rid.startswith("copy."):
        return "rewrite_failed_page_copy"
    if rid.startswith("html."):
        return "repair_failed_html_structure"
    if rid.startswith("action."):
        return "repair_failed_button_actions"
    if category == "copy":
        return "rewrite_failed_page_copy"
    if category == "html":
        return "repair_failed_html_structure"
    if category == "action":
        return "repair_failed_button_actions"
    return "manual_review"


def _rule_dimensions(rule_id: str, category: str) -> List[str]:
    rid = str(rule_id or "").strip()
    cat = str(category or "").strip()

    # 审计可追溯相关规则优先走 evidence_auditability。
    evidence_rules = {
        "copy.first_sentence_prefix",
        "copy.forbid_phrase_after_first",
        "copy.no_date_mentions",
        "copy.page_ban_topics",
        "copy.sentence_count",
        "copy.min_chars",
        "html.no_comments",
        "html.external_script_policy",
        "action.showmodal_dom_sequence",
        "action.button_id_coverage",
    }
    visual_rules = {
        "html.no_rounded_rectangles",
        "copy.avoid_terms",
        "copy.ban_words",
    }
    functional_rules = {
        "action.button_action_unique",
        "copy.page_similarity_diversity",
        "copy.chart_append_sentence",
        "html.chart_responsive_false",
        "html.chart_maintain_aspect_ratio_true",
        "copy.overview_target_chars",
        "copy.overview_ban_words",
        "copy.overview_ban_topics",
    }

    dims: List[str] = []
    if rid in evidence_rules or cat == "action":
        dims.append("evidence_auditability")
    if rid in functional_rules or cat in {"copy", "html"}:
        dims.append("functional_completeness")
    if rid in visual_rules:
        dims.append("visual_expression")
    if not dims:
        dims.append("functional_completeness")
    if rid.startswith("html.") and "visual_expression" not in dims:
        dims.append("visual_expression")
    return dims


def _priority_index(dimension: str, priority_order: List[str]) -> int:
    text = str(dimension or "").strip()
    if text in priority_order:
        return priority_order.index(text)
    return len(priority_order)


def _action_candidates_for_rule(rule_id: str, category: str, priority_order: List[str]) -> List[Dict[str, Any]]:
    action = _action_for_rule(rule_id, category=category)
    dimensions = _rule_dimensions(rule_id, category=category)
    candidates: List[Dict[str, Any]] = []
    for dim in dimensions:
        candidates.append(
            {
                "action": action,
                "dimension": dim,
                "priority_index": _priority_index(dim, priority_order),
            }
        )
    return candidates


def _choose_candidate(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return {"action": "manual_review", "dimension": "functional_completeness", "priority_index": 99}
    ranked = sorted(
        candidates,
        key=lambda item: (
            int(item.get("priority_index") or 99),
            str(item.get("action") or ""),
        ),
    )
    return ranked[0]


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def build_skill_policy_decision(
    project_name: str,
    project_dir: Path,
    runtime_rule_graph: Dict[str, Any] | None = None,
    compliance_report: Dict[str, Any] | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    project_dir = Path(project_dir)
    graph = runtime_rule_graph if isinstance(runtime_rule_graph, dict) else _load_json(project_dir / "runtime_rule_graph.json")
    compliance = compliance_report if isinstance(compliance_report, dict) else _load_json(project_dir / "skill_compliance_report.json")

    nodes = ((graph.get("graph") or {}).get("nodes") or []) if isinstance(graph, dict) else []
    if not isinstance(nodes, list):
        nodes = []
    node_map = {str(item.get("rule_id") or ""): item for item in nodes if isinstance(item, dict) and str(item.get("rule_id") or "").strip()}

    summary = compliance.get("summary") or {}
    failed_ids = [str(x).strip() for x in (summary.get("failed_rule_ids") or []) if str(x).strip()]
    critical_ids = set([str(x).strip() for x in ((graph.get("policy") or {}).get("critical_rule_ids") or []) if str(x).strip()])
    conflict_priority = list(((graph.get("orchestration") or {}).get("conflict_priority") or []))
    if not conflict_priority:
        conflict_priority = list(DEFAULT_CONFLICT_PRIORITY)

    decisions: List[Dict[str, Any]] = []
    action_stats: Dict[str, Dict[str, Any]] = {}
    blocking = 0
    for rid in failed_ids:
        node = node_map.get(rid) or {}
        category = str(node.get("category") or "unknown")
        severity = str(node.get("severity") or "minor")
        is_critical = rid in critical_ids or severity == "critical"
        if is_critical:
            blocking += 1
        candidates = _action_candidates_for_rule(rid, category=category, priority_order=conflict_priority)
        chosen = _choose_candidate(candidates)
        action = str(chosen.get("action") or "manual_review")
        chosen_dimension = str(chosen.get("dimension") or "functional_completeness")
        priority_index = _to_int(chosen.get("priority_index"), 99)

        row = action_stats.setdefault(
            action,
            {
                "action": action,
                "priority_index": priority_index,
                "dimensions": set(),
                "critical_rule_count": 0,
                "rule_count": 0,
                "rule_ids": [],
            },
        )
        row["priority_index"] = min(_to_int(row.get("priority_index"), 99), priority_index)
        row["dimensions"].add(chosen_dimension)
        row["rule_count"] = int(row.get("rule_count") or 0) + 1
        if is_critical:
            row["critical_rule_count"] = int(row.get("critical_rule_count") or 0) + 1
        row["rule_ids"].append(rid)

        decisions.append(
            {
                "rule_id": rid,
                "category": category,
                "severity": severity,
                "is_critical": is_critical,
                "action": action,
                "action_dimension": chosen_dimension,
                "action_priority_index": priority_index,
                "candidate_actions": candidates,
                "conflict_priority": conflict_priority,
            }
        )

    action_resolution = []
    for _, stat in action_stats.items():
        action_resolution.append(
            {
                "action": str(stat.get("action") or ""),
                "priority_index": _to_int(stat.get("priority_index"), 99),
                "dimensions": sorted([str(x) for x in (stat.get("dimensions") or set())]),
                "critical_rule_count": _to_int(stat.get("critical_rule_count"), 0),
                "rule_count": _to_int(stat.get("rule_count"), 0),
                "rule_ids": list(stat.get("rule_ids") or []),
            }
        )
    action_resolution = sorted(
        action_resolution,
        key=lambda item: (
            _to_int(item.get("priority_index"), 99),
            -_to_int(item.get("critical_rule_count"), 0),
            -_to_int(item.get("rule_count"), 0),
            str(item.get("action") or ""),
        ),
    )
    auto_fix_actions = [str(item.get("action") or "") for item in action_resolution if str(item.get("action") or "").strip()]

    payload = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "policy_version": "v3",
        "summary": {
            "failed_rule_count": len(failed_ids),
            "blocking_rule_count": blocking,
            "auto_fix_actions": auto_fix_actions,
            "rule_pass_ratio": float(summary.get("rule_pass_ratio") or 0.0),
            "critical_failed_rules": list(summary.get("critical_failed_rules") or []),
            "action_resolution": action_resolution,
        },
        "orchestration": {
            "trigger_order": list(((graph.get("orchestration") or {}).get("trigger_order") or [])),
            "conflict_priority": conflict_priority,
            "degrade_path": list(((graph.get("orchestration") or {}).get("degrade_path") or [])),
        },
        "decisions": decisions,
    }
    out_path = project_dir / "skill_policy_decision_report.json"
    _save_json(out_path, payload)
    return out_path, payload
