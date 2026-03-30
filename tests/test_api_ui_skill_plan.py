import asyncio
import json
from pathlib import Path

import api.server as server


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_api_get_ui_skill_plan(tmp_path, monkeypatch):
    project_id = "proj-1"
    project_name = "示例系统"
    project_dir = tmp_path / project_name
    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "menu_list": [{"page_id": "page_1", "title": "工单页"}],
            "pages": {"page_1": {"page_title": "工单页", "page_description": "处理工单"}},
            "executable_spec": {"page_api_mapping": [], "api_contracts": []},
        },
    )

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(server.db, "get_project", lambda pid: {"id": pid, "name": project_name} if pid == project_id else None)

    payload = asyncio.run(server.get_ui_skill_plan(project_id))
    assert payload["project_id"] == project_id
    assert payload["project_name"] == project_name
    assert int((payload.get("blueprint_summary") or {}).get("page_count") or 0) == 1
    assert Path(payload["profile_path"]).exists()
    assert Path(payload["blueprint_path"]).exists()
    assert Path(payload["contract_path"]).exists()
    assert Path(payload["runtime_skill_path"]).exists()
    assert Path(payload["runtime_rule_graph_path"]).exists()
    assert "skill_compliance_report_path" in payload
    assert "skill_autorepair_report_path" in payload
    assert "skill_policy_report_path" in payload


def test_api_rebuild_ui_skill_plan(tmp_path, monkeypatch):
    project_id = "proj-2"
    project_name = "重建系统"
    project_dir = tmp_path / project_name
    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "menu_list": [{"page_id": "page_1", "title": "统计页"}],
            "pages": {"page_1": {"page_title": "统计页", "page_description": "趋势统计"}},
            "executable_spec": {"page_api_mapping": [], "api_contracts": []},
        },
    )

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(server.db, "get_project", lambda pid: {"id": pid, "name": project_name} if pid == project_id else None)

    payload = asyncio.run(server.rebuild_ui_skill_plan(project_id))
    assert payload["message"] == "UI 技能规划已重建"
    assert payload["project_id"] == project_id
    assert Path(payload["report_path"]).exists()


def test_api_post_ui_skill_plan_supports_force_flag(tmp_path, monkeypatch):
    project_id = "proj-3"
    project_name = "计划系统"
    project_dir = tmp_path / project_name
    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "menu_list": [{"page_id": "page_1", "title": "运营页"}],
            "pages": {"page_1": {"page_title": "运营页", "page_description": "运营分析"}},
            "executable_spec": {"page_api_mapping": [], "api_contracts": []},
        },
    )

    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(server.db, "get_project", lambda pid: {"id": pid, "name": project_name} if pid == project_id else None)

    payload = asyncio.run(server.build_ui_skill_plan(project_id, force=False))
    assert payload["message"] == "UI 技能规划已生成"
    assert payload["project_id"] == project_id
    assert Path(payload["report_path"]).exists()
