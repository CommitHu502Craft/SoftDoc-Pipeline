import json
from pathlib import Path

from core.llm_budget import llm_budget
from modules.ui_skill_orchestrator import build_ui_skill_artifacts


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_build_ui_skill_artifacts_generates_contracts(tmp_path: Path):
    project_name = "示例项目"
    project_dir = tmp_path / project_name
    plan = {
        "project_name": project_name,
        "menu_list": [
            {"page_id": "page_1", "title": "工单处理"},
            {"page_id": "page_2", "title": "统计分析"},
        ],
        "pages": {
            "page_1": {"page_title": "工单处理", "page_description": "工单分配与处理"},
            "page_2": {"page_title": "统计分析", "page_description": "趋势与报表"},
        },
        "executable_spec": {
            "page_api_mapping": [
                {"page_id": "page_1", "api_ids": ["api_ticket_assign"]},
                {"page_id": "page_2", "api_ids": []},
            ],
            "api_contracts": [
                {
                    "id": "api_ticket_assign",
                    "method_name": "assign_ticket",
                    "http_method": "POST",
                    "path": "/api/tickets/assign",
                    "description": "工单分配",
                }
            ],
        },
    }

    artifacts = build_ui_skill_artifacts(
        project_name=project_name,
        plan=plan,
        project_dir=project_dir,
        force=True,
        settings_override={
            "ui_skill_enabled": True,
            "ui_skill_mode": "narrative_tool_hybrid",
            "ui_token_policy": "balanced",
        },
    )

    assert artifacts["profile_path"].exists()
    assert artifacts["blueprint_path"].exists()
    assert artifacts["contract_path"].exists()
    assert artifacts["runtime_skill_path"].exists()
    assert artifacts["runtime_rule_graph_path"].exists()
    assert artifacts["report_path"].exists()

    profile = artifacts.get("profile") or {}
    orchestration = profile.get("orchestration_policy") or {}
    runtime_skillpack = profile.get("runtime_skillpack") or {}
    assert str(runtime_skillpack.get("id") or "").strip()
    assert orchestration.get("trigger_order") == ["intent", "visual", "functional", "evidence", "token"]
    assert orchestration.get("conflict_priority") == [
        "evidence_auditability",
        "functional_completeness",
        "visual_expression",
        "token_saving",
    ]

    blueprint = artifacts.get("blueprint") or {}
    summary = blueprint.get("summary") or {}
    assert int(summary.get("page_count") or 0) == 2
    assert int(summary.get("block_count") or 0) >= 6

    contract = artifacts.get("contract") or {}
    assert "page_1" in (contract.get("pages") or {})
    selectors = ((contract.get("pages") or {}).get("page_1") or {}).get("required_selectors") or []
    assert len(selectors) > 0
    runtime_skill_plan = artifacts.get("runtime_skill_plan") or {}
    assert bool((runtime_skill_plan.get("validation") or {}).get("passed"))


def test_ui_skill_token_policy_affects_block_density(tmp_path: Path):
    project_name = "策略项目"
    project_dir = tmp_path / project_name
    plan = {
        "project_name": project_name,
        "menu_list": [{"page_id": "page_1", "title": "工单处理"}],
        "pages": {
            "page_1": {"page_title": "工单处理", "page_description": "工单分配与处理"},
        },
        "executable_spec": {"page_api_mapping": [], "api_contracts": []},
    }

    low = build_ui_skill_artifacts(
        project_name=project_name,
        plan=plan,
        project_dir=project_dir,
        force=True,
        settings_override={
            "ui_skill_enabled": True,
            "ui_skill_mode": "narrative_tool_hybrid",
            "ui_token_policy": "economy",
        },
    )
    low_blocks = int(((low.get("blueprint") or {}).get("summary") or {}).get("block_count") or 0)

    high = build_ui_skill_artifacts(
        project_name=project_name,
        plan=plan,
        project_dir=project_dir,
        force=True,
        settings_override={
            "ui_skill_enabled": True,
            "ui_skill_mode": "narrative_tool_hybrid",
            "ui_token_policy": "quality_first",
        },
    )
    high_blocks = int(((high.get("blueprint") or {}).get("summary") or {}).get("block_count") or 0)

    assert low_blocks > 0
    assert high_blocks > 0
    assert high_blocks >= low_blocks


def test_ui_skill_artifact_build_records_prefix_cache_metrics(tmp_path: Path):
    project_name = "缓存统计项目"
    project_dir = tmp_path / project_name
    plan = {
        "project_name": project_name,
        "menu_list": [{"page_id": "page_1", "title": "工单处理"}],
        "pages": {
            "page_1": {"page_title": "工单处理", "page_description": "工单分配与处理"},
        },
        "executable_spec": {"page_api_mapping": [], "api_contracts": []},
    }

    run_id = "ui-skill-cache-run"
    llm_budget.reset_run(run_id)
    with llm_budget.run_scope(run_id), llm_budget.stage_scope("plan"):
        build_ui_skill_artifacts(
            project_name=project_name,
            plan=plan,
            project_dir=project_dir,
            force=True,
        )
        build_ui_skill_artifacts(
            project_name=project_name,
            plan=plan,
            project_dir=project_dir,
            force=False,
        )

    state = llm_budget.get_state(run_id)
    assert int(state.get("skill_prefix_cache_hits") or 0) >= 1
    assert int(state.get("skill_prefix_cache_misses") or 0) >= 1


def test_ui_skill_blueprint_non_homogeneous_for_three_archetypes(tmp_path: Path):
    fixtures = [
        ("工单流系统", "工单处理中心", "工单分配与流程处理"),
        ("知识检索系统", "知识检索页", "文档检索与索引命中分析"),
        ("运营监控系统", "运行监控页", "告警监控与容量趋势"),
    ]
    archetypes = []
    chart_sets = []

    for project_name, page_title, page_desc in fixtures:
        project_dir = tmp_path / project_name
        plan = {
            "project_name": project_name,
            "menu_list": [{"page_id": "page_1", "title": page_title}],
            "pages": {
                "page_1": {
                    "page_title": page_title,
                    "page_description": page_desc,
                }
            },
            "executable_spec": {"page_api_mapping": [], "api_contracts": []},
        }
        artifacts = build_ui_skill_artifacts(
            project_name=project_name,
            plan=plan,
            project_dir=project_dir,
            force=True,
            settings_override={
                "ui_skill_enabled": True,
                "ui_skill_mode": "narrative_tool_hybrid",
                "ui_token_policy": "balanced",
            },
        )
        page = ((artifacts.get("blueprint") or {}).get("pages") or [{}])[0]
        archetypes.append(str(page.get("archetype") or ""))
        chart_sets.append(tuple(page.get("required_chart_types") or []))

    # 3类样本应至少覆盖 2 种不同 archetype，避免同质化蓝图。
    assert len(set(archetypes)) >= 2
    assert len(set(chart_sets)) >= 2
