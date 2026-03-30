import json
from pathlib import Path

import modules.pre_submission_risk as risk
from modules.project_charter import default_project_charter_template
from modules.skill_autorepair_runner import run_skill_autorepair
from modules.skill_studio import run_skill_studio
from modules.vendor_assets import ensure_vendor_assets_for_html_dir


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _sample_html() -> str:
    return (
        "<html><head>"
        "<script src='https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js'></script>"
        "<script src='vendor/echarts/5.4.3/echarts.min.js'></script>"
        "</head><body>"
        "<div id='widget_chart_1' style='height:300px;'></div>"
        "<button id='btn_query'>查询</button>"
        "<script>"
        "if(window.Chart&&window.Chart.defaults){window.Chart.defaults.responsive=false;window.Chart.defaults.maintainAspectRatio=true;}"
        "document.getElementById('btn_query').addEventListener('click', function(ev){"
        "ev.preventDefault();"
        "var dialog=document.createElement('dialog');"
        "dialog.innerHTML='<button id=\"cancel\">取消</button><button id=\"confirm\">确认</button>';"
        "document.body.appendChild(dialog);"
        "var cancelBtn=dialog.querySelector('#cancel');"
        "var confirmBtn=dialog.querySelector('#confirm');"
        "cancelBtn.addEventListener('click', function(){dialog.close();dialog.remove();});"
        "confirmBtn.addEventListener('click', function(){dialog.close();dialog.remove();});"
        "dialog.showModal();"
        "});"
        "</script>"
        "</body></html>"
    )


def test_skill_studio_closed_loop_gate_pass(tmp_path, monkeypatch):
    project_name = "闭环验证系统"
    project_dir = tmp_path / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    plan_path = project_dir / "project_plan.json"
    _write_json(plan_path, {"project_name": project_name, "menu_list": [], "pages": {}})

    charter = default_project_charter_template(project_name)
    charter["business_scope"] = "覆盖工单录入、处理、查询、统计，不扩展到无关业务。"
    _write_json(project_dir / "project_charter.json", charter)

    studio_result = run_skill_studio(
        project_name=project_name,
        project_dir=project_dir,
        intent_text="做一个工单系统，界面像IDE，页面精美且可审查",
        apply_to_plan=True,
        rebuild_ui_skill=True,
    )
    assert studio_result.get("ok") is True
    assert Path(studio_result.get("spec_path") or "").exists()

    runtime_skill_plan = _load_json(project_dir / "runtime_skill_plan.json")
    frontend_constraints = ((runtime_skill_plan.get("constraints") or {}).get("frontend") or {})

    html_dir = tmp_path / "temp_build" / project_name / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    ensure_vendor_assets_for_html_dir(html_dir=html_dir, frontend_constraints=frontend_constraints)

    plan = _load_json(plan_path)
    for page_id in (plan.get("pages") or {}).keys():
        (html_dir / f"{page_id}.html").write_text(_sample_html(), encoding="utf-8")

    repair = run_skill_autorepair(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        max_rounds=2,
    )
    assert bool(repair.get("fixed")) is True
    rebuild_spec = risk._fix_rebuild_spec(project_name, project_dir)
    assert bool(rebuild_spec.get("ok")) is True

    monkeypatch.setattr(risk, "_claim_evidence_check", lambda _pn, _pd, _hd: ({"passed": True}, [], True))
    monkeypatch.setattr(risk, "_novelty_check", lambda _pn, _pd: ({"passed": True}, [], True))

    report = risk.evaluate_submission_risk(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        block_threshold=75,
        gate_profile="document_preflight",
    )

    assert (report.get("hard_gate") or {}).get("passed") is True
    assert report.get("should_block_submission") is False
