import asyncio
import json
from pathlib import Path

import api.server as server_module
import api.task_manager as task_manager_module
from api.models import SpecReviewApproveRequest
from modules.spec_review import approve_spec_review, get_spec_review_status, save_spec_review_artifacts


def _sample_plan(project_name: str) -> dict:
    return {
        "project_name": project_name,
        "menu_list": [{"title": "首页", "page_id": "page_1"}],
        "pages": {"page_1": {"page_title": "首页", "page_description": "展示信息"}},
        "code_blueprint": {"entities": ["Order"]},
    }


def _sample_spec(project_name: str) -> dict:
    return {
        "project_name": project_name,
        "entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}],
        "state_machines": [{"name": "订单流转", "states": ["draft", "done"], "transitions": [{"from": "draft", "to": "done"}]}],
        "permission_matrix": [{"role": "管理员", "permissions": ["order.read", "order.write"]}],
        "api_contracts": [{"name": "查询订单", "http_method": "GET", "path": "/api/orders", "description": "查询列表"}],
        "page_api_mapping": [{"page_id": "page_1", "apis": ["/api/orders"]}],
    }


def _prepare_project(tmp_path: Path, project_name: str) -> Path:
    project_dir = tmp_path / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project_plan.json").write_text(
        json.dumps(_sample_plan(project_name), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    spec = _sample_spec(project_name)
    (project_dir / "project_executable_spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_spec_review_artifacts(project_dir, project_name, spec)
    return project_dir


def test_task_manager_blocks_code_when_spec_not_approved(tmp_path, monkeypatch):
    project_name = "门禁阻断项目"
    _prepare_project(tmp_path, project_name)
    monkeypatch.setattr(task_manager_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(task_manager_module.TaskManager, "_auto_confirm_spec_review_enabled", staticmethod(lambda: False))

    manager = task_manager_module.TaskManager()
    task_id = manager.create_task("pid-1", project_name)
    ok = manager._run_code(project_name, task_id)

    assert ok is False
    logs = manager.get_task(task_id)["logs"]
    assert any("规格未确认" in item["message"] for item in logs)


def test_task_manager_auto_approves_spec_for_code(tmp_path, monkeypatch):
    project_name = "自动确认规格项目"
    project_dir = _prepare_project(tmp_path, project_name)
    monkeypatch.setattr(task_manager_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(task_manager_module.TaskManager, "_auto_confirm_spec_review_enabled", staticmethod(lambda: True))

    called = {}

    def fake_generate_code_from_plan(json_path: str, code_dir: str):
        called["ok"] = True
        out_dir = Path(code_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "main.py"
        out_file.write_text("def run():\n    return 1\n", encoding="utf-8")
        return [str(out_file)]

    import modules.code_generator as code_generator_module

    monkeypatch.setattr(code_generator_module, "generate_code_from_plan", fake_generate_code_from_plan)

    manager = task_manager_module.TaskManager()
    task_id = manager.create_task("pid-1b", project_name)
    ok = manager._run_code(project_name, task_id)

    assert ok is True
    assert called.get("ok") is True
    status = get_spec_review_status(project_dir, project_dir / "project_executable_spec.json")
    assert status.get("approved") is True


def test_task_manager_allows_code_after_spec_approved(tmp_path, monkeypatch):
    project_name = "门禁放行项目"
    project_dir = _prepare_project(tmp_path, project_name)
    approve_spec_review(project_dir, reviewer="tester")
    monkeypatch.setattr(task_manager_module, "OUTPUT_DIR", tmp_path)

    called = {}

    def fake_generate_code_from_plan(json_path: str, code_dir: str):
        called["ok"] = True
        out_dir = Path(code_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "main.py"
        out_file.write_text("def run():\n    return 1\n", encoding="utf-8")
        return [str(out_file)]

    import modules.code_generator as code_generator_module

    monkeypatch.setattr(code_generator_module, "generate_code_from_plan", fake_generate_code_from_plan)

    manager = task_manager_module.TaskManager()
    task_id = manager.create_task("pid-2", project_name)
    ok = manager._run_code(project_name, task_id)

    assert ok is True
    assert called.get("ok") is True


def test_api_spec_review_endpoints(tmp_path, monkeypatch):
    project_name = "规格接口项目"
    _prepare_project(tmp_path, project_name)

    monkeypatch.setattr(server_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(server_module.db, "get_project", lambda _pid: {"name": project_name})

    status = asyncio.run(server_module.get_project_spec_review_status("pid-3"))
    assert status.approved is False
    assert status.review_status in {"pending", "missing_spec"}

    approved = asyncio.run(
        server_module.approve_project_spec_review("pid-3", SpecReviewApproveRequest(reviewer="api-test"))
    )
    assert approved.approved is True
    assert approved.reviewer == "api-test"


def test_batch_run_spec_precheck_only_for_no_spec_prefix():
    assert server_module._requires_preapproved_spec(["plan", "spec", "code", "verify"]) is False
    assert server_module._requires_preapproved_spec(["html", "code", "verify"]) is True
