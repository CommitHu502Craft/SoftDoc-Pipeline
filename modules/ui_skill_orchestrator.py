"""
UI skill orchestrator.

This module creates deterministic "skill planning" artifacts that can be
consumed by HTML generation, screenshot capture and evidence gates.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import BASE_DIR
from core.llm_budget import llm_budget
from modules.runtime_skill_compiler import build_runtime_rule_graph
from modules.runtime_skill_engine import build_runtime_skill_plan


DEFAULT_UI_SKILL_SETTINGS: Dict[str, Any] = {
    "ui_skill_enabled": True,
    "ui_skill_mode": "narrative_tool_hybrid",
    "ui_token_policy": "balanced",
    "ui_skill_force_blueprint": True,
}


DEFAULT_SKILL_REGISTRY: List[Dict[str, str]] = [
    {
        "name": "frontend-design",
        "role": "visual_identity",
        "source": "skills/frontend-design/SKILL.md",
    },
    {
        "name": "ui-ux-pro-max",
        "role": "ux_quality_and_chart_diversity",
        "source": "skills/ui-ux-pro-max/SKILL.md",
    },
    {
        "name": "web-artifacts-builder",
        "role": "artifact_layout_and_stack_guidance",
        "source": "skills/web-artifacts-builder/SKILL.md",
    },
]


ARCHETYPE_KEYWORDS: Dict[str, List[str]] = {
    "workflow": ["工单", "审批", "派单", "流程", "任务", "待办", "节点"],
    "operations": ["监控", "告警", "巡检", "运行", "容量", "性能", "异常"],
    "knowledge": ["知识", "检索", "文档", "资料", "索引", "查询", "语料"],
    "relationship": ["客户", "线索", "联系人", "伙伴", "跟进", "关系", "crm"],
    "reporting": ["统计", "报表", "分析", "比对", "趋势", "版本", "洞察"],
}


ARCHETYPE_BLOCKS: Dict[str, List[Tuple[str, str]]] = {
    "workflow": [
        ("filter_bar", "工单筛选与检索"),
        ("action_form", "新建/分配操作区"),
        ("data_table", "待处理工单列表"),
        ("detail_panel", "工单详情与流转"),
        ("chart_card", "SLA与处理效率趋势"),
    ],
    "operations": [
        ("kpi_strip", "运行指标总览"),
        ("filter_bar", "告警筛选与定位"),
        ("chart_card", "实时趋势与异常分布"),
        ("data_table", "告警明细与处理状态"),
        ("detail_panel", "告警详情与处置记录"),
    ],
    "knowledge": [
        ("search_form", "检索输入与高级筛选"),
        ("data_table", "检索结果列表"),
        ("detail_panel", "文档详情与版本信息"),
        ("chart_card", "命中率与标签分布"),
        ("action_form", "收藏/标注/导出操作"),
    ],
    "relationship": [
        ("filter_bar", "客户线索筛选"),
        ("data_table", "客户主档与跟进记录"),
        ("detail_panel", "联系人详情与关系网络"),
        ("chart_card", "转化漏斗与阶段趋势"),
        ("action_form", "新增跟进与分配动作"),
    ],
    "reporting": [
        ("filter_bar", "报表口径与周期筛选"),
        ("kpi_strip", "核心指标总览"),
        ("chart_card", "趋势/对比/结构分析"),
        ("data_table", "报表版本与明细记录"),
        ("action_form", "生成/导出/归档操作"),
    ],
    "generic": [
        ("filter_bar", "条件筛选与检索"),
        ("kpi_strip", "指标概览"),
        ("chart_card", "趋势与结构分析"),
        ("data_table", "业务数据明细"),
        ("detail_panel", "对象详情与操作记录"),
    ],
}


ARCHETYPE_CHART_TYPES: Dict[str, List[str]] = {
    "workflow": ["line", "bar", "funnel", "heatmap", "gauge"],
    "operations": ["line", "heatmap", "scatter", "bar", "gauge"],
    "knowledge": ["bar", "treemap", "line", "scatter", "pie"],
    "relationship": ["funnel", "bar", "line", "sankey", "pie"],
    "reporting": ["bar", "line", "pie", "scatter", "heatmap"],
    "generic": ["bar", "line", "pie", "scatter", "heatmap"],
}

SKILL_TRIGGER_ORDER = ["intent", "visual", "functional", "evidence", "token"]
SKILL_CONFLICT_PRIORITY = [
    "evidence_auditability",
    "functional_completeness",
    "visual_expression",
    "token_saving",
]
SKILL_DEGRADE_PATH = ["advanced_skills", "base_skills", "rules_template"]


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _slug(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def _stable_seed(*parts: Any) -> int:
    raw = "|".join([str(p or "") for p in parts])
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _discover_skill_registry() -> List[Dict[str, str]]:
    """
    Discover local skills dynamically to avoid hard-coded one-shot behavior.
    """
    skills_dir = BASE_DIR / "skills"
    if not skills_dir.exists():
        return list(DEFAULT_SKILL_REGISTRY)

    discovered: List[Dict[str, str]] = []
    for skill_md in skills_dir.glob("*/SKILL.md"):
        skill_name = skill_md.parent.name
        description = ""
        try:
            text = skill_md.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^\s*description:\s*(.+)$", text, flags=re.MULTILINE)
            if m:
                description = str(m.group(1)).strip().strip("'").strip('"')
        except Exception:
            description = ""
        discovered.append(
            {
                "name": skill_name,
                "role": "local_skill",
                "source": str(skill_md.relative_to(BASE_DIR)).replace("\\", "/"),
                "description": description[:200],
            }
        )

    if not discovered:
        return list(DEFAULT_SKILL_REGISTRY)

    # Keep deterministic ordering.
    discovered.sort(key=lambda x: str(x.get("name") or ""))
    return discovered


def _pick_chart_types(archetype: str, count: int, seed: int) -> List[str]:
    pool = ARCHETYPE_CHART_TYPES.get(archetype, ARCHETYPE_CHART_TYPES["generic"])
    if not pool:
        return []
    result: List[str] = []
    idx = seed % len(pool)
    for _ in range(max(1, int(count))):
        result.append(pool[idx % len(pool)])
        idx += 1
    deduped: List[str] = []
    for item in result:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _detect_archetype(project_name: str, page_title: str, page_desc: str) -> str:
    hay = f"{project_name} {page_title} {page_desc}".lower()
    best = ("generic", 0)
    for key, words in ARCHETYPE_KEYWORDS.items():
        score = sum(1 for w in words if w and w.lower() in hay)
        if score > best[1]:
            best = (key, score)
    return best[0]


def _collect_page_api_refs(spec: Dict[str, Any], page_id: str) -> List[str]:
    mapping = spec.get("page_api_mapping") or []
    refs: List[str] = []
    for item in mapping:
        if str(item.get("page_id") or "").strip() != str(page_id).strip():
            continue
        for api_id in item.get("api_ids") or []:
            aid = str(api_id or "").strip()
            if aid and aid not in refs:
                refs.append(aid)
    return refs


def load_ui_skill_settings() -> Dict[str, Any]:
    settings_path = BASE_DIR / "config" / "general_settings.json"
    payload = _load_json(settings_path)

    settings = dict(DEFAULT_UI_SKILL_SETTINGS)
    nested = payload.get("ui_skill") if isinstance(payload.get("ui_skill"), dict) else {}
    if isinstance(nested, dict):
        settings.update(nested)

    # Backward/flat compatibility
    for key in ("ui_skill_enabled", "ui_skill_mode", "ui_token_policy", "ui_skill_force_blueprint"):
        if key in payload:
            settings[key] = payload.get(key)

    settings["ui_skill_enabled"] = bool(settings.get("ui_skill_enabled", True))
    settings["ui_skill_mode"] = str(settings.get("ui_skill_mode") or "narrative_tool_hybrid").strip() or "narrative_tool_hybrid"
    settings["ui_token_policy"] = str(settings.get("ui_token_policy") or "balanced").strip() or "balanced"
    settings["ui_skill_force_blueprint"] = bool(settings.get("ui_skill_force_blueprint", True))
    return settings


def _build_profile(
    project_name: str,
    plan: Dict[str, Any],
    settings: Dict[str, Any],
    runtime_skill_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    genome = plan.get("genome") or {}
    business_context = genome.get("business_context") or []
    context_tokens = [str(x).strip() for x in business_context if str(x).strip()]
    ui_framework = str(genome.get("ui_framework") or "Bootstrap")
    visual_style = str(genome.get("visual_style") or "Enterprise")
    token_policy = str(settings.get("ui_token_policy") or "balanced")
    dev_skills = _discover_skill_registry()
    runtime_skill_plan = runtime_skill_plan if isinstance(runtime_skill_plan, dict) else {}
    runtime_orchestration = runtime_skill_plan.get("orchestration") or {}
    runtime_skillpack = runtime_skill_plan.get("skillpack") or {}

    mode = str(settings.get("ui_skill_mode") or "narrative_tool_hybrid").strip() or "narrative_tool_hybrid"

    # Deterministic style branch per project (anti-template).
    seed = _stable_seed(project_name, ui_framework, visual_style, token_policy, mode)
    style_buckets = [
        "operations-atlas",
        "industrial-lab-console",
        "narrative-flow-canvas",
        "ai-ide-workbench",
    ]
    style_direction = style_buckets[seed % len(style_buckets)]
    if mode == "narrative_tool_hybrid":
        style_direction = "ai-ide-workbench"
    elif mode == "narrative_first":
        style_direction = "narrative-flow-canvas"
    elif mode == "tool_first":
        style_direction = "operations-atlas"

    layout_archetype_hint = {
        "ai-ide-workbench": "command_workbench",
        "narrative-flow-canvas": "narrative_tool_surface",
        "operations-atlas": "atlas_split_view",
        "industrial-lab-console": "lab_control_shell",
    }.get(style_direction, "command_workbench")

    profile = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "token_policy": token_policy,
        "enabled": bool(settings.get("ui_skill_enabled")),
        "runtime_skills": list(runtime_orchestration.get("stages") or []),
        "runtime_skillpack": runtime_skillpack,
        "dev_skill_registry": dev_skills,
        "design_decision": {
            "style_direction": style_direction,
            "layout_archetype_hint": layout_archetype_hint,
            "ui_framework": ui_framework,
            "visual_style": visual_style,
            "font_policy": "avoid_generic_inter_arial",
            "layout_policy": "block_first_with_claim_anchors",
            "chart_policy": "at_least_two_distinct_types_per_page",
            "anti_template_policy": {
                "ban_classic_admin_dashboard_shell": True,
                "ban_generic_copy": ["Dashboard / Overview", "Admin", "系统菜单"],
                "require_non_table_interactive_sections": 2,
            },
        },
        "token_strategy": {
            "cache_stable_prefix": True,
            "block_level_regen": True,
            "retry_scope": "block_only",
            "policy": token_policy,
            "insertable_stages": ["plan", "spec", "html", "screenshot", "document", "freeze"],
        },
        "orchestration_policy": {
            "trigger_order": list(SKILL_TRIGGER_ORDER),
            "conflict_priority": list(SKILL_CONFLICT_PRIORITY),
            "degrade_path": list(SKILL_DEGRADE_PATH),
        },
        "business_context": context_tokens[:12],
    }
    return profile


def _apply_runtime_skill_constraints(
    blueprint: Dict[str, Any],
    runtime_skill_plan: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply runtime skill constraints into ui_blueprint to make downstream modules
    consume a single source of truth.
    """
    if not isinstance(blueprint, dict):
        return {}
    payload = dict(blueprint)
    plan_payload = runtime_skill_plan if isinstance(runtime_skill_plan, dict) else {}
    constraints = plan_payload.get("constraints") or {}
    if not isinstance(constraints, dict):
        constraints = {}

    page_catalog = constraints.get("page_catalog") or {}
    page_name_len_max = int(page_catalog.get("page_name_len_max") or 0)
    if page_name_len_max > 0:
        for page in payload.get("pages") or []:
            if not isinstance(page, dict):
                continue
            title = str(page.get("page_title") or "").strip()
            page["name_len_ok"] = (len(title) <= page_name_len_max) if title else True

    preferred_chart_types = constraints.get("preferred_chart_types") or []
    if isinstance(preferred_chart_types, list) and preferred_chart_types:
        for page in payload.get("pages") or []:
            if not isinstance(page, dict):
                continue
            page_chart_types = [str(x).strip() for x in (page.get("required_chart_types") or []) if str(x).strip()]
            merged = []
            for item in page_chart_types + [str(x).strip() for x in preferred_chart_types if str(x).strip()]:
                if item and item not in merged:
                    merged.append(item)
            page["required_chart_types"] = merged[:6]

    payload["runtime_constraints"] = constraints
    payload["runtime_skillpack"] = {
        "id": str((plan_payload.get("skillpack") or {}).get("id") or ""),
        "version": str((plan_payload.get("skillpack") or {}).get("version") or ""),
        "domain": str((plan_payload.get("domain_match") or {}).get("domain") or "generic"),
        "constraints_checksum": str(plan_payload.get("constraints_checksum") or ""),
    }
    return payload


def _build_page_blocks(
    project_name: str,
    page_id: str,
    page_title: str,
    page_desc: str,
    archetype: str,
    api_refs: List[str],
    token_policy: str = "balanced",
) -> Dict[str, Any]:
    templates = list(ARCHETYPE_BLOCKS.get(archetype, ARCHETYPE_BLOCKS["generic"]))
    policy = str(token_policy or "balanced").strip().lower()
    if policy == "economy":
        templates = templates[:4]
    elif policy == "quality_first":
        extra = [("chart_card", "多维对比分析"), ("detail_panel", "对象状态回放")]
        templates.extend(extra)
    seed = _stable_seed(project_name, page_id, page_title, archetype)
    chart_target = 1 if policy == "economy" else (3 if policy == "quality_first" else 2)
    chart_types = _pick_chart_types(archetype=archetype, count=chart_target, seed=seed)

    chart_idx = 1
    table_idx = 1
    blocks: List[Dict[str, Any]] = []
    for idx, (block_type, block_title) in enumerate(templates, start=1):
        block_id = f"{page_id}_block_{idx}"
        claim_id = f"claim:{page_id}:{_slug(block_type, fallback='block')}_{idx}"
        required_widgets: List[str] = []
        if block_type == "chart_card":
            required_widgets = [f"widget_chart_{chart_idx}", f"widget_chart_{chart_idx + 1}"]
            chart_idx += 2
        elif block_type in {"data_table", "action_form"}:
            required_widgets = [f"widget_table_{table_idx}"]
            table_idx += 1

        block_api_refs = api_refs if block_type in {"action_form", "data_table", "detail_panel"} else []
        requires_api = bool(block_api_refs)
        selector = f"[data-claim-id='{claim_id}']"

        blocks.append(
            {
                "block_id": block_id,
                "block_type": block_type,
                "title": block_title,
                "claim_id": claim_id,
                "claim_text": f"{page_title} - {block_title} 功能可执行并可被证据链验证",
                "selector": selector,
                "required_widgets": required_widgets,
                "api_refs": block_api_refs,
                "requires_api": requires_api,
                "code_keywords": [
                    page_title,
                    page_desc,
                    block_title,
                    block_type,
                    *block_api_refs,
                ],
                "interaction_steps": [
                    "输入筛选条件",
                    "触发查询或提交动作",
                    "查看结果与详情联动",
                ],
            }
        )

    return {
        "page_id": page_id,
        "page_title": page_title,
        "archetype": archetype,
        "required_chart_types": chart_types,
        "functional_blocks": blocks,
        "min_non_chart_blocks": 2,
        "min_total_blocks": max(4, len(blocks)),
    }


def _build_blueprint(project_name: str, plan: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    pages = plan.get("pages") or {}
    menu_list = plan.get("menu_list") or []
    menu_title_map = {
        str(item.get("page_id") or "").strip(): str(item.get("title") or "").strip()
        for item in menu_list
        if str(item.get("page_id") or "").strip()
    }
    spec = plan.get("executable_spec") or _load_json((BASE_DIR / "output" / project_name / "project_executable_spec.json"))

    token_policy = str(settings.get("ui_token_policy") or "balanced")
    page_items: List[Dict[str, Any]] = []
    for page_id, page_data in pages.items():
        pid = str(page_id or "").strip()
        if not pid:
            continue
        title = str((page_data or {}).get("page_title") or menu_title_map.get(pid, pid)).strip() or pid
        desc = str((page_data or {}).get("page_description") or "").strip()
        archetype = _detect_archetype(project_name, title, desc)
        api_refs = _collect_page_api_refs(spec, pid)
        page_items.append(
            _build_page_blocks(
                project_name=project_name,
                page_id=pid,
                page_title=title,
                page_desc=desc,
                archetype=archetype,
                api_refs=api_refs,
                token_policy=token_policy,
            )
        )

    page_map = {item["page_id"]: item for item in page_items}
    block_count = sum(len(item.get("functional_blocks") or []) for item in page_items)
    blueprint = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": str(settings.get("ui_skill_mode") or "narrative_tool_hybrid"),
        "token_policy": token_policy,
        "pages": page_items,
        "page_map": page_map,
        "summary": {
            "page_count": len(page_items),
            "block_count": block_count,
            "avg_blocks_per_page": round(block_count / max(1, len(page_items)), 2),
            "min_blocks_required": 4,
        },
    }
    return blueprint


def _build_screenshot_contract(project_name: str, blueprint: Dict[str, Any]) -> Dict[str, Any]:
    pages = blueprint.get("pages") or []
    contract_pages: Dict[str, Any] = {}
    token_policy = str(blueprint.get("token_policy") or "balanced")
    for page in pages:
        page_id = str(page.get("page_id") or "").strip()
        if not page_id:
            continue
        blocks = page.get("functional_blocks") or []
        selectors = []
        component_ids: List[str] = []
        for block in blocks:
            selector = str(block.get("selector") or "").strip()
            claim_id = str(block.get("claim_id") or "").strip()
            block_id = str(block.get("block_id") or "").strip()
            if selector:
                selectors.append(
                    {
                        "selector": selector,
                        "claim_id": claim_id,
                        "block_id": block_id,
                    }
                )
            for wid in block.get("required_widgets") or []:
                text = str(wid or "").strip()
                if text and text not in component_ids:
                    component_ids.append(text)

        contract_pages[page_id] = {
            "page_id": page_id,
            "required_full_page": True,
            "required_selectors": selectors,
            "required_component_ids": component_ids,
            "min_selector_hits": (
                max(1, int(math.ceil(len(selectors) * 0.5)))
                if selectors and token_policy == "economy"
                else max(1, int(math.ceil(len(selectors) * 0.6))) if selectors else 0
            ),
            "recommended_viewport": {"width": 1920, "height": 1080},
        }

    return {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pages": contract_pages,
        "summary": {
            "page_count": len(contract_pages),
            "selector_count": sum(len((v.get("required_selectors") or [])) for v in contract_pages.values()),
        },
    }


def build_ui_skill_artifacts(
    project_name: str,
    plan: Dict[str, Any],
    project_dir: Path,
    force: bool = False,
    settings_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build and persist UI skill artifacts.

    Returns a dictionary containing paths and loaded payloads.
    """
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    settings = load_ui_skill_settings()
    if isinstance(settings_override, dict):
        settings = {**settings, **settings_override}

    profile_path = project_dir / "ui_skill_profile.json"
    blueprint_path = project_dir / "ui_blueprint.json"
    contract_path = project_dir / "screenshot_contract.json"
    runtime_skill_path = project_dir / "runtime_skill_plan.json"
    runtime_rule_graph_path = project_dir / "runtime_rule_graph.json"
    report_path = project_dir / "ui_skill_plan_report.json"
    prefix_cache_key = f"ui_skill:{project_name}"

    if (
        (not force)
        and profile_path.exists()
        and blueprint_path.exists()
        and contract_path.exists()
        and runtime_skill_path.exists()
        and runtime_rule_graph_path.exists()
    ):
        profile = _load_json(profile_path)
        blueprint = _load_json(blueprint_path)
        contract = _load_json(contract_path)
        runtime_skill_plan = _load_json(runtime_skill_path)
        runtime_rule_graph = _load_json(runtime_rule_graph_path)
        llm_budget.record_skill_prefix_cache_hit(prefix_key=prefix_cache_key, hit=True)
    else:
        llm_budget.record_skill_prefix_cache_hit(prefix_key=prefix_cache_key, hit=False)
        runtime_skill_result = build_runtime_skill_plan(
            project_name=project_name,
            plan=plan or {},
            settings=settings,
            project_dir=project_dir,
        )
        runtime_skill_plan = runtime_skill_result.get("payload") or {}
        _, runtime_rule_graph = build_runtime_rule_graph(
            project_dir=project_dir,
            runtime_skill_plan=runtime_skill_plan,
        )
        profile = _build_profile(
            project_name=project_name,
            plan=plan or {},
            settings=settings,
            runtime_skill_plan=runtime_skill_plan,
        )
        profile["runtime_skillpack"] = runtime_skill_plan.get("skillpack") or {}
        profile["runtime_domain"] = str((runtime_skill_plan.get("domain_match") or {}).get("domain") or "generic")
        profile["runtime_stages"] = list((runtime_skill_plan.get("orchestration") or {}).get("stages") or [])
        profile["runtime_constraints_checksum"] = str(runtime_skill_plan.get("constraints_checksum") or "")
        profile["runtime_validation"] = runtime_skill_plan.get("validation") or {}
        profile["runtime_override_applied"] = runtime_skill_plan.get("override_applied") or {}

        blueprint = _build_blueprint(project_name=project_name, plan=plan or {}, settings=settings)
        blueprint = _apply_runtime_skill_constraints(blueprint, runtime_skill_plan=runtime_skill_plan)
        contract = _build_screenshot_contract(project_name=project_name, blueprint=blueprint)
        _save_json(profile_path, profile)
        _save_json(blueprint_path, blueprint)
        _save_json(contract_path, contract)
        _save_json(runtime_skill_path, runtime_skill_plan)
        _save_json(runtime_rule_graph_path, runtime_rule_graph)

    summary = blueprint.get("summary") or {}
    page_count = int(summary.get("page_count") or 0)
    block_count = int(summary.get("block_count") or 0)
    runtime_skill_passed = bool((runtime_skill_plan.get("validation") or {}).get("passed")) if isinstance(runtime_skill_plan, dict) else False
    runtime_rule_count = int((((runtime_rule_graph.get("graph") or {}).get("summary") or {}).get("rule_count") or 0)) if isinstance(runtime_rule_graph, dict) else 0
    passed = (
        bool(settings.get("ui_skill_enabled", True))
        and page_count > 0
        and block_count >= page_count * 3
        and runtime_skill_passed
        and runtime_rule_count > 0
    )
    report = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "issues": [] if passed else ["UI 技能蓝图覆盖不足或 runtime skill plan 未通过"],
        "orchestration": {
            "trigger_order": list(SKILL_TRIGGER_ORDER),
            "conflict_priority": list(SKILL_CONFLICT_PRIORITY),
            "degrade_path": list(SKILL_DEGRADE_PATH),
        },
        "summary": {
            "page_count": page_count,
            "block_count": block_count,
            "ui_skill_enabled": bool(settings.get("ui_skill_enabled", True)),
            "mode": str(settings.get("ui_skill_mode") or "narrative_tool_hybrid"),
            "token_policy": str(settings.get("ui_token_policy") or "balanced"),
            "runtime_skill_passed": runtime_skill_passed,
            "runtime_skillpack_id": str((runtime_skill_plan.get("skillpack") or {}).get("id") or ""),
            "runtime_domain": str((runtime_skill_plan.get("domain_match") or {}).get("domain") or "generic"),
            "runtime_rule_count": runtime_rule_count,
            "runtime_override_applied": bool((runtime_skill_plan.get("override_applied") or {}).get("applied")),
        },
        "paths": {
            "profile_path": str(profile_path),
            "blueprint_path": str(blueprint_path),
            "contract_path": str(contract_path),
            "runtime_skill_path": str(runtime_skill_path),
            "runtime_rule_graph_path": str(runtime_rule_graph_path),
        },
    }
    _save_json(report_path, report)

    return {
        "profile_path": profile_path,
        "blueprint_path": blueprint_path,
        "contract_path": contract_path,
        "runtime_skill_path": runtime_skill_path,
        "runtime_rule_graph_path": runtime_rule_graph_path,
        "report_path": report_path,
        "profile": profile,
        "blueprint": blueprint,
        "contract": contract,
        "runtime_skill_plan": runtime_skill_plan,
        "runtime_rule_graph": runtime_rule_graph,
        "report": report,
    }


def load_ui_blueprint(project_dir: Path) -> Dict[str, Any]:
    return _load_json(Path(project_dir) / "ui_blueprint.json")


def load_screenshot_contract(project_dir: Path) -> Dict[str, Any]:
    return _load_json(Path(project_dir) / "screenshot_contract.json")
