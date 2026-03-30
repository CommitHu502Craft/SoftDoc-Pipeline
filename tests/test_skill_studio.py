import json
from pathlib import Path

from modules.skill_studio import run_skill_studio


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_skill_studio_generates_override_and_plan(tmp_path: Path):
    project_name = "工单示例系统"
    project_dir = tmp_path / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project_plan.json").write_text(
        json.dumps({"project_name": project_name, "menu_list": [], "pages": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = run_skill_studio(
        project_name=project_name,
        project_dir=project_dir,
        intent_text="我想做一个工单管理系统，页面要首页、工单池、处理台、统计页，界面精美，尽量减少token消耗",
        apply_to_plan=True,
        rebuild_ui_skill=False,
    )
    assert result.get("ok") is True
    assert Path(result.get("skill_studio_plan_path") or "").exists()
    assert Path(result.get("runtime_skill_override_path") or "").exists()
    assert Path(result.get("spec_path") or "").exists()
    assert "rebuild_executable_spec" in (result.get("actions") or [])

    studio = _load_json(project_dir / "skill_studio_plan.json")
    decisions = studio.get("decisions") or {}
    assert str(decisions.get("domain") or "") == "workflow"
    assert int(decisions.get("page_count") or 0) >= 6

    override = _load_json(project_dir / "runtime_skill_override.json")
    constraints = override.get("constraints") or {}
    required_pages = constraints.get("required_pages") or []
    assert isinstance(required_pages, list) and len(required_pages) >= 6

    plan = _load_json(project_dir / "project_plan.json")
    assert len(plan.get("menu_list") or []) >= 6
    assert len(plan.get("pages") or {}) >= 6
    spec = _load_json(project_dir / "project_executable_spec.json")
    assert len(spec.get("api_contracts") or []) > 0
