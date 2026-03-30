import json
from pathlib import Path

from modules.project_charter import (
    normalize_project_charter,
    validate_project_charter,
)
from modules.executable_spec_builder import (
    build_executable_spec,
    validate_executable_spec,
)
from modules.runtime_verifier import run_runtime_verification
from modules.freeze_package import build_freeze_package


def _sample_charter(project_name: str = "测试项目"):
    return normalize_project_charter(
        {
            "project_name": project_name,
            "business_scope": "覆盖业务录入、审核与查询流程",
            "user_roles": [
                {"name": "系统管理员", "responsibility": "配置与审计"},
                {"name": "业务操作员", "responsibility": "录入和查询"},
            ],
            "core_flows": [
                {"name": "业务提交流程", "steps": ["录入", "提交", "审核通过"], "success_criteria": "状态为通过"}
            ],
            "non_functional_constraints": ["关键页面响应<2秒"],
            "acceptance_criteria": ["可完成端到端流程"],
        },
        project_name=project_name,
    )


def _sample_plan(project_name: str = "测试项目"):
    return {
        "project_name": project_name,
        "menu_list": [
            {"title": "业务录入", "page_id": "page_1"},
            {"title": "业务审核", "page_id": "page_2"},
        ],
        "pages": {
            "page_1": {"page_title": "业务录入", "page_description": "录入和提交"},
            "page_2": {"page_title": "业务审核", "page_description": "审核处理"},
        },
        "code_blueprint": {
            "entities": ["BusinessRecord", "AuditTask"],
            "controllers": [
                {
                    "name": "BusinessController",
                    "page_id": "page_1",
                    "methods": [
                        {"name": "submit", "desc": "提交业务", "http": "POST /api/business/submit"},
                    ],
                }
            ],
        },
        "genome": {"target_language": "python"},
    }


def test_project_charter_validation_gate():
    broken = normalize_project_charter({}, project_name="缺失章程")
    errors = validate_project_charter(broken)
    assert errors
    assert any("business_scope" in e for e in errors)


def test_executable_spec_builder_core_sections():
    charter = _sample_charter()
    plan = _sample_plan()
    spec = build_executable_spec(plan, charter)
    errors = validate_executable_spec(spec)
    assert errors == []
    assert spec["entities"]
    assert spec["api_contracts"]
    assert spec["permission_matrix"]
    assert spec["page_api_mapping"]


def test_runtime_verifier_and_freeze_package(tmp_path: Path):
    project_name = "回归项目"
    project_dir = tmp_path / "output" / project_name
    html_dir = tmp_path / "temp_build" / project_name / "html"
    screenshots_dir = project_dir / "screenshots"
    code_dir = project_dir / "aligned_code"
    project_dir.mkdir(parents=True)
    html_dir.mkdir(parents=True)
    screenshots_dir.mkdir(parents=True)
    code_dir.mkdir(parents=True)

    charter = _sample_charter(project_name)
    plan = _sample_plan(project_name)
    spec = build_executable_spec(plan, charter)

    (project_dir / "project_plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (project_dir / "project_charter.json").write_text(json.dumps(charter, ensure_ascii=False), encoding="utf-8")
    (project_dir / "project_executable_spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    (html_dir / "page_1.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    (screenshots_dir / "page_1_full.png").write_bytes(b"fake")
    (code_dir / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    passed, report_path, report = run_runtime_verification(project_name, project_dir, html_dir)
    assert passed is True
    assert report_path.exists()
    assert report["overall_passed"] is True

    freeze_result = build_freeze_package(project_name, project_dir, html_dir)
    assert Path(freeze_result["manifest_path"]).exists()
    assert Path(freeze_result["hashes_path"]).exists()
    assert Path(freeze_result["zip_path"]).exists()
    assert Path(freeze_result["reproducibility_path"]).exists()
    manifest = json.loads(Path(freeze_result["manifest_path"]).read_text(encoding="utf-8"))
    assert "pipeline_protocol_version" in manifest
    assert "project_charter.json" in manifest.get("evidence_chain", [])
    assert "project_executable_spec.json" in manifest.get("evidence_chain", [])
    assert "runtime_verification_report.json" in manifest.get("evidence_chain", [])
    assert "novelty_quality_report.json" in manifest.get("missing_evidence", [])
    repro = json.loads(Path(freeze_result["reproducibility_path"]).read_text(encoding="utf-8"))
    assert repro.get("passed") is True


def test_runtime_verifier_replay_requires_api_mapping(tmp_path: Path):
    project_name = "回放收紧项目"
    project_dir = tmp_path / "output" / project_name
    html_dir = tmp_path / "temp_build" / project_name / "html"
    screenshots_dir = project_dir / "screenshots"
    code_dir = project_dir / "aligned_code"
    project_dir.mkdir(parents=True)
    html_dir.mkdir(parents=True)
    screenshots_dir.mkdir(parents=True)
    code_dir.mkdir(parents=True)

    charter = _sample_charter(project_name)
    plan = _sample_plan(project_name)
    spec = build_executable_spec(plan, charter)
    spec["page_api_mapping"] = []  # 强制制造“页面没有接口映射”的场景

    (project_dir / "project_plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (project_dir / "project_charter.json").write_text(json.dumps(charter, ensure_ascii=False), encoding="utf-8")
    (project_dir / "project_executable_spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    (html_dir / "page_1.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    (screenshots_dir / "page_1_full.png").write_bytes(b"fake")
    (code_dir / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    passed, _, report = run_runtime_verification(project_name, project_dir, html_dir)
    assert passed is False
    replay = report.get("checks", {}).get("business_path_replay", {})
    assert replay.get("passed") is False
