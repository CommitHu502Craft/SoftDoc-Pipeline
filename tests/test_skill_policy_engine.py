from pathlib import Path

from modules.skill_policy_engine import build_skill_policy_decision


def test_skill_policy_engine_outputs_actions(tmp_path: Path):
    graph = {
        "policy": {"critical_rule_ids": ["action.showmodal_dom_sequence"]},
        "orchestration": {"conflict_priority": ["evidence_auditability", "functional_completeness"]},
        "graph": {
            "nodes": [
                {"rule_id": "copy.first_sentence_prefix", "category": "copy", "severity": "critical"},
                {"rule_id": "html.no_comments", "category": "html", "severity": "major"},
                {"rule_id": "action.showmodal_dom_sequence", "category": "action", "severity": "critical"},
            ]
        },
    }
    compliance = {
        "summary": {
            "failed_rule_ids": ["copy.first_sentence_prefix", "action.showmodal_dom_sequence"],
            "critical_failed_rules": ["action.showmodal_dom_sequence"],
            "rule_pass_ratio": 0.7,
        }
    }
    out_path, payload = build_skill_policy_decision(
        project_name="策略项目",
        project_dir=tmp_path,
        runtime_rule_graph=graph,
        compliance_report=compliance,
    )
    assert out_path.exists()
    summary = payload.get("summary") or {}
    assert int(summary.get("failed_rule_count") or 0) == 2
    assert int(summary.get("blocking_rule_count") or 0) >= 1
    actions = summary.get("auto_fix_actions") or []
    assert "rewrite_failed_page_copy" in actions
    assert "repair_failed_button_actions" in actions
    resolution = summary.get("action_resolution") or []
    assert isinstance(resolution, list) and len(resolution) >= 1
    assert str((resolution[0] or {}).get("action") or "").strip() != ""
    for item in resolution:
        assert "priority_index" in item


def test_skill_policy_engine_prioritizes_evidence_dimension(tmp_path: Path):
    graph = {
        "policy": {"critical_rule_ids": ["action.showmodal_dom_sequence"]},
        "orchestration": {
            "conflict_priority": [
                "evidence_auditability",
                "functional_completeness",
                "visual_expression",
                "token_saving",
            ]
        },
        "graph": {
            "nodes": [
                {"rule_id": "copy.page_similarity_diversity", "category": "copy", "severity": "major"},
                {"rule_id": "action.showmodal_dom_sequence", "category": "action", "severity": "critical"},
            ]
        },
    }
    compliance = {
        "summary": {
            "failed_rule_ids": ["copy.page_similarity_diversity", "action.showmodal_dom_sequence"],
            "critical_failed_rules": ["action.showmodal_dom_sequence"],
            "rule_pass_ratio": 0.6,
        }
    }
    _, payload = build_skill_policy_decision(
        project_name="策略优先级项目",
        project_dir=tmp_path,
        runtime_rule_graph=graph,
        compliance_report=compliance,
    )
    resolution = ((payload.get("summary") or {}).get("action_resolution") or [])
    assert len(resolution) >= 2
    # evidence 维度动作应排在更前。
    assert str((resolution[0] or {}).get("action") or "") == "repair_failed_button_actions"
