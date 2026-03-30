import json
from pathlib import Path

import modules.runtime_skill_engine as runtime_skill_engine
from modules.runtime_skill_engine import (
    build_runtime_skill_plan,
    compile_runtime_skill_plan,
    load_runtime_skillpacks,
)


def test_runtime_skillpack_can_be_loaded():
    packs = load_runtime_skillpacks()
    assert len(packs) >= 1
    ids = {str(p.get("id") or "") for p in packs}
    assert "soft_copyright_master_v1" in ids


def test_runtime_skill_plan_matches_domain_keywords():
    plan = {
        "project_name": "工单管理系统",
        "pages": {
            "page_1": {"page_title": "工单处理", "page_description": "工单分配与审批流程"},
            "page_2": {"page_title": "处理统计", "page_description": "SLA 趋势统计"},
        },
    }
    runtime_plan = compile_runtime_skill_plan(
        project_name="工单管理系统",
        plan=plan,
        settings={},
    )
    domain = str((runtime_plan.get("domain_match") or {}).get("domain") or "")
    assert domain == "workflow"
    assert bool((runtime_plan.get("validation") or {}).get("passed"))


def test_runtime_skill_plan_page_count_rule_works():
    plan = {
        "project_name": "示例系统",
        "pages": {
            "page_1": {"page_title": "首页", "page_description": "概览"},
        },
    }
    runtime_plan = compile_runtime_skill_plan(
        project_name="示例系统",
        plan=plan,
        settings={},
    )
    warnings = [str(x) for x in ((runtime_plan.get("validation") or {}).get("warnings") or [])]
    assert any("页面数量不足" in x for x in warnings)


def test_runtime_skill_plan_applies_project_override(tmp_path: Path):
    project_dir = tmp_path / "override-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "runtime_skill_override.json").write_text(
        '{"constraints":{"page_catalog":{"page_count_min":7},"frontend":{"button_action_unique":true}}}',
        encoding="utf-8",
    )
    result = build_runtime_skill_plan(
        project_name="覆盖系统",
        plan={"project_name": "覆盖系统", "pages": {}},
        settings={},
        project_dir=project_dir,
    )
    payload = result.get("payload") or {}
    assert bool((payload.get("override_applied") or {}).get("applied"))
    constraints = payload.get("constraints") or {}
    assert int(((constraints.get("page_catalog") or {}).get("page_count_min") or 0)) == 7


def test_runtime_skill_plan_accepts_extended_page_narration_override(tmp_path: Path):
    project_dir = tmp_path / "override-page-narration"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "runtime_skill_override.json").write_text(
        '{"constraints":{"page_narration":{"forbid_phrase_after_first":"本页面","ban_date_mentions":true,"max_cross_page_similarity":0.97}}}',
        encoding="utf-8",
    )
    result = build_runtime_skill_plan(
        project_name="扩展文案规则系统",
        plan={"project_name": "扩展文案规则系统", "pages": {}},
        settings={},
        project_dir=project_dir,
    )
    payload = result.get("payload") or {}
    assert bool((payload.get("override_applied") or {}).get("blocked")) is False
    narration = ((payload.get("constraints") or {}).get("page_narration") or {})
    assert str(narration.get("forbid_phrase_after_first") or "") == "本页面"
    assert bool(narration.get("ban_date_mentions")) is True


def test_runtime_skill_plan_normalizes_external_script_policy():
    runtime_plan = compile_runtime_skill_plan(
        project_name="策略系统",
        plan={"project_name": "策略系统", "pages": {}},
        settings={},
    )
    frontend = ((runtime_plan.get("constraints") or {}).get("frontend") or {})
    policy = frontend.get("external_script_policy") or {}
    assert str(policy.get("mode") or "") == "allowlist_with_vendor_fallback"
    assert "cdn.jsdelivr.net" in (policy.get("allowed_domains") or [])
    assert str(((policy.get("vendor_fallback") or {}).get("echarts") or "")).endswith("echarts.min.js")


def test_runtime_skill_plan_blocks_invalid_override_schema(tmp_path: Path):
    project_dir = tmp_path / "override-blocked"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "runtime_skill_override.json").write_text(
        '{"constraints":{"frontend":{"button_action_unique":true}},"unknown_root":{"x":1}}',
        encoding="utf-8",
    )
    result = build_runtime_skill_plan(
        project_name="非法覆盖系统",
        plan={"project_name": "非法覆盖系统", "pages": {}},
        settings={},
        project_dir=project_dir,
    )
    payload = result.get("payload") or {}
    override_applied = payload.get("override_applied") or {}
    assert bool(override_applied.get("blocked")) is True
    assert bool(override_applied.get("applied")) is False
    issues = [str(x) for x in (override_applied.get("validation_issues") or [])]
    assert any("未允许根键" in x for x in issues)


def test_runtime_skillpack_loader_migrates_legacy_external_script_policy(tmp_path: Path, monkeypatch):
    runtime_dir = tmp_path / "runtime_skills"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    legacy_pack = {
        "id": "legacy_pack",
        "version": "0.9.0",
        "description": "legacy",
        "orchestration": {
            "trigger_order": ["intent", "visual", "functional", "evidence", "token"],
            "conflict_priority": ["evidence_auditability"],
            "degrade_path": ["base_skills"],
        },
        "constraints": {
            "naming": {},
            "page_catalog": {},
            "page_narration": {},
            "frontend": {
                "no_external_script": True,
            },
        },
    }
    (runtime_dir / "legacy.json").write_text(
        json.dumps(legacy_pack, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_skill_engine, "_runtime_skill_dir", lambda: runtime_dir)

    packs = load_runtime_skillpacks()
    target = next((x for x in packs if str(x.get("id") or "") == "legacy_pack"), {})
    assert target, "未加载 legacy_pack"
    frontend = ((target.get("constraints") or {}).get("frontend") or {})
    policy = frontend.get("external_script_policy") or {}
    assert str(policy.get("mode") or "") == "strict_no_external"
    assert str(((policy.get("vendor_fallback") or {}).get("echarts") or "")).endswith("echarts.min.js")
    assert bool((target.get("schema_migration") or {}).get("applied")) is True
