import json
from pathlib import Path

from modules.pre_submission_risk import _fix_rebuild_screenshot_report, evaluate_submission_risk


def test_fix_rebuild_screenshot_report(tmp_path: Path):
    project_name = "截图重建项目"
    project_dir = tmp_path / project_name
    screenshot_dir = project_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    (screenshot_dir / "abc123_page_1_full.png").write_bytes(b"x")
    (screenshot_dir / "abc123_page_1_widget_chart_1.png").write_bytes(b"x")
    (screenshot_dir / "abc123_page_1_widget_table_1.png").write_bytes(b"x")

    (project_dir / "screenshot_contract.json").write_text(
        json.dumps(
            {
                "project_name": project_name,
                "pages": {
                    "page_1": {
                        "required_selectors": [
                            {
                                "selector": "[data-claim-id='claim:page_1:block_1']",
                                "claim_id": "claim:page_1:block_1",
                                "block_id": "page_1_block_1",
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = _fix_rebuild_screenshot_report(project_name, project_dir)
    assert result["ok"] is True

    report_path = project_dir / "screenshot_capture_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["legacy_rebuilt"] is True
    assert "page_1" in payload["pages"]


def test_document_preflight_profile_ignores_submission_only_checks(tmp_path: Path, monkeypatch):
    import modules.pre_submission_risk as risk

    project_dir = tmp_path / "示例项目"
    html_dir = tmp_path / "html"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(risk, "_charter_check", lambda _pd: ({"passed": True}, [], True))
    monkeypatch.setattr(risk, "_naming_consistency_check", lambda _pd: ({"passed": True}, [], True))
    monkeypatch.setattr(risk, "_ui_skill_consistency_check", lambda _pn, _pd, _plan: ({"passed": True}, [], True))
    monkeypatch.setattr(risk, "_runtime_skill_compliance_check", lambda _pn, _pd, _hd: ({"passed": True}, [], True))
    monkeypatch.setattr(risk, "_spec_consistency_check", lambda _pd: ({"passed": True}, [], True))
    monkeypatch.setattr(risk, "_claim_evidence_check", lambda _pn, _pd, _hd: ({"passed": True}, [], True))
    monkeypatch.setattr(risk, "_novelty_check", lambda _pn, _pd: ({"passed": True}, [], True))
    # 提交态会失败的两个终态检查
    monkeypatch.setattr(risk, "_document_screenshot_check", lambda _pd, _hd: ({"passed": False}, ["缺少说明书（docx/pdf）"], False))
    monkeypatch.setattr(risk, "_timeline_consistency_check", lambda _pd: ({"passed": False}, ["缺少时间线报告"], False))
    monkeypatch.setattr(risk, "_evidence_chain_check", lambda _pd: ({"passed": False}, ["缺少冻结包 manifest"], False))

    submission_report = evaluate_submission_risk(
        project_name="示例项目",
        project_dir=project_dir,
        html_dir=html_dir,
        block_threshold=75,
        gate_profile="submission",
    )
    assert submission_report["hard_gate"]["passed"] is False
    assert "document_screenshot" in (submission_report.get("failed_checks") or [])
    assert "evidence_chain" in (submission_report.get("failed_checks") or [])

    preflight_report = evaluate_submission_risk(
        project_name="示例项目",
        project_dir=project_dir,
        html_dir=html_dir,
        block_threshold=75,
        gate_profile="document_preflight",
    )
    assert preflight_report["gate_profile"] == "document_preflight"
    assert preflight_report["hard_gate"]["passed"] is True
    assert "document_screenshot" not in (preflight_report.get("failed_checks") or [])
    assert "evidence_chain" not in (preflight_report.get("failed_checks") or [])
