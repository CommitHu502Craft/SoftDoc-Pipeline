import asyncio
import json
from pathlib import Path

import api.server as server
from api.models import UiSkillStudioRequest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_api_run_ui_skill_studio(tmp_path, monkeypatch):
    project_id = "proj-skill-studio"
    project_name = "技能演示系统"
    project_dir = tmp_path / project_name
    _write_json(
        project_dir / "project_plan.json",
        {"project_name": project_name, "menu_list": [], "pages": {}},
    )

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        server.db,
        "get_project",
        lambda pid: {"id": pid, "name": project_name} if pid == project_id else None,
    )

    req = UiSkillStudioRequest(
        intent_text="做一个工单系统，包含首页、工单池、处理台、统计页",
        apply_to_plan=True,
        rebuild_ui_skill=False,
    )
    payload = asyncio.run(server.run_ui_skill_studio(project_id, req))
    assert payload.project_id == project_id
    assert payload.project_name == project_name
    assert Path(payload.studio_plan_path).exists()
    assert Path(payload.runtime_skill_override_path).exists()
    assert Path(payload.spec_path).exists()
    assert payload.override_validation.get("passed") is True
    assert len(payload.actions) >= 2


def test_api_get_ui_skill_studio(tmp_path, monkeypatch):
    project_id = "proj-skill-studio-get"
    project_name = "技能读取系统"
    project_dir = tmp_path / project_name
    _write_json(project_dir / "skill_studio_plan.json", {"actions": ["a"], "decisions": {"domain": "workflow"}})

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        server.db,
        "get_project",
        lambda pid: {"id": pid, "name": project_name} if pid == project_id else None,
    )
    payload = asyncio.run(server.get_ui_skill_studio(project_id))
    assert payload.project_id == project_id
    assert payload.decisions.get("domain") == "workflow"
