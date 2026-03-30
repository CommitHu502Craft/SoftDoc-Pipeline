import json
from pathlib import Path

from modules.artifact_naming import preferred_artifact_path
from modules.document_generator import DocumentGenerator
from modules.pre_submission_risk import _document_screenshot_check


def test_save_examiner_material_sections_pass(tmp_path: Path):
    generator = DocumentGenerator.__new__(DocumentGenerator)
    generator.output_path = tmp_path / "测试软件_操作说明书.docx"
    generator.plan = {"project_name": "测试软件", "pages": {"page_1": {"page_title": "首页"}}}
    generator.project_spec = {
        "api_contracts": [{"id": "api_1"}],
        "entities": [{"name": "Order"}],
    }

    (tmp_path / "runtime_verification_report.json").write_text(
        json.dumps(
            {
                "overall_passed": True,
                "checks": {
                    "business_path_replay": {
                        "passed": True,
                        "match_ratio": 1.0,
                    }
                },
                "summary": {"replay_passed": True},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    freeze_dir = tmp_path / "freeze_package"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    (freeze_dir / "timeline_consistency_report.json").write_text(
        json.dumps(
            {
                "passed": True,
                "issues": [],
                "warnings": [],
                "declared_timeline": {
                    "development_started_at": "2025-01-01",
                    "development_completed_at": "2025-03-01",
                    "published_at": "2025-03-05",
                    "submit_at": "2025-03-10",
                    "organization_established_at": "2024-12-01",
                },
                "inferred_timeline": {
                    "development_started_at": "2025-01-02",
                    "development_completed_at": "2025-02-28",
                    "frozen_at": "2025-03-11T10:00:00",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / "novelty_quality_report.json").write_text(
        json.dumps({"recommendation": "safe", "max_similarity": 0.32}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "semantic_homogeneity_report.json").write_text(
        json.dumps({"top_similarity": 0.45, "should_rewrite": False, "rewritten": False}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    matrix = {
        "summary": {"total_claims": 1, "passed_claims": 1, "binding_ratio": 1.0},
        "hard_blocking_issues": [],
        "claims": [
            {
                "claim_id": "page:page_1",
                "claim_type": "page_capability",
                "claim_text": "首页可被执行和回放",
                "page_id": "page_1",
                "page_title": "首页",
                "evidence": {
                    "screenshot_paths": ["screenshots/a_page_1_full.png"],
                    "api_contracts": [{"http_method": "GET", "path": "/api/home/list"}],
                    "code_hits": ["aligned_code/controller/home.py"],
                    "runtime_replay_matches": [{"flow": "主流程", "passed": True}],
                },
                "passed": True,
                "missing_evidence": [],
            }
        ],
    }

    context = {"project_name": "测试软件"}
    report = generator._save_examiner_material_sections(context, matrix)

    assert report["passed"] is True
    assert (tmp_path / "examiner_material_report.json").exists()
    assert (tmp_path / "examiner_material_sections.md").exists()
    assert len(context.get("feature_evidence_rows") or []) == 1
    assert context.get("examiner_summary")
    assert context.get("timeline_review_text")
    assert context.get("novelty_review_text")


def test_document_screenshot_check_requires_examiner_material_report(tmp_path: Path):
    project_dir = tmp_path / "项目A"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir = tmp_path / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    (html_dir / "page1.html").write_text("<html></html>", encoding="utf-8")
    (html_dir / "page2.html").write_text("<html></html>", encoding="utf-8")

    screenshots = project_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    (screenshots / "a.png").write_bytes(b"x")
    (screenshots / "b.png").write_bytes(b"x")

    docx_path = preferred_artifact_path(project_dir, project_name=project_dir.name, artifact_key="manual_docx")
    docx_path.write_bytes(b"x")

    (project_dir / "doc_code_consistency_report.json").write_text(
        json.dumps({"passed": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    detail, blockers, passed = _document_screenshot_check(project_dir, html_dir)
    assert passed is False
    assert detail["examiner_material_report_exists"] is False
    assert any("审查版材料报告" in item for item in blockers)


def test_save_examiner_material_sections_document_stage_allows_timeline_deferred(tmp_path: Path):
    generator = DocumentGenerator.__new__(DocumentGenerator)
    generator.output_path = tmp_path / "测试软件_操作说明书.docx"
    generator.plan = {"project_name": "测试软件", "pages": {"page_1": {"page_title": "首页"}}}
    generator.project_spec = {
        "api_contracts": [{"id": "api_1"}],
        "entities": [{"name": "Order"}],
    }

    (tmp_path / "runtime_verification_report.json").write_text(
        json.dumps(
            {
                "overall_passed": True,
                "checks": {
                    "business_path_replay": {
                        "passed": True,
                        "match_ratio": 1.0,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / "novelty_quality_report.json").write_text(
        json.dumps({"recommendation": "safe", "max_similarity": 0.12}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "semantic_homogeneity_report.json").write_text(
        json.dumps({"top_similarity": 0.2, "should_rewrite": False, "rewritten": False}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    matrix = {
        "summary": {"total_claims": 1, "passed_claims": 1, "binding_ratio": 1.0},
        "hard_blocking_issues": [],
        "claims": [
            {
                "claim_id": "page:page_1",
                "claim_type": "page_capability",
                "claim_text": "首页可被执行和回放",
                "page_id": "page_1",
                "page_title": "首页",
                "evidence": {
                    "screenshot_paths": ["screenshots/a_page_1_full.png"],
                    "api_contracts": [{"http_method": "GET", "path": "/api/home/list"}],
                    "code_hits": ["aligned_code/controller/home.py"],
                    "runtime_replay_matches": [{"flow": "主流程", "passed": True}],
                },
                "passed": True,
                "missing_evidence": [],
            }
        ],
    }

    context = {"project_name": "测试软件"}
    report = generator._save_examiner_material_sections(context, matrix, strict_timeline=False)

    assert report["passed"] is True
    assert report["strict_timeline"] is False
    assert report["sections_ready"]["timeline_review_ready"] is False
    assert any("缺少开发时间说明数据" in x for x in (report.get("deferred_issues") or []))


def test_document_screenshot_check_pass_with_examiner_material_report(tmp_path: Path):
    project_dir = tmp_path / "项目B"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir = tmp_path / "html2"
    html_dir.mkdir(parents=True, exist_ok=True)

    (html_dir / "page1.html").write_text("<html></html>", encoding="utf-8")
    (html_dir / "page2.html").write_text("<html></html>", encoding="utf-8")

    screenshots = project_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    (screenshots / "a.png").write_bytes(b"x")
    (screenshots / "b.png").write_bytes(b"x")

    docx_path = preferred_artifact_path(project_dir, project_name=project_dir.name, artifact_key="manual_docx")
    docx_path.write_bytes(b"x")

    (project_dir / "doc_code_consistency_report.json").write_text(
        json.dumps({"passed": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (project_dir / "examiner_material_report.json").write_text(
        json.dumps(
            {
                "passed": True,
                "blocking_issues": [],
                "sections_ready": {
                    "feature_evidence_ready": True,
                    "timeline_review_ready": True,
                    "novelty_review_ready": True,
                },
                "counts": {
                    "feature_evidence_row_count": 3,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    detail, blockers, passed = _document_screenshot_check(project_dir, html_dir)
    assert passed is True
    assert blockers == []
    assert detail["examiner_material_report_exists"] is True
    assert detail["examiner_material_passed"] is True
