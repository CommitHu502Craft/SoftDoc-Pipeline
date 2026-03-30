import asyncio
import json
from pathlib import Path

from fastapi import BackgroundTasks
from fastapi import HTTPException

import api.server as server_module
from api.models import (
    PipelineStep,
    ProjectCharterUpdateRequest,
    SelfHealRunRequest,
    SubmissionRiskCheckRequest,
)
from modules.project_charter import validate_project_charter


def _valid_charter(project_name: str) -> dict:
    return {
        "project_name": project_name,
        "business_scope": f"{project_name} 聚焦业务录入、审核与查询闭环",
        "user_roles": [
            {"name": "系统管理员", "responsibility": "配置与审计"},
            {"name": "业务操作员", "responsibility": "录入与提交"},
        ],
        "core_flows": [
            {
                "name": "主流程",
                "steps": ["录入数据", "提交审核", "查询结果"],
                "success_criteria": "记录可追溯、状态可查询",
            }
        ],
        "non_functional_constraints": ["关键页面响应<2秒"],
        "acceptance_criteria": ["可完成端到端主流程"],
    }


def _patch_project_db(monkeypatch, project: dict):
    def _get_project(project_id: str):
        if project_id == project["id"]:
            return project
        return None

    def _update_project(project_id: str, updates: dict):
        if project_id != project["id"]:
            return None
        project.update(updates)
        charter = updates.get("project_charter")
        if isinstance(charter, dict):
            project["charter_completed"] = len(validate_project_charter(charter)) == 0
            project["charter_summary"] = {
                "business_scope": charter.get("business_scope", ""),
                "role_count": len(charter.get("user_roles") or []),
                "flow_count": len(charter.get("core_flows") or []),
                "nfr_count": len(charter.get("non_functional_constraints") or []),
                "acceptance_count": len(charter.get("acceptance_criteria") or []),
            }
        return project

    monkeypatch.setattr(server_module.db, "get_project", _get_project)
    monkeypatch.setattr(server_module.db, "update_project", _update_project)


def test_api_charter_endpoints(tmp_path, monkeypatch):
    output_root = tmp_path / "output"
    monkeypatch.setattr(server_module, "OUTPUT_DIR", output_root)

    project = {
        "id": "pid-charter",
        "name": "章程测试项目",
        "project_charter": {},
        "charter_summary": {},
        "charter_completed": False,
    }
    _patch_project_db(monkeypatch, project)

    update_req = ProjectCharterUpdateRequest(charter=_valid_charter(project["name"]))
    updated = asyncio.run(server_module.update_project_charter(project["id"], update_req))
    assert updated.charter_completed is True
    assert updated.validation_errors == []
    assert Path(updated.charter_path).exists()

    drafted_charter = _valid_charter(project["name"])
    drafted_charter["business_scope"] = "AI 草拟章程业务边界"
    monkeypatch.setattr(
        server_module,
        "draft_project_charter_with_ai",
        lambda project_name, context_hint="": drafted_charter,
    )
    drafted = asyncio.run(server_module.draft_project_charter(project["id"]))
    assert drafted.charter["business_scope"] == "AI 草拟章程业务边界"
    assert drafted.charter_completed is True

    fetched = asyncio.run(server_module.get_project_charter(project["id"]))
    assert fetched.project_name == project["name"]
    assert fetched.charter_completed is True


def test_api_self_heal_run_inserts_plan_and_spec(tmp_path, monkeypatch):
    output_root = tmp_path / "output"
    monkeypatch.setattr(server_module, "OUTPUT_DIR", output_root)

    project = {
        "id": "pid-heal",
        "name": "自愈项目",
        "project_charter": {},
        "charter_summary": {},
        "charter_completed": False,
    }
    _patch_project_db(monkeypatch, project)

    monkeypatch.setattr(
        server_module,
        "draft_project_charter_with_ai",
        lambda project_name, context_hint="": _valid_charter(project_name),
    )

    created = {}

    def _create_task(project_id, project_name, code_generation_overrides=None, project_charter=None):
        created["project_id"] = project_id
        created["project_name"] = project_name
        created["project_charter"] = project_charter or {}
        return "task-self-heal"

    async def _run_pipeline(*args, **kwargs):
        return None

    monkeypatch.setattr(server_module.task_manager, "create_task", _create_task)
    monkeypatch.setattr(server_module.task_manager, "run_pipeline", _run_pipeline)

    req = SelfHealRunRequest(steps=[PipelineStep.CODE, PipelineStep.VERIFY])
    result = asyncio.run(
        server_module.self_heal_run_pipeline(project["id"], req, BackgroundTasks())
    )
    assert result["task_id"] == "task-self-heal"
    assert "charter_auto_drafted" in result["actions"]
    assert "plan_inserted" in result["actions"]
    assert "spec_inserted" in result["actions"]
    assert result["resolved_steps"][0] == "plan"
    assert created["project_charter"]


def test_api_submission_risk_check_endpoint(tmp_path, monkeypatch):
    output_root = tmp_path / "output"
    monkeypatch.setattr(server_module, "OUTPUT_DIR", output_root)
    monkeypatch.setattr(server_module, "BASE_DIR", tmp_path)

    project = {
        "id": "pid-risk",
        "name": "风险测试项目",
        "project_charter": {},
        "charter_summary": {},
        "charter_completed": False,
    }
    _patch_project_db(monkeypatch, project)

    project_dir = output_root / project["name"]
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project_charter.json").write_text(
        json.dumps(_valid_charter(project["name"]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = asyncio.run(
        server_module.check_submission_risk(
            project["id"],
            SubmissionRiskCheckRequest(block_threshold=75),
        )
    )
    assert result.project_id == project["id"]
    assert Path(result.report_path).exists()
    assert isinstance(result.report.get("score"), int)


def test_start_submit_queue_all_blocked_by_risk(monkeypatch):
    pending = [
        {
            "id": "queue-1",
            "project_id": "pid-risk-block",
            "project_name": "高风险项目",
            "status": "pending",
        }
    ]
    updated = {}

    monkeypatch.setattr(server_module.submit_queue_db, "is_running", False)
    monkeypatch.setattr(server_module.submit_queue_db, "get_queue", lambda: pending)
    monkeypatch.setattr(
        server_module.submit_queue_db,
        "update_item",
        lambda item_id, payload: updated.setdefault(item_id, payload),
    )
    monkeypatch.setattr(
        server_module,
        "run_submission_risk_precheck",
        lambda **kwargs: (
            False,
            Path("/tmp/submission_risk_report.json"),
            {"score": 40, "blocking_issues": ["证据链不完整"]},
        ),
    )

    try:
        asyncio.run(
            server_module.start_submit_queue(
                server_module.StartSubmitRequest(account_id=None),
                BackgroundTasks(),
            )
        )
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 400
        assert "风险预检拦截" in str(e.detail)
        assert "queue-1" in updated


def test_start_submit_queue_mixed_gate_results(monkeypatch):
    pending = [
        {
            "id": "queue-ok",
            "project_id": "pid-ok",
            "project_name": "可提交项目",
            "status": "pending",
        },
        {
            "id": "queue-block",
            "project_id": "pid-block",
            "project_name": "阻断项目",
            "status": "pending",
        },
    ]
    updates = {}

    monkeypatch.setattr(server_module.submit_queue_db, "is_running", False)
    monkeypatch.setattr(server_module.submit_queue_db, "get_queue", lambda: pending)
    monkeypatch.setattr(
        server_module.submit_queue_db,
        "update_item",
        lambda item_id, payload: updates.setdefault(item_id, payload),
    )

    class _DummyBackgroundTasks:
        def __init__(self):
            self.calls = []

        def add_task(self, fn, *args, **kwargs):
            self.calls.append((fn, args, kwargs))

    bg = _DummyBackgroundTasks()

    def _risk_precheck(**kwargs):
        if kwargs.get("project_name") == "可提交项目":
            return True, Path("/tmp/ok.json"), {"score": 92, "blocking_issues": []}
        return False, Path("/tmp/block.json"), {
            "score": 48,
            "blocking_issues": ["证据链不完整"],
            "auto_fix": {
                "attempted": True,
                "fixed": False,
                "rounds": [
                    {
                        "action_results": [
                            {"ok": True, "action": "regen_html"},
                            {"ok": False, "action": "freeze_package"},
                        ]
                    }
                ],
            },
        }

    monkeypatch.setattr(server_module, "run_submission_risk_precheck", _risk_precheck)

    result = asyncio.run(
        server_module.start_submit_queue(
            server_module.StartSubmitRequest(account_id=None),
            bg,  # type: ignore[arg-type]
        )
    )
    assert result["eligible"] == 1
    assert result["blocked"] == 1
    assert result["blocked_items"][0]["project_name"] == "阻断项目"
    assert "regen_html" in (result["blocked_items"][0].get("auto_fixed_actions") or [])
    assert "queue-block" in updates


def test_api_llm_usage_snapshot_endpoint(monkeypatch):
    called = {"max_runs": None}

    def _snapshot(max_runs: int = 20):
        called["max_runs"] = max_runs
        return {
            "generated_at": 123456.0,
            "config": {
                "total_calls": 120,
                "total_failures": 32,
                "stages": {"default": 40},
                "cache_ttl_seconds": 1800.0,
                "cache_max_entries": 256,
            },
            "cache": {"entries": 2, "max_entries": 256},
            "summary": {"active_runs": 1, "total_calls": 3, "total_failures": 0},
            "runs": [
                {
                    "run_id": "api:demo",
                    "started_at": 123000.0,
                    "total_calls": 3,
                    "total_failures": 0,
                    "stage_calls": {"plan": 1, "code": 2},
                    "stage_failures": {},
                    "exhausted_by_failures": False,
                }
            ],
        }

    monkeypatch.setattr(server_module.llm_budget, "get_runtime_snapshot", _snapshot)
    result = asyncio.run(server_module.get_llm_usage(max_runs=7))

    assert called["max_runs"] == 7
    assert result["summary"]["total_calls"] == 3
    assert result["cache"]["entries"] == 2


def test_signature_stats_scan_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(server_module, "OUTPUT_DIR", tmp_path / "output")

    sign_dir = tmp_path / "签章页"
    signed_dir = tmp_path / "已签名"
    final_dir = tmp_path / "最终提交"
    submitted_dir = (tmp_path / "output" / "已提交")

    sign_dir.mkdir(parents=True, exist_ok=True)
    signed_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    submitted_dir.mkdir(parents=True, exist_ok=True)

    (sign_dir / "a.pdf").write_bytes(b"x")
    (sign_dir / "b.pdf").write_bytes(b"x")
    (signed_dir / "a.pdf").write_bytes(b"x")
    (final_dir / "a.pdf").write_bytes(b"x")
    (submitted_dir / "p1").mkdir()
    (submitted_dir / "p2").mkdir()

    stats = asyncio.run(server_module.get_signature_stats())
    assert stats.pending_download == 2
    assert stats.downloaded == 2
    assert stats.signed == 1
    assert stats.scan_effected == 1
