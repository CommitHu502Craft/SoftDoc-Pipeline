import json
from pathlib import Path

from modules.claim_evidence_compiler import build_claim_evidence_matrix


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_claim_evidence_static_page_without_api_mapping_can_pass(tmp_path: Path):
    project_dir = tmp_path / "proj_static"
    screenshots_dir = project_dir / "screenshots"
    code_dir = project_dir / "aligned_code" / "Controllers"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)

    (screenshots_dir / "dashboard_full.png").write_bytes(b"x")
    (code_dir / "SystemMonitorController.php").write_text("<?php class SystemMonitorController {}", encoding="utf-8")

    _write_json(
        project_dir / "project_plan.json",
        {
            "pages": {
                "dashboard": {
                    "page_title": "系统运维监控中心",
                    "page_description": "用于监控平台运行状态",
                }
            },
            "menu_list": [{"page_id": "dashboard", "title": "系统运维监控中心"}],
        },
    )
    _write_json(
        project_dir / "project_executable_spec.json",
        {
            "page_api_mapping": [{"page_id": "dashboard", "api_ids": []}],
            "api_contracts": [],
        },
    )
    _write_json(
        project_dir / "project_charter.json",
        {
            "core_flows": [
                {"name": "主流程", "steps": ["进入监控首页", "查看运行数据"]},
            ]
        },
    )
    _write_json(
        project_dir / "runtime_verification_report.json",
        {
            "checks": {
                "business_path_replay": {
                    "items": [
                        {"flow": "主流程", "related_pages": ["dashboard"], "related_apis": [], "passed": True}
                    ]
                }
            }
        },
    )

    matrix = build_claim_evidence_matrix("proj_static", project_dir)
    page_claim = next(c for c in (matrix.get("claims") or []) if c.get("claim_id") == "page:dashboard")
    assert page_claim.get("passed") is True
    assert "api_contract" not in (page_claim.get("missing_evidence") or [])
    assert len((page_claim.get("evidence") or {}).get("code_hits") or []) > 0


def test_claim_evidence_structural_code_fallback_for_misaligned_api_keywords(tmp_path: Path):
    project_dir = tmp_path / "proj_fallback"
    screenshots_dir = project_dir / "screenshots"
    code_dir = project_dir / "aligned_code" / "Controllers"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)

    (screenshots_dir / "page_1_full.png").write_bytes(b"x")
    (code_dir / "ConsultationOrderController.php").write_text(
        "<?php class ConsultationOrderController { public function dispatchExpert(){} }",
        encoding="utf-8",
    )

    _write_json(
        project_dir / "project_plan.json",
        {
            "pages": {
                "page_1": {
                    "page_title": "专家资源调度指派",
                    "page_description": "工单指派和调度",
                }
            },
            "menu_list": [{"page_id": "page_1", "title": "专家资源调度指派"}],
        },
    )
    _write_json(
        project_dir / "project_executable_spec.json",
        {
            "page_api_mapping": [{"page_id": "page_1", "api_ids": ["api_dispatch_assign"]}],
            "api_contracts": [
                {
                    "id": "api_dispatch_assign",
                    "method_name": "assign_expert_task",
                    "http_method": "POST",
                    "path": "/api/dispatch/assign",
                    "description": "专家资源调度指派",
                }
            ],
        },
    )
    _write_json(
        project_dir / "project_charter.json",
        {
            "core_flows": [
                {"name": "主流程", "steps": ["调度员指派专家"]},
            ]
        },
    )
    _write_json(
        project_dir / "runtime_verification_report.json",
        {
            "checks": {
                "business_path_replay": {
                    "items": [
                        {
                            "flow": "主流程",
                            "related_pages": ["page_1"],
                            "related_apis": ["api_dispatch_assign"],
                            "passed": True,
                        }
                    ]
                }
            }
        },
    )
    _write_json(
        project_dir / "ui_blueprint.json",
        {
            "page_map": {
                "page_1": {
                    "functional_blocks": [
                        {
                            "block_id": "page_1_block_1",
                            "claim_id": "claim:page_1:dispatch_1",
                            "selector": "[data-claim-id='claim:page_1:dispatch_1']",
                            "claim_text": "指派区可执行",
                            "api_refs": ["api_dispatch_assign"],
                            "requires_api": True,
                            "required_widgets": ["widget_table_1"],
                            "code_keywords": ["dispatch", "assign"],
                        }
                    ]
                }
            }
        },
    )

    matrix = build_claim_evidence_matrix("proj_fallback", project_dir)
    page_claim = next(c for c in (matrix.get("claims") or []) if c.get("claim_id") == "page:page_1")
    assert page_claim.get("passed") is True
    assert len((page_claim.get("evidence") or {}).get("code_hits") or []) > 0
    assert str(page_claim.get("api_contract_id") or "") == "api_dispatch_assign"
    assert str((page_claim.get("evidence") or {}).get("api_contract_id") or "") == "api_dispatch_assign"
    assert str(page_claim.get("code_ref") or "").strip()

    block_claim = next(c for c in (matrix.get("claims") or []) if c.get("claim_type") == "functional_block")
    assert str(block_claim.get("block_id") or "") == "page_1_block_1"
    assert str(block_claim.get("selector") or "").strip()
    assert str(block_claim.get("api_contract_id") or "") == "api_dispatch_assign"
    assert str(block_claim.get("code_ref") or "").strip()
    assert float((matrix.get("summary") or {}).get("binding_ratio") or 0.0) >= 0.85
