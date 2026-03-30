"""
申报前门禁（Submission Authorization Gate）。

设计原则：
1) 硬门禁优先：任一关键检查失败即阻断提交。
2) 自动修复闭环：提供可执行修复动作，并支持多轮“修复 -> 复检”。
3) 兼容旧接口：保留 score/risk_level/blocking_issues 等字段。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import BASE_DIR
from modules.claim_evidence_compiler import compile_claim_evidence_matrix
from modules.artifact_naming import (
    candidate_artifact_paths,
    first_existing_artifact_path,
    preferred_artifact_path,
)
from modules.executable_spec_builder import (
    build_executable_spec,
    save_executable_spec,
    validate_executable_spec,
)
from modules.fingerprint_auditor import FingerprintAuditor
from modules.project_charter import (
    default_project_charter_template,
    normalize_project_charter,
    resolve_software_identity,
    save_project_charter,
    validate_project_charter,
)
from modules.runtime_verifier import run_runtime_verification
from modules.runtime_skill_compiler import build_runtime_rule_graph
from modules.semantic_homogeneity_gate import (
    apply_semantic_homogeneity_gate,
    run_semantic_homogeneity_closed_loop,
)
from modules.skill_autorepair_runner import run_skill_autorepair
from modules.skill_compliance_validator import validate_runtime_skill_compliance
from modules.skill_policy_engine import build_skill_policy_decision


HARD_GATE_ORDER = [
    "charter",
    "naming_consistency",
    "ui_skill_consistency",
    "runtime_skill_compliance",
    "spec_consistency",
    "claim_evidence",
    "novelty",
    "document_screenshot",
    "timeline_consistency",
    "evidence_chain",
]

GATE_PROFILE_CHECKS = {
    # 最终提交门禁：全量硬门禁
    "submission": list(HARD_GATE_ORDER),
    # 文档阶段门禁：仅校验文档可生成所需前置条件，避免与 freeze 产物形成时序死锁
    "document_preflight": [
        "charter",
        "naming_consistency",
        "ui_skill_consistency",
        "runtime_skill_compliance",
        "spec_consistency",
        "claim_evidence",
        "novelty",
    ],
}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _score_item(weight: int, passed: bool) -> int:
    return int(weight if passed else 0)


def _charter_check(project_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    charter_path = project_dir / "project_charter.json"
    charter = normalize_project_charter(_load_json(charter_path), project_name=project_dir.name)
    errors = validate_project_charter(charter)
    passed = len(errors) == 0
    detail = {
        "path": str(charter_path),
        "passed": passed,
        "error_count": len(errors),
        "errors": errors,
        "summary": {
            "software_full_name": charter.get("software_full_name"),
            "software_short_name": charter.get("software_short_name"),
            "role_count": len(charter.get("user_roles") or []),
            "flow_count": len(charter.get("core_flows") or []),
            "nfr_count": len(charter.get("non_functional_constraints") or []),
            "acceptance_count": len(charter.get("acceptance_criteria") or []),
        },
    }
    blockers = [f"章程不完整: {err}" for err in errors]
    return detail, blockers, passed


def _naming_consistency_check(project_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    charter = normalize_project_charter(_load_json(project_dir / "project_charter.json"), project_name=project_dir.name)
    identity = resolve_software_identity(charter, fallback_project_name=project_dir.name)
    spec = _load_json(project_dir / "project_executable_spec.json")
    spec_identity = (spec.get("software_identity") or {}) if isinstance(spec, dict) else {}

    full_name = str(identity.get("software_full_name") or "").strip()
    short_name = str(identity.get("software_short_name") or "").strip()
    spec_full_name = str(spec_identity.get("software_full_name") or "").strip()
    spec_short_name = str(spec_identity.get("software_short_name") or "").strip()

    blockers: List[str] = []
    if not full_name:
        blockers.append("命名事实源缺少 software_full_name")
    if not short_name:
        blockers.append("命名事实源缺少 software_short_name")
    if spec and spec_full_name and spec_full_name != full_name:
        blockers.append("规格中的 software_full_name 与章程不一致")
    if spec and spec_short_name and spec_short_name != short_name:
        blockers.append("规格中的 software_short_name 与章程不一致")

    terms = identity.get("term_dictionary") or {}
    if not isinstance(terms, dict):
        blockers.append("章程术语字典 term_dictionary 结构非法")
    else:
        if str(terms.get("software_full_name") or "").strip() != full_name:
            blockers.append("term_dictionary.software_full_name 与章程不一致")
        if str(terms.get("software_short_name") or "").strip() != short_name:
            blockers.append("term_dictionary.software_short_name 与章程不一致")

    detail = {
        "passed": len(blockers) == 0,
        "software_full_name": full_name,
        "software_short_name": short_name,
        "spec_full_name": spec_full_name,
        "spec_short_name": spec_short_name,
        "term_count": len(terms) if isinstance(terms, dict) else 0,
    }
    return detail, blockers, detail["passed"]


def _ui_skill_consistency_check(project_name: str, project_dir: Path, plan: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], bool]:
    profile_path = project_dir / "ui_skill_profile.json"
    blueprint_path = project_dir / "ui_blueprint.json"
    contract_path = project_dir / "screenshot_contract.json"
    runtime_skill_path = project_dir / "runtime_skill_plan.json"
    report_path = project_dir / "ui_skill_plan_report.json"

    profile = _load_json(profile_path)
    blueprint = _load_json(blueprint_path)
    contract = _load_json(contract_path)
    runtime_skill = _load_json(runtime_skill_path)
    report = _load_json(report_path)

    blockers: List[str] = []
    if not profile:
        blockers.append("缺少 UI 技能画像（ui_skill_profile.json）")
    if not blueprint:
        blockers.append("缺少 UI 蓝图（ui_blueprint.json）")
    if not contract:
        blockers.append("缺少截图契约（screenshot_contract.json）")
    if not runtime_skill:
        blockers.append("缺少运行时技能计划（runtime_skill_plan.json）")

    page_count = int(((blueprint.get("summary") or {}).get("page_count") or 0))
    block_count = int(((blueprint.get("summary") or {}).get("block_count") or 0))
    menu_page_count = len(plan.get("menu_list") or []) if isinstance(plan, dict) else 0
    pages = blueprint.get("pages") or []
    if not isinstance(pages, list):
        pages = []

    if page_count <= 0 or block_count <= 0:
        blockers.append("UI 蓝图内容为空（page/block 数量为 0）")
    if menu_page_count > 0 and page_count < max(1, int(menu_page_count * 0.7)):
        blockers.append("UI 蓝图页面覆盖率不足（<70%）")
    if page_count > 0 and block_count < page_count * 3:
        blockers.append("UI 蓝图功能块密度不足（<3 blocks/page）")

    contract_pages = contract.get("pages") or {}
    if not isinstance(contract_pages, dict):
        contract_pages = {}
    if page_count > 0 and len(contract_pages) < page_count:
        blockers.append("截图契约页面覆盖不完整")

    report_passed = bool(report.get("passed")) if report else False
    if report and not report_passed:
        blockers.append("UI 技能规划报告未通过")

    runtime_validation = runtime_skill.get("validation") if isinstance(runtime_skill, dict) else {}
    runtime_passed = bool((runtime_validation or {}).get("passed")) if isinstance(runtime_validation, dict) else False
    if runtime_skill and not runtime_passed:
        blockers.append("运行时技能计划校验未通过")

    orchestration = profile.get("orchestration_policy") or {}
    trigger_order = orchestration.get("trigger_order") or []
    conflict_priority = orchestration.get("conflict_priority") or []
    expected_trigger_order = ["intent", "visual", "functional", "evidence", "token"]
    expected_conflict_priority = [
        "evidence_auditability",
        "functional_completeness",
        "visual_expression",
        "token_saving",
    ]
    if trigger_order and list(trigger_order) != expected_trigger_order:
        blockers.append("UI 技能触发顺序不符合约定（intent->visual->functional->evidence->token）")
    if conflict_priority and list(conflict_priority) != expected_conflict_priority:
        blockers.append("UI 技能冲突优先级不符合约定（evidence>functional>visual>token）")
    if not trigger_order:
        blockers.append("UI 技能画像缺少 orchestration_policy.trigger_order")
    if not conflict_priority:
        blockers.append("UI 技能画像缺少 orchestration_policy.conflict_priority")

    detail = {
        "passed": len(blockers) == 0,
        "profile_exists": profile_path.exists(),
        "blueprint_exists": blueprint_path.exists(),
        "contract_exists": contract_path.exists(),
        "report_exists": report_path.exists(),
        "runtime_skill_exists": runtime_skill_path.exists(),
        "runtime_skill_passed": runtime_passed,
        "report_passed": report_passed,
        "blueprint_page_count": page_count,
        "blueprint_block_count": block_count,
        "menu_page_count": menu_page_count,
        "contract_page_count": len(contract_pages),
        "trigger_order": trigger_order,
        "conflict_priority": conflict_priority,
    }
    return detail, blockers, detail["passed"]


def _runtime_skill_compliance_check(project_name: str, project_dir: Path, html_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    runtime_plan_path = project_dir / "runtime_skill_plan.json"
    runtime_rule_graph_path = project_dir / "runtime_rule_graph.json"
    blockers: List[str] = []
    html_dir = Path(html_dir)
    html_count = len(list(html_dir.glob("*.html"))) if html_dir.exists() else 0

    runtime_plan = _load_json(runtime_plan_path)
    if not runtime_plan:
        blockers.append("缺少运行时技能计划（runtime_skill_plan.json）")
        return {
            "passed": False,
            "runtime_skill_plan_exists": runtime_plan_path.exists(),
            "runtime_rule_graph_exists": runtime_rule_graph_path.exists(),
            "html_page_count": html_count,
            "compliance_report_exists": False,
        }, blockers, False
    if html_count <= 0:
        blockers.append("缺少 HTML 页面，无法执行运行时技能合规校验")
    override_applied = runtime_plan.get("override_applied") if isinstance(runtime_plan, dict) else {}
    override_blocked = bool((override_applied or {}).get("blocked"))
    override_issues = [str(x) for x in ((override_applied or {}).get("validation_issues") or []) if str(x).strip()]
    if override_blocked:
        blockers.append("运行时覆盖配置非法，已阻断应用（runtime_skill_override.json）")
        if override_issues:
            blockers.append(f"覆盖配置错误: {';'.join(override_issues[:3])}")

    if not runtime_rule_graph_path.exists():
        try:
            build_runtime_rule_graph(project_dir=project_dir, runtime_skill_plan=runtime_plan)
        except Exception as e:
            blockers.append(f"运行时规则图编译失败: {e}")

    try:
        passed, report_path, report = validate_runtime_skill_compliance(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            write_report=True,
        )
    except Exception as e:
        blockers.append(f"运行时技能合规校验失败: {e}")
        return {
            "passed": False,
            "runtime_skill_plan_exists": runtime_plan_path.exists(),
            "runtime_rule_graph_exists": runtime_rule_graph_path.exists(),
            "compliance_report_exists": False,
            "error": str(e),
        }, blockers, False

    policy_path, policy_report = build_skill_policy_decision(
        project_name=project_name,
        project_dir=project_dir,
        compliance_report=report,
    )
    policy_summary = policy_report.get("summary") if isinstance(policy_report, dict) else {}
    if not isinstance(policy_summary, dict):
        policy_summary = {}

    summary = report.get("summary") or {}
    ratio = float(summary.get("rule_pass_ratio") or 0.0)
    critical_failed = [str(x).strip() for x in (summary.get("critical_failed_rules") or []) if str(x).strip()]
    evidence_preview = [
        x
        for x in (report.get("evidence_preview") or [])
        if isinstance(x, dict)
    ][:20]
    if ratio < 0.85:
        blockers.append("运行时技能规则通过率不足（<85%）")
    if critical_failed:
        blockers.append(f"运行时技能关键规则失败: {','.join(critical_failed[:6])}")

    detail = {
        "passed": bool(passed) and ratio >= 0.85 and len(critical_failed) == 0 and (not override_blocked),
        "runtime_skill_plan_exists": runtime_plan_path.exists(),
        "runtime_rule_graph_exists": runtime_rule_graph_path.exists(),
        "html_page_count": html_count,
        "override_blocked": override_blocked,
        "override_issues": override_issues,
        "compliance_report_exists": bool(report_path and Path(report_path).exists()),
        "compliance_report_path": str(report_path),
        "policy_decision_report_path": str(policy_path),
        "policy_version": str(policy_report.get("policy_version") or ""),
        "policy_auto_fix_actions": list((policy_summary.get("auto_fix_actions") or [])),
        "policy_action_resolution": list((policy_summary.get("action_resolution") or [])),
        "summary": summary,
        "critical_failed_rules": critical_failed,
        "evidence_preview": evidence_preview,
    }
    return detail, blockers, detail["passed"]


def _spec_consistency_check(project_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    plan_path = project_dir / "project_plan.json"
    spec_path = project_dir / "project_executable_spec.json"
    charter_path = project_dir / "project_charter.json"

    plan = _load_json(plan_path)
    spec = _load_json(spec_path)
    charter = _load_json(charter_path)

    blockers: List[str] = []
    if not spec:
        blockers.append("缺少可执行规格（project_executable_spec.json）")
        return {
            "path": str(spec_path),
            "passed": False,
            "reason": "missing_spec",
        }, blockers, False

    page_ids = [
        str(item.get("page_id") or "").strip()
        for item in (plan.get("menu_list") or [])
        if str(item.get("page_id") or "").strip()
    ]
    mapping = spec.get("page_api_mapping") or []
    mapped_pages = [str(item.get("page_id") or "").strip() for item in mapping if str(item.get("page_id") or "").strip()]
    mapped_page_ratio = _safe_ratio(len(set(mapped_pages) & set(page_ids)), len(set(page_ids))) if page_ids else 0.0

    api_contracts = spec.get("api_contracts") or []
    contract_ids = {str(c.get("id") or "").strip() for c in api_contracts if str(c.get("id") or "").strip()}
    orphan_api_ref_count = 0
    for item in mapping:
        for api_id in (item.get("api_ids") or []):
            if str(api_id).strip() and str(api_id).strip() not in contract_ids:
                orphan_api_ref_count += 1

    state_machine_count = len(spec.get("state_machines") or [])
    permission_count = len(spec.get("permission_matrix") or [])
    entity_count = len(spec.get("entities") or [])

    charter_digest_expected = ""
    if charter:
        try:
            charter_digest_expected = hashlib.sha256(
                json.dumps(normalize_project_charter(charter, project_name=project_dir.name), ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
        except Exception:
            charter_digest_expected = ""
    charter_digest_actual = str(spec.get("charter_digest") or "")
    digest_match = bool(charter_digest_expected and charter_digest_actual and charter_digest_expected == charter_digest_actual)
    spec_fresh = True
    if plan_path.exists() and spec_path.exists():
        try:
            spec_fresh = spec_path.stat().st_mtime >= plan_path.stat().st_mtime
        except Exception:
            spec_fresh = True

    passed = all(
        [
            entity_count > 0,
            len(api_contracts) > 0,
            permission_count > 0,
            state_machine_count > 0,
            mapped_page_ratio >= 0.6 if page_ids else True,
            orphan_api_ref_count == 0,
            digest_match or not charter_digest_expected,
            spec_fresh,
        ]
    )

    if entity_count <= 0:
        blockers.append("规格缺少实体模型")
    if len(api_contracts) <= 0:
        blockers.append("规格缺少 API 合约")
    if permission_count <= 0:
        blockers.append("规格缺少权限矩阵")
    if state_machine_count <= 0:
        blockers.append("规格缺少状态机")
    if page_ids and mapped_page_ratio < 0.6:
        blockers.append("规格页面-接口映射覆盖率不足（<60%）")
    if orphan_api_ref_count > 0:
        blockers.append("规格存在无效 API 映射引用")
    if charter_digest_expected and not digest_match:
        blockers.append("规格与章程摘要不一致，请重新生成 spec")
    if not spec_fresh:
        blockers.append("规格落后于最新规划，请重建 project_executable_spec.json")

    detail = {
        "path": str(spec_path),
        "passed": passed,
        "entity_count": entity_count,
        "api_contract_count": len(api_contracts),
        "permission_count": permission_count,
        "state_machine_count": state_machine_count,
        "page_count": len(page_ids),
        "mapped_page_ratio": round(mapped_page_ratio, 3),
        "orphan_api_ref_count": orphan_api_ref_count,
        "charter_digest_match": digest_match or not charter_digest_expected,
        "spec_fresh": spec_fresh,
    }
    return detail, blockers, passed


def _claim_evidence_check(
    project_name: str,
    project_dir: Path,
    html_dir: Path,
) -> Tuple[Dict[str, Any], List[str], bool]:
    blockers: List[str] = []
    try:
        passed, matrix_path, matrix = compile_claim_evidence_matrix(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
        )
    except Exception as e:
        blockers.append(f"声称-证据矩阵编译失败: {e}")
        return {"passed": False, "error": str(e)}, blockers, False

    summary = matrix.get("summary") or {}
    hard_blocking = matrix.get("hard_blocking_issues") or []
    if hard_blocking:
        blockers.extend([f"声称-证据绑定失败: {x}" for x in hard_blocking])

    passed_claims = int(summary.get("passed_claims") or 0)
    total_claims = int(summary.get("total_claims") or 0)
    binding_ratio = float(summary.get("binding_ratio") or 0.0)
    if total_claims > 0 and binding_ratio < 0.85:
        blockers.append("声称-证据绑定率不足（<85%）")

    detail = {
        "passed": bool(passed),
        "path": str(matrix_path),
        "summary": summary,
        "total_claims": total_claims,
        "passed_claims": passed_claims,
        "binding_ratio": round(binding_ratio, 4),
        "hard_blocking_issues": hard_blocking,
    }
    return detail, blockers, bool(passed)


def _novelty_check(project_name: str, project_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    blockers: List[str] = []
    semantic_report = apply_semantic_homogeneity_gate(
        project_name=project_name,
        project_dir=project_dir,
        output_root=project_dir.parent,
        threshold=0.82,
        auto_rewrite=False,
    )
    top_similarity = float(semantic_report.get("top_similarity") or 0.0)
    should_rewrite = bool(semantic_report.get("should_rewrite"))
    if should_rewrite:
        blockers.append(f"语义同质化偏高(top_similarity={top_similarity:.3f})")

    auditor = FingerprintAuditor()
    novelty_report = auditor.evaluate_project_novelty(
        project_name=project_name,
        project_dir=str(project_dir),
        persist_report=True,
        update_history=False,
    )
    recommendation = str(novelty_report.get("recommendation") or "safe")
    max_similarity = float(novelty_report.get("max_similarity") or 0.0)
    if recommendation == "blocked":
        blockers.append(f"指纹相似度过高(max_similarity={max_similarity:.3f})")

    passed = (not should_rewrite) and recommendation != "blocked"
    detail = {
        "passed": passed,
        "semantic_report_path": semantic_report.get("report_path"),
        "semantic_top_similarity": round(top_similarity, 4),
        "semantic_should_rewrite": should_rewrite,
        "novelty_report": novelty_report,
    }
    return detail, blockers, passed


def _document_screenshot_check(project_dir: Path, html_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    project_name = project_dir.name
    docx_candidates = candidate_artifact_paths(project_dir, project_name=project_name, artifact_key="manual_docx")
    doc_pdf_candidates = candidate_artifact_paths(project_dir, project_name=project_name, artifact_key="manual_pdf")
    docx_path = first_existing_artifact_path(project_dir, project_name=project_name, artifact_key="manual_docx")
    doc_pdf_path = first_existing_artifact_path(project_dir, project_name=project_name, artifact_key="manual_pdf")
    screenshots_dir = project_dir / "screenshots"

    screenshot_count = len(list(screenshots_dir.glob("*.png"))) if screenshots_dir.exists() else 0
    html_count = len(list(html_dir.glob("*.html"))) if html_dir.exists() else 0
    coverage_ratio = _safe_ratio(screenshot_count, html_count) if html_count > 0 else 0.0
    capture_report_path = project_dir / "screenshot_capture_report.json"
    capture_report = _load_json(capture_report_path)
    capture_summary = capture_report.get("summary") if isinstance(capture_report, dict) else {}
    if not isinstance(capture_summary, dict):
        capture_summary = {}
    selector_total = int(capture_summary.get("selector_total") or 0)
    selector_hits = int(capture_summary.get("selector_hits") or 0)
    selector_hit_ratio = float(capture_summary.get("selector_hit_ratio") or 0.0) if selector_total > 0 else 0.0

    has_doc = bool(docx_path or doc_pdf_path)
    blockers: List[str] = []
    if not has_doc:
        blockers.append("缺少说明书（docx/pdf）")
    if screenshot_count <= 0:
        blockers.append("缺少运行截图证据")
    if selector_total > 0:
        if selector_hit_ratio < 0.85:
            blockers.append("截图契约覆盖率不足（<85%）")
    elif html_count > 0 and coverage_ratio < 0.85:
        blockers.append("截图覆盖率不足（<85%）")

    consistency_path = project_dir / "doc_code_consistency_report.json"
    consistency = _load_json(consistency_path)
    consistency_passed = bool(consistency.get("passed")) if consistency else False
    if consistency and not consistency_passed:
        blockers.append("代码-文档一致性报告未通过")

    examiner_report_path = project_dir / "examiner_material_report.json"
    examiner_report = _load_json(examiner_report_path)
    examiner_report_exists = bool(examiner_report_path.exists())
    examiner_passed = bool(examiner_report.get("passed")) if examiner_report else False
    examiner_sections = examiner_report.get("sections_ready") or {}
    examiner_counts = examiner_report.get("counts") or {}
    feature_row_count = int(examiner_counts.get("feature_evidence_row_count") or 0)

    if not examiner_report_exists:
        blockers.append("缺少审查版材料报告（examiner_material_report.json）")
    else:
        if not examiner_passed:
            issues = [str(x).strip() for x in (examiner_report.get("blocking_issues") or []) if str(x).strip()]
            if issues:
                blockers.extend([f"审查版材料未通过: {x}" for x in issues[:6]])
            else:
                blockers.append("审查版材料未通过")
        if feature_row_count <= 0:
            blockers.append("功能对应表为空（A03 未生成）")
        if examiner_sections and not bool(examiner_sections.get("timeline_review_ready")):
            blockers.append("开发时间说明未就绪（A04 未通过）")
        if examiner_sections and not bool(examiner_sections.get("novelty_review_ready")):
            blockers.append("版本与新增点说明未就绪（A05 未通过）")

    detail = {
        "passed": len(blockers) == 0,
        "docx_exists": bool(docx_path),
        "doc_pdf_exists": bool(doc_pdf_path),
        "docx_candidates": [str(p) for p in docx_candidates],
        "doc_pdf_candidates": [str(p) for p in doc_pdf_candidates],
        "screenshot_count": screenshot_count,
        "html_page_count": html_count,
        "screenshot_coverage_ratio": round(coverage_ratio, 3),
        "screenshot_capture_report_exists": capture_report_path.exists(),
        "selector_total": selector_total,
        "selector_hits": selector_hits,
        "selector_hit_ratio": round(selector_hit_ratio, 3) if selector_total > 0 else 0.0,
        "consistency_report_exists": consistency_path.exists(),
        "consistency_passed": consistency_passed if consistency else False,
        "examiner_material_report_exists": examiner_report_exists,
        "examiner_material_passed": examiner_passed if examiner_report else False,
        "examiner_sections_ready": examiner_sections if examiner_sections else {},
        "feature_evidence_row_count": feature_row_count,
    }
    return detail, blockers, detail["passed"]


def _timeline_consistency_check(project_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    report_path = project_dir / "freeze_package" / "timeline_consistency_report.json"
    report = _load_json(report_path)
    blockers: List[str] = []
    if not report:
        blockers.append("缺少时间线一致性报告（freeze_package/timeline_consistency_report.json）")
        return {"passed": False, "path": str(report_path), "reason": "missing_report"}, blockers, False

    passed = bool(report.get("passed"))
    issues = report.get("issues") or []
    warnings = report.get("warnings") or []
    if not passed:
        blockers.extend([f"时间线冲突: {x}" for x in issues] or ["时间线一致性校验未通过"])
    if warnings:
        blockers.extend([f"时间线补证提示: {x}" for x in warnings])

    detail = {
        "passed": passed,
        "path": str(report_path),
        "issues": issues,
        "warnings": warnings,
        "requires_supporting_note": bool(report.get("requires_supporting_note")),
    }
    return detail, blockers, passed and not warnings


def _evidence_chain_check(project_dir: Path) -> Tuple[Dict[str, Any], List[str], bool]:
    runtime_report_path = project_dir / "runtime_verification_report.json"
    runtime_report = _load_json(runtime_report_path)
    runtime_passed = bool(runtime_report.get("overall_passed"))

    freeze_dir = project_dir / "freeze_package"
    freeze_manifest = freeze_dir / "manifest.json"
    freeze_hashes = freeze_dir / "artifact_hashes.json"
    freeze_repro = freeze_dir / "reproducibility_report.json"
    freeze_zip = first_existing_artifact_path(
        project_dir,
        project_name=project_dir.name,
        artifact_key="freeze_zip",
    )
    timeline_report = freeze_dir / "timeline_consistency_report.json"
    claim_matrix = project_dir / "claim_evidence_matrix.json"
    runtime_skill_plan = project_dir / "runtime_skill_plan.json"
    runtime_rule_graph = project_dir / "runtime_rule_graph.json"
    skill_compliance_report = project_dir / "skill_compliance_report.json"
    skill_autorepair_report = project_dir / "skill_autorepair_report.json"
    skill_policy_report = project_dir / "skill_policy_decision_report.json"
    ui_profile = project_dir / "ui_skill_profile.json"
    ui_blueprint = project_dir / "ui_blueprint.json"
    screenshot_contract = project_dir / "screenshot_contract.json"
    screenshot_report = project_dir / "screenshot_capture_report.json"

    blockers: List[str] = []
    if not runtime_report_path.exists():
        blockers.append("缺少运行验证报告")
    elif not runtime_passed:
        blockers.append("运行验证未通过")
    if not claim_matrix.exists():
        blockers.append("缺少声称-证据矩阵")
    if not runtime_skill_plan.exists():
        blockers.append("缺少运行时技能计划")
    if not runtime_rule_graph.exists():
        blockers.append("缺少运行时规则图")
    if not skill_compliance_report.exists():
        blockers.append("缺少运行时技能合规报告")
    if not skill_policy_report.exists():
        blockers.append("缺少运行时技能策略裁决报告")
    if not ui_profile.exists():
        blockers.append("缺少 UI 技能画像")
    if not ui_blueprint.exists():
        blockers.append("缺少 UI 蓝图")
    if not screenshot_contract.exists():
        blockers.append("缺少截图契约")
    if not screenshot_report.exists():
        blockers.append("缺少截图执行报告")
    if not freeze_manifest.exists():
        blockers.append("缺少冻结包 manifest")
    if not freeze_hashes.exists():
        blockers.append("缺少冻结包哈希清单")
    if not freeze_repro.exists():
        blockers.append("缺少冻结包复验报告")
    if not freeze_zip:
        blockers.append("缺少冻结包 zip")
    if not timeline_report.exists():
        blockers.append("缺少冻结包时间线一致性报告")

    passed = len(blockers) == 0
    detail = {
        "passed": passed,
        "runtime_report_exists": runtime_report_path.exists(),
        "runtime_report_passed": runtime_passed,
        "claim_matrix_exists": claim_matrix.exists(),
        "runtime_skill_plan_exists": runtime_skill_plan.exists(),
        "runtime_rule_graph_exists": runtime_rule_graph.exists(),
        "skill_compliance_report_exists": skill_compliance_report.exists(),
        "skill_autorepair_report_exists": skill_autorepair_report.exists(),
        "skill_policy_report_exists": skill_policy_report.exists(),
        "ui_skill_profile_exists": ui_profile.exists(),
        "ui_blueprint_exists": ui_blueprint.exists(),
        "screenshot_contract_exists": screenshot_contract.exists(),
        "screenshot_report_exists": screenshot_report.exists(),
        "freeze_manifest_exists": freeze_manifest.exists(),
        "freeze_hashes_exists": freeze_hashes.exists(),
        "freeze_repro_exists": freeze_repro.exists(),
        "freeze_zip_exists": bool(freeze_zip),
        "timeline_report_exists": timeline_report.exists(),
    }
    return detail, blockers, passed


def _plan_auto_fix_actions(report: Dict[str, Any]) -> List[str]:
    failed_checks = set(report.get("failed_checks") or [])
    actions: List[str] = []
    if {"charter", "naming_consistency"} & failed_checks:
        actions.extend(["repair_charter_identity", "rebuild_spec"])
    if "ui_skill_consistency" in failed_checks:
        actions.extend(["rebuild_ui_skills", "rebuild_screenshot_report", "regen_html", "recapture_screenshots"])
    if "runtime_skill_compliance" in failed_checks:
        actions.extend(["repair_runtime_skill_compliance", "rebuild_screenshot_report"])
    if "spec_consistency" in failed_checks:
        actions.append("rebuild_spec")
    if "novelty" in failed_checks:
        actions.extend(["novelty_rewrite_loop", "regenerate_code"])
    if {"document_screenshot", "claim_evidence"} & failed_checks:
        actions.extend(["regen_html", "recapture_screenshots", "regenerate_document"])
    if "evidence_chain" in failed_checks:
        actions.extend(["rebuild_screenshot_report", "recapture_screenshots", "runtime_verify", "freeze_package"])
    if {"timeline_consistency", "evidence_chain", "claim_evidence"} & failed_checks:
        actions.extend(["runtime_verify", "freeze_package"])
    ordered: List[str] = []
    seen: set[str] = set()
    for action in actions:
        if action not in seen:
            seen.add(action)
            ordered.append(action)
    return ordered


def _fix_repair_charter_identity(project_name: str, project_dir: Path) -> Dict[str, Any]:
    charter = normalize_project_charter(_load_json(project_dir / "project_charter.json"), project_name=project_name)
    errors = validate_project_charter(charter)
    if errors:
        template = default_project_charter_template(project_name)
        charter = normalize_project_charter({**template, **charter}, project_name=project_name)
    save_project_charter(project_dir, charter)
    return {
        "ok": len(validate_project_charter(charter)) == 0,
        "charter_path": str(project_dir / "project_charter.json"),
    }


def _fix_rebuild_spec(project_name: str, project_dir: Path) -> Dict[str, Any]:
    plan_path = project_dir / "project_plan.json"
    if not plan_path.exists():
        return {"ok": False, "error": "缺少 project_plan.json"}
    plan = _load_json(plan_path)
    charter = normalize_project_charter(_load_json(project_dir / "project_charter.json"), project_name=project_name)
    spec = build_executable_spec(plan, charter)
    errors = validate_executable_spec(spec)
    if errors:
        return {"ok": False, "error": "；".join(errors)}
    spec_path = save_executable_spec(project_dir, spec)
    apply_semantic_homogeneity_gate(
        project_name=project_name,
        project_dir=project_dir,
        output_root=project_dir.parent,
        threshold=0.82,
        auto_rewrite=True,
    )
    return {"ok": True, "spec_path": str(spec_path)}


def _fix_rebuild_ui_skills(project_name: str, project_dir: Path) -> Dict[str, Any]:
    from modules.ui_skill_orchestrator import build_ui_skill_artifacts

    plan_path = project_dir / "project_plan.json"
    if not plan_path.exists():
        return {"ok": False, "error": "缺少 project_plan.json"}
    plan = _load_json(plan_path)
    artifacts = build_ui_skill_artifacts(
        project_name=project_name,
        plan=plan,
        project_dir=project_dir,
        force=True,
    )
    return {
        "ok": bool((artifacts.get("report") or {}).get("passed")),
        "profile_path": str(artifacts.get("profile_path")),
        "blueprint_path": str(artifacts.get("blueprint_path")),
        "contract_path": str(artifacts.get("contract_path")),
        "runtime_rule_graph_path": str(artifacts.get("runtime_rule_graph_path") or ""),
        "report_path": str(artifacts.get("report_path")),
    }


def _fix_repair_runtime_skill_compliance(project_name: str, project_dir: Path, html_dir: Path) -> Dict[str, Any]:
    result = run_skill_autorepair(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        max_rounds=2,
    )
    return {
        "ok": bool(result.get("fixed")),
        "report_path": str(result.get("report_path") or ""),
        "final_summary": result.get("final_summary") or {},
        "round_count": len(result.get("rounds") or []),
    }


def _fix_regen_html(project_name: str, project_dir: Path) -> Dict[str, Any]:
    from modules import generate_html_pages
    from modules.ui_skill_orchestrator import build_ui_skill_artifacts

    plan_path = project_dir / "project_plan.json"
    if not plan_path.exists():
        return {"ok": False, "error": "缺少 project_plan.json"}
    plan = _load_json(plan_path)
    try:
        build_ui_skill_artifacts(
            project_name=project_name,
            plan=plan,
            project_dir=project_dir,
            force=True,
        )
    except Exception:
        pass
    html_dir = generate_html_pages(plan_path)
    return {"ok": True, "html_dir": str(html_dir)}


def _fix_recapture_screenshots(project_name: str, project_dir: Path, html_dir: Path) -> Dict[str, Any]:
    from modules import capture_screenshots_sync

    html_dir = Path(html_dir)
    if not html_dir.exists():
        return {"ok": False, "error": f"HTML目录不存在: {html_dir}"}
    screenshot_dir = project_dir / "screenshots"
    contract_path = project_dir / "screenshot_contract.json"
    capture_screenshots_sync(html_dir, screenshot_dir, contract_path=contract_path)
    return {"ok": True, "screenshot_dir": str(screenshot_dir)}


def _fix_rebuild_screenshot_report(project_name: str, project_dir: Path) -> Dict[str, Any]:
    """
    在不依赖 Playwright 的前提下，根据现有截图与合同重建 screenshot_capture_report.json。
    用于历史项目迁移或截图阶段异常中断后的自愈。
    """
    screenshot_dir = project_dir / "screenshots"
    contract_path = project_dir / "screenshot_contract.json"
    report_path = project_dir / "screenshot_capture_report.json"

    contract = _load_json(contract_path)
    contract_pages = contract.get("pages") or {}
    if not isinstance(contract_pages, dict):
        contract_pages = {}

    pages_payload: Dict[str, Any] = {}
    if screenshot_dir.exists():
        all_png = list(screenshot_dir.glob("*.png"))
    else:
        all_png = []

    page_ids = set(contract_pages.keys())
    if not page_ids:
        # 无合同时，尽力从截图文件名推断 page_id（hash_page_xxx_*.png）。
        for path in all_png:
            parts = path.stem.split("_")
            if len(parts) >= 3 and parts[1].startswith("page"):
                page_ids.add(parts[1])

    for page_id in sorted(page_ids):
        contract_page = contract_pages.get(page_id) or {}
        selectors = contract_page.get("required_selectors") or []
        if not isinstance(selectors, list):
            selectors = []

        full = ""
        full_candidates = sorted(screenshot_dir.glob(f"*_{page_id}_full.png")) if screenshot_dir.exists() else []
        if full_candidates:
            full = full_candidates[0].name

        components = []
        component_candidates = sorted(screenshot_dir.glob(f"*_{page_id}_widget_*.png")) if screenshot_dir.exists() else []
        for cp in component_candidates:
            comp_id = cp.stem.split(f"{page_id}_")[-1]
            components.append({"component_id": comp_id, "file": cp.name})

        claim_candidates = sorted(screenshot_dir.glob(f"*_{page_id}_claim_*.png")) if screenshot_dir.exists() else []
        claim_files = [c.name for c in claim_candidates]
        claims = []
        selector_hits = 0
        for idx, spec in enumerate(selectors, start=1):
            if isinstance(spec, dict):
                claim_id = str(spec.get("claim_id") or f"claim_{idx}").strip()
                selector = str(spec.get("selector") or "").strip()
                block_id = str(spec.get("block_id") or "").strip()
            else:
                claim_id = f"claim_{idx}"
                selector = str(spec or "").strip()
                block_id = ""

            token = re.sub(r"[^a-zA-Z0-9_\-]", "_", claim_id)
            matched = next((x for x in claim_files if token in x), "")
            captured = bool(matched)
            if captured:
                selector_hits += 1
            claims.append(
                {
                    "claim_id": claim_id,
                    "block_id": block_id,
                    "selector": selector,
                    "captured": captured,
                    "file": matched,
                }
            )

        selector_total = len(selectors)
        pages_payload[page_id] = {
            "full_screenshot": full,
            "components": components,
            "claims": claims,
            "selector_hits": int(selector_hits),
            "selector_total": int(selector_total),
            "selector_hit_ratio": round(float(selector_hits) / float(selector_total), 3) if selector_total > 0 else 1.0,
        }

    selector_total_all = sum(int((v or {}).get("selector_total") or 0) for v in pages_payload.values())
    selector_hits_all = sum(int((v or {}).get("selector_hits") or 0) for v in pages_payload.values())
    payload = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "contract_path": str(contract_path),
        "pages": pages_payload,
        "summary": {
            "page_count": len(pages_payload),
            "selector_total": selector_total_all,
            "selector_hits": selector_hits_all,
            "selector_hit_ratio": round(float(selector_hits_all) / float(selector_total_all), 3) if selector_total_all > 0 else 1.0,
            "legacy_rebuilt": True,
        },
    }
    _save_json(report_path, payload)
    return {
        "ok": True,
        "report_path": str(report_path),
        "page_count": len(pages_payload),
        "selector_total": selector_total_all,
    }


def _fix_regenerate_code(project_name: str, project_dir: Path) -> Dict[str, Any]:
    from modules.code_generator import generate_code_from_plan

    plan_path = project_dir / "project_plan.json"
    if not plan_path.exists():
        return {"ok": False, "error": "缺少 project_plan.json"}
    code_dir = project_dir / "aligned_code"
    files = generate_code_from_plan(str(plan_path), str(code_dir))
    return {"ok": bool(files), "file_count": len(files or []), "code_dir": str(code_dir)}


def _fix_runtime_verify(project_name: str, project_dir: Path, html_dir: Path) -> Dict[str, Any]:
    ok, report_path, report = run_runtime_verification(project_name, project_dir, html_dir)
    return {
        "ok": bool(ok),
        "report_path": str(report_path),
        "summary": report.get("summary") or {},
    }


def _fix_regenerate_document(project_name: str, project_dir: Path) -> Dict[str, Any]:
    from modules.document_generator import generate_document
    from modules.word_to_pdf import convert_word_to_pdf

    plan_path = project_dir / "project_plan.json"
    screenshot_dir = project_dir / "screenshots"
    template_path = BASE_DIR / "templates" / "manual_template.docx"
    output_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="manual_docx")
    output_pdf_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="manual_pdf")
    if not template_path.exists():
        return {"ok": False, "error": f"模板不存在: {template_path}"}
    if not plan_path.exists():
        return {"ok": False, "error": "缺少 project_plan.json"}
    ok = generate_document(str(plan_path), str(screenshot_dir), str(template_path), str(output_path))
    pdf_ok = False
    if ok:
        try:
            pdf_ok = bool(convert_word_to_pdf(output_path, output_pdf_path))
        except Exception:
            pdf_ok = False
    return {
        "ok": bool(ok and pdf_ok),
        "docx_path": str(output_path),
        "pdf_path": str(output_pdf_path),
        "word_ok": bool(ok),
        "pdf_ok": bool(pdf_ok),
    }


def _fix_freeze_package(project_name: str, project_dir: Path, html_dir: Path) -> Dict[str, Any]:
    from modules.freeze_package import build_freeze_package

    result = build_freeze_package(project_name, project_dir, html_dir)
    return {"ok": bool(result), "result": result}


def _fix_novelty_rewrite_loop(project_name: str, project_dir: Path, html_dir: Path) -> Dict[str, Any]:
    def _post_rewrite_callback(**kwargs):
        code_result = _fix_regenerate_code(project_name, project_dir)
        verify_result = _fix_runtime_verify(project_name, project_dir, html_dir)
        doc_result = _fix_regenerate_document(project_name, project_dir)
        return {
            "code": code_result,
            "verify": verify_result,
            "document": doc_result,
        }

    loop_report = run_semantic_homogeneity_closed_loop(
        project_name=project_name,
        project_dir=project_dir,
        output_root=project_dir.parent,
        threshold=0.82,
        max_rounds=2,
        post_rewrite_callback=_post_rewrite_callback,
    )
    return {"ok": bool(loop_report.get("passed")), "loop_report": loop_report}


def _execute_auto_fix_action(action: str, project_name: str, project_dir: Path, html_dir: Path) -> Dict[str, Any]:
    try:
        if action == "repair_charter_identity":
            payload = _fix_repair_charter_identity(project_name, project_dir)
        elif action == "rebuild_ui_skills":
            payload = _fix_rebuild_ui_skills(project_name, project_dir)
        elif action == "repair_runtime_skill_compliance":
            payload = _fix_repair_runtime_skill_compliance(project_name, project_dir, html_dir)
        elif action == "rebuild_screenshot_report":
            payload = _fix_rebuild_screenshot_report(project_name, project_dir)
        elif action == "rebuild_spec":
            payload = _fix_rebuild_spec(project_name, project_dir)
        elif action == "regen_html":
            payload = _fix_regen_html(project_name, project_dir)
        elif action == "recapture_screenshots":
            payload = _fix_recapture_screenshots(project_name, project_dir, html_dir)
        elif action == "regenerate_code":
            payload = _fix_regenerate_code(project_name, project_dir)
        elif action == "runtime_verify":
            payload = _fix_runtime_verify(project_name, project_dir, html_dir)
        elif action == "regenerate_document":
            payload = _fix_regenerate_document(project_name, project_dir)
        elif action == "freeze_package":
            payload = _fix_freeze_package(project_name, project_dir, html_dir)
        elif action == "novelty_rewrite_loop":
            payload = _fix_novelty_rewrite_loop(project_name, project_dir, html_dir)
        else:
            payload = {"ok": False, "error": f"未知修复动作: {action}"}
        payload["action"] = action
        return payload
    except Exception as e:
        return {"ok": False, "action": action, "error": str(e)}


def evaluate_submission_risk(
    project_name: str,
    project_dir: Path,
    html_dir: Path,
    block_threshold: int = 75,
    gate_profile: str = "submission",
) -> Dict[str, Any]:
    """
    执行门禁评估并返回报告。
    兼容旧字段：score / risk_level / should_block_submission / blocking_issues。
    """
    project_dir = Path(project_dir)
    html_dir = Path(html_dir)

    charter_detail, charter_blockers, charter_passed = _charter_check(project_dir)
    naming_detail, naming_blockers, naming_passed = _naming_consistency_check(project_dir)
    plan_data = _load_json(project_dir / "project_plan.json")
    ui_skill_detail, ui_skill_blockers, ui_skill_passed = _ui_skill_consistency_check(project_name, project_dir, plan_data)
    runtime_compliance_detail, runtime_compliance_blockers, runtime_compliance_passed = _runtime_skill_compliance_check(
        project_name,
        project_dir,
        html_dir,
    )
    spec_detail, spec_blockers, spec_passed = _spec_consistency_check(project_dir)
    claim_detail, claim_blockers, claim_passed = _claim_evidence_check(project_name, project_dir, html_dir)
    novelty_detail, novelty_blockers, novelty_passed = _novelty_check(project_name, project_dir)
    doc_detail, doc_blockers, doc_passed = _document_screenshot_check(project_dir, html_dir)
    timeline_detail, timeline_blockers, timeline_passed = _timeline_consistency_check(project_dir)
    evidence_detail, evidence_blockers, evidence_passed = _evidence_chain_check(project_dir)

    check_results = {
        "charter": charter_passed,
        "naming_consistency": naming_passed,
        "ui_skill_consistency": ui_skill_passed,
        "runtime_skill_compliance": runtime_compliance_passed,
        "spec_consistency": spec_passed,
        "claim_evidence": claim_passed,
        "novelty": novelty_passed,
        "document_screenshot": doc_passed,
        "timeline_consistency": timeline_passed,
        "evidence_chain": evidence_passed,
    }
    active_order = GATE_PROFILE_CHECKS.get(str(gate_profile or "submission"), HARD_GATE_ORDER)
    failed_checks = [k for k in active_order if not check_results.get(k)]
    hard_gate_passed = len(failed_checks) == 0

    weights = {
        "charter": 14,
        "naming_consistency": 8,
        "ui_skill_consistency": 10,
        "runtime_skill_compliance": 10,
        "spec_consistency": 16,
        "claim_evidence": 16,
        "novelty": 12,
        "document_screenshot": 10,
        "timeline_consistency": 10,
        "evidence_chain": 4,
    }
    score = sum(_score_item(weights[k], bool(check_results.get(k))) for k in active_order if k in weights)

    blocker_map = {
        "charter": charter_blockers,
        "naming_consistency": naming_blockers,
        "ui_skill_consistency": ui_skill_blockers,
        "runtime_skill_compliance": runtime_compliance_blockers,
        "spec_consistency": spec_blockers,
        "claim_evidence": claim_blockers,
        "novelty": novelty_blockers,
        "document_screenshot": doc_blockers,
        "timeline_consistency": timeline_blockers,
        "evidence_chain": evidence_blockers,
    }
    blocking_issues: List[str] = []
    for check_name in active_order:
        blocking_issues.extend(blocker_map.get(check_name) or [])

    should_block = (not hard_gate_passed) or bool(blocking_issues) or score < int(block_threshold)
    if score >= 90 and not should_block:
        risk_level = "low"
    elif score >= 75 and not should_block:
        risk_level = "medium"
    else:
        risk_level = "high"

    recommendations: List[str] = []
    if charter_blockers or naming_blockers:
        recommendations.append("先修复章程命名事实源，再重建 spec。")
    if ui_skill_blockers:
        recommendations.append("重建 UI 技能蓝图与截图契约，并重跑 html/screenshot。")
    if runtime_compliance_blockers:
        policy_actions = runtime_compliance_detail.get("policy_auto_fix_actions") if isinstance(runtime_compliance_detail, dict) else []
        action_text = f"（建议动作: {','.join(policy_actions)}）" if policy_actions else ""
        recommendations.append(f"执行运行时技能合规自动修复，仅重写失败页面或失败文件{action_text}。")
    if spec_blockers:
        recommendations.append("重新生成并确认可执行规格，确保页面-接口映射完整。")
    if claim_blockers or doc_blockers:
        recommendations.append("补截图并重生成说明书，确保声称均有代码/API/回放证据。")
    if novelty_blockers:
        recommendations.append("执行同质化改写闭环（spec重写 -> code/doc/verify重跑）。")
    if timeline_blockers:
        recommendations.append("修复时间线冲突并补充说明附件。")
    if evidence_blockers:
        recommendations.append("补跑 verify/freeze，确保运行证据与哈希链完整。")

    auto_fix_actions = _plan_auto_fix_actions({"failed_checks": failed_checks})
    report = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "gate_mode": "hard_gate_v2",
        "gate_profile": str(gate_profile or "submission"),
        "score": int(score),
        "block_threshold": int(block_threshold),
        "risk_level": risk_level,
        "should_block_submission": bool(should_block),
        "hard_gate": {
            "passed": hard_gate_passed,
            "check_order": active_order,
            "failed_checks": failed_checks,
        },
        "failed_checks": failed_checks,
        "blocking_issues": blocking_issues,
        "recommendations": recommendations,
        "auto_fix_actions": auto_fix_actions,
        "checks": {
            "charter": charter_detail,
            "naming_consistency": naming_detail,
            "ui_skill_consistency": ui_skill_detail,
            "runtime_skill_compliance": runtime_compliance_detail,
            "spec_consistency": spec_detail,
            "claim_evidence": claim_detail,
            "novelty": novelty_detail,
            "document_screenshot": doc_detail,
            "timeline_consistency": timeline_detail,
            "evidence_chain": evidence_detail,
        },
    }
    return report


def run_submission_auto_fix(
    project_name: str,
    project_dir: Path,
    html_dir: Path,
    block_threshold: int = 75,
    max_rounds: int = 2,
    gate_profile: str = "submission",
) -> Dict[str, Any]:
    """
    执行自动修复闭环，并返回修复轨迹及最终报告。
    """
    project_dir = Path(project_dir)
    html_dir = Path(html_dir)
    max_rounds = max(1, int(max_rounds))
    rounds: List[Dict[str, Any]] = []
    current_report = evaluate_submission_risk(
        project_name,
        project_dir,
        html_dir,
        block_threshold=block_threshold,
        gate_profile=gate_profile,
    )

    for round_idx in range(1, max_rounds + 1):
        if not current_report.get("should_block_submission"):
            break
        planned_actions = current_report.get("auto_fix_actions") or []
        if not planned_actions:
            break

        action_results = []
        for action in planned_actions:
            result = _execute_auto_fix_action(action, project_name, project_dir, html_dir)
            action_results.append(result)

        current_report = evaluate_submission_risk(
            project_name,
            project_dir,
            html_dir,
            block_threshold=block_threshold,
            gate_profile=gate_profile,
        )
        rounds.append(
            {
                "round": round_idx,
                "planned_actions": planned_actions,
                "action_results": action_results,
                "post_report_passed": not bool(current_report.get("should_block_submission")),
                "post_failed_checks": current_report.get("failed_checks") or [],
            }
        )
        if not current_report.get("should_block_submission"):
            break

    return {
        "attempted": bool(rounds),
        "max_rounds": max_rounds,
        "rounds": rounds,
        "fixed": not bool(current_report.get("should_block_submission")),
        "final_report": current_report,
    }


def run_submission_risk_precheck(
    project_name: str,
    project_dir: Path,
    html_dir: Path,
    block_threshold: int = 75,
    enable_auto_fix: bool = False,
    max_fix_rounds: int = 2,
    gate_profile: str = "submission",
) -> Tuple[bool, Path, Dict[str, Any]]:
    """
    运行门禁并落盘。
    返回: (是否通过, 报告路径, 报告对象)。
    """
    report = evaluate_submission_risk(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        block_threshold=block_threshold,
        gate_profile=gate_profile,
    )
    auto_fix = {
        "attempted": False,
        "fixed": False,
        "rounds": [],
        "max_rounds": int(max_fix_rounds),
    }
    if enable_auto_fix and report.get("should_block_submission"):
        auto_fix_result = run_submission_auto_fix(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            block_threshold=block_threshold,
            max_rounds=max_fix_rounds,
            gate_profile=gate_profile,
        )
        report = auto_fix_result.get("final_report") or report
        auto_fix = {
            "attempted": bool(auto_fix_result.get("attempted")),
            "fixed": bool(auto_fix_result.get("fixed")),
            "rounds": auto_fix_result.get("rounds") or [],
            "max_rounds": int(auto_fix_result.get("max_rounds") or max_fix_rounds),
        }

    report["auto_fix"] = auto_fix
    output_path = Path(project_dir) / "submission_risk_report.json"
    _save_json(output_path, report)
    passed = (not bool(report.get("should_block_submission"))) and bool((report.get("hard_gate") or {}).get("passed"))
    return passed, output_path, report
