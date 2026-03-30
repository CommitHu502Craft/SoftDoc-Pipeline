import asyncio
import json
from pathlib import Path

import api.server as server
from api.models import UiSkillPolicyAutofixRequest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_api_ui_skill_policy_autofix_runs_autorepair(tmp_path, monkeypatch):
    project_id = "proj-policy-fix"
    project_name = "策略修复系统"
    project_dir = tmp_path / project_name
    _write_json(project_dir / "project_plan.json", {"project_name": project_name, "pages": {}})

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        server.db,
        "get_project",
        lambda pid: {"id": pid, "name": project_name} if pid == project_id else None,
    )

    calls = {"precheck": 0, "autorepair": 0}

    def fake_precheck(*, project_name, project_dir, html_dir, block_threshold, enable_auto_fix, max_fix_rounds, gate_profile="submission"):
        calls["precheck"] += 1
        if calls["precheck"] == 1:
            report = {
                "project_name": project_name,
                "should_block_submission": True,
                "hard_gate": {"passed": False},
                "blocking_issues": ["运行时技能关键规则失败"],
                "checks": {
                    "runtime_skill_compliance": {
                        "policy_auto_fix_actions": ["repair_failed_html_structure"],
                        "critical_failed_rules": ["action.showmodal_dom_sequence"],
                    }
                },
            }
        else:
            report = {
                "project_name": project_name,
                "should_block_submission": False,
                "hard_gate": {"passed": True},
                "blocking_issues": [],
                "checks": {
                    "runtime_skill_compliance": {
                        "policy_auto_fix_actions": [],
                        "critical_failed_rules": [],
                    }
                },
            }
        report_path = Path(project_dir) / "submission_risk_report.json"
        _write_json(report_path, report)
        return (not bool(report.get("should_block_submission"))), report_path, report

    def fake_run_autorepair(*, project_name, project_dir, html_dir, max_rounds, policy_actions=None):
        calls["autorepair"] += 1
        assert "repair_failed_html_structure" in (policy_actions or [])
        report_path = Path(project_dir) / "skill_autorepair_report.json"
        _write_json(
            report_path,
            {"project_name": project_name, "fixed": True, "rounds": [{"round": 1}], "max_rounds": max_rounds},
        )
        return {"fixed": True, "rounds": [{"round": 1}], "report_path": str(report_path)}

    monkeypatch.setattr(server, "run_submission_risk_precheck", fake_precheck)
    monkeypatch.setattr(server, "run_skill_autorepair", fake_run_autorepair)

    req = UiSkillPolicyAutofixRequest(max_rounds=2, block_threshold=75)
    payload = asyncio.run(server.run_ui_skill_policy_autofix(project_id, req))
    assert payload.project_id == project_id
    assert payload.attempted is True
    assert payload.fixed is True
    assert calls["autorepair"] == 1
    assert "repair_failed_html_structure" in payload.policy_actions


def test_api_ui_skill_policy_autofix_skips_when_no_actions(tmp_path, monkeypatch):
    project_id = "proj-policy-fix-no-action"
    project_name = "策略修复无动作系统"
    project_dir = tmp_path / project_name
    _write_json(project_dir / "project_plan.json", {"project_name": project_name, "pages": {}})

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        server.db,
        "get_project",
        lambda pid: {"id": pid, "name": project_name} if pid == project_id else None,
    )

    calls = {"precheck": 0, "autorepair": 0}

    def fake_precheck(*, project_name, project_dir, html_dir, block_threshold, enable_auto_fix, max_fix_rounds, gate_profile="submission"):
        calls["precheck"] += 1
        report = {
            "project_name": project_name,
            "should_block_submission": True,
            "hard_gate": {"passed": False},
            "blocking_issues": ["需要人工处理"],
            "checks": {"runtime_skill_compliance": {"policy_auto_fix_actions": [], "critical_failed_rules": []}},
        }
        report_path = Path(project_dir) / "submission_risk_report.json"
        _write_json(report_path, report)
        return False, report_path, report

    def fake_run_autorepair(*, project_name, project_dir, html_dir, max_rounds, policy_actions=None):
        calls["autorepair"] += 1
        return {"fixed": False}

    monkeypatch.setattr(server, "run_submission_risk_precheck", fake_precheck)
    monkeypatch.setattr(server, "run_skill_autorepair", fake_run_autorepair)

    req = UiSkillPolicyAutofixRequest(max_rounds=1, block_threshold=75)
    payload = asyncio.run(server.run_ui_skill_policy_autofix(project_id, req))
    assert payload.project_id == project_id
    assert payload.attempted is False
    assert payload.fixed is False
    assert calls["autorepair"] == 0
