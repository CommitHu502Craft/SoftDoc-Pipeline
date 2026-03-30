"""
Skill Studio: natural-language intent to runtime-skill decision artifacts.

This module is for product runtime planning (not Codex development skills).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.executable_spec_builder import build_executable_spec, save_executable_spec
from modules.project_charter import normalize_project_charter
from modules.runtime_skill_engine import validate_runtime_skill_override
from modules.spec_review import get_spec_review_status, save_spec_review_artifacts


DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "workflow": ["工单", "审批", "流转", "派单", "待办", "任务", "流程"],
    "knowledge": ["知识", "检索", "文档", "资料", "索引", "标签", "问答"],
    "operations": ["监控", "告警", "巡检", "容量", "性能", "运维", "状态"],
    "reporting": ["统计", "报表", "趋势", "分析", "对比", "图表", "看板"],
    "relationship": ["客户", "线索", "联系人", "跟进", "关系", "crm"],
}

DOMAIN_PAGE_CATALOG: Dict[str, List[str]] = {
    "workflow": ["首页", "工单池", "处理台", "统计页", "规则页", "日志页", "配置页"],
    "knowledge": ["首页", "检索页", "文档页", "标签页", "统计页", "设置页", "日志页"],
    "operations": ["首页", "监控页", "告警页", "巡检页", "统计页", "设置页", "日志页"],
    "reporting": ["首页", "指标页", "趋势页", "对比页", "报表页", "归档页", "设置页"],
    "relationship": ["首页", "客户页", "线索页", "跟进页", "统计页", "设置页", "日志页"],
    "generic": ["首页", "业务页", "处理页", "统计页", "报表页", "设置页", "日志页"],
}

DOMAIN_CHART_TYPES: Dict[str, List[str]] = {
    "workflow": ["line", "bar", "funnel", "heatmap", "gauge"],
    "knowledge": ["bar", "treemap", "line", "scatter", "pie"],
    "operations": ["line", "heatmap", "scatter", "bar", "gauge"],
    "reporting": ["bar", "line", "pie", "scatter", "heatmap"],
    "relationship": ["funnel", "line", "bar", "pie", "sankey"],
    "generic": ["bar", "line", "pie", "scatter", "heatmap"],
}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _short_title(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return "页面"
    return text[:5] if len(text) > 5 else text


def _detect_domain(project_name: str, intent_text: str) -> str:
    text = f"{project_name} {intent_text}".lower()
    best = ("generic", 0)
    for domain, words in DOMAIN_KEYWORDS.items():
        score = sum(1 for w in words if w and w.lower() in text)
        if score > best[1]:
            best = (domain, score)
    return best[0]


def _extract_page_count(intent_text: str, min_pages: int = 6, max_pages: int = 8) -> int:
    text = str(intent_text or "")
    m = re.search(r"([6-8])\s*个?\s*页", text)
    if m:
        return max(min_pages, min(max_pages, int(m.group(1))))
    for digit in ("6", "7", "8"):
        if f"{digit}个页面" in text or f"{digit}页" in text:
            return int(digit)
    return min_pages


def _detect_token_policy(intent_text: str) -> str:
    text = str(intent_text or "").lower()
    if any(k in text for k in ["减少token", "省token", "省tokens", "低成本", "快点出结果", "economy"]):
        return "economy"
    if any(k in text for k in ["精美", "高级", "一次成功", "严查", "授权", "quality", "高质量"]):
        return "quality_first"
    return "balanced"


def _detect_ui_mode(intent_text: str) -> str:
    text = str(intent_text or "").lower()
    if any(k in text for k in ["codex", "ai ide", "aiide", "叙事", "工具混合"]):
        return "narrative_tool_hybrid"
    if "tool_first" in text:
        return "tool_first"
    if "narrative_first" in text:
        return "narrative_first"
    return "narrative_tool_hybrid"


def _extract_named_pages(intent_text: str) -> List[str]:
    text = str(intent_text or "")
    segments = re.split(r"[，,。；;、\n\r\t ]+", text)
    candidates: List[str] = []
    for seg in segments:
        token = str(seg or "").strip()
        if not token:
            continue
        if len(token) > 8:
            continue
        if any(x in token for x in ["页面", "页", "台", "池", "中心", "列表", "报表", "看板", "设置"]):
            clean = token.replace("页面", "页")
            candidates.append(_short_title(clean))
    dedup: List[str] = []
    for item in candidates:
        if item and item not in dedup:
            dedup.append(item)
    return dedup[:8]


def _build_page_catalog(domain: str, intent_text: str, page_count: int) -> List[str]:
    requested = _extract_named_pages(intent_text)
    baseline = list(DOMAIN_PAGE_CATALOG.get(domain, DOMAIN_PAGE_CATALOG["generic"]))
    pages: List[str] = []
    for item in requested + baseline:
        name = _short_title(item)
        if name and name not in pages:
            pages.append(name)
        if len(pages) >= page_count:
            break
    while len(pages) < page_count:
        pages.append(_short_title(f"页面{len(pages) + 1}"))
    return pages[:page_count]


def _build_page_description(page_title: str) -> str:
    title = str(page_title or "业务页").strip() or "业务页"
    return (
        f"本页面围绕{title}组织录入、查询与状态变更操作，输入框、下拉框和按钮按处理顺序排列。"
        f"{title}支持先设置筛选条件再执行查询，结果区会保留当前条件并联动详情区域。"
        f"{title}提供新增和编辑入口，点击按钮后弹出填写窗口，确认后写入当前记录并刷新状态。"
        f"{title}中的下拉框用于选择处理类型、优先级和责任项，切换后会联动展示不同字段。"
        f"{title}会记录每次提交前后的字段变化与处理说明，便于后续复核执行过程。"
        "鼠标悬停在图表自己想了解的数据上方，可以查看具体数值。"
    )


def _build_overview(project_name: str, domain: str) -> str:
    name = str(project_name or "本系统").strip() or "本系统"
    domain_text = {
        "workflow": "业务流程处理",
        "knowledge": "知识检索与文档处理",
        "operations": "运维监控与告警处理",
        "reporting": "统计分析与报表归档",
        "relationship": "客户关系与线索跟进",
    }.get(domain, "业务处理与统计分析")
    return (
        f"{name}用于{domain_text}，系统把页面操作和后台接口按统一规则串联。"
        "首页提供关键入口，业务页提供筛选、表单提交和状态流转。"
        "同一套页面支持事项登记、记录跟进、异常处理、结果复核和报表导出。"
        "每次操作生成可回溯记录，包含时间、处理动作和变更字段。"
        "系统按角色控制操作入口，并在提交前执行必填与格式校验。"
        "输出的截图、接口映射和代码定位信息保持一致，便于审查核对。"
    )


def _build_runtime_override(
    intent_text: str,
    domain: str,
    page_catalog: List[str],
    token_policy: str,
) -> Dict[str, Any]:
    page_count = len(page_catalog)
    chart_types = DOMAIN_CHART_TYPES.get(domain, DOMAIN_CHART_TYPES["generic"])
    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "skill_studio",
            "intent_excerpt": str(intent_text or "")[:500],
            "domain": domain,
            "token_policy": token_policy,
        },
        "constraints": {
            "page_catalog": {
                "page_count_min": max(6, page_count),
                "page_count_max": max(8, page_count),
                "page_name_len_max": 5,
            },
            "required_pages": page_catalog,
            "preferred_chart_types": chart_types,
            "page_narration": {
                "sentence_count_per_page": 6,
                "min_chars_per_page": 300,
                "first_sentence_prefix": "本页面",
                "avoid_terms": ["模块", "板块", "主页面", "区域"],
                "ban_words": ["重要", "高效", "全面", "丰富", "核心", "聚焦"],
                "replacement_map": {"展示": "有"},
                "chart_append_sentence": "鼠标悬停在图表自己想了解的数据上方，可以查看具体数值。",
            },
            "overview_copy": {
                "target_chars": 250,
                "ban_topics": ["AI", "智能"],
            },
            "frontend": {
                "button_action_required": True,
                "button_action_unique": True,
                "modal_api_required": "showModal",
                "no_comments_required": True,
                "no_rounded_rectangles": True,
                "chart_required": True,
                "chart_responsive": False,
                "chart_maintain_aspect_ratio": True,
            },
        },
    }


def _icon_for_page(title: str) -> str:
    text = str(title or "")
    if "首页" in text:
        return "mdi mdi-home"
    if any(k in text for k in ["统计", "报表", "趋势", "对比"]):
        return "mdi mdi-chart-line"
    if any(k in text for k in ["设置", "配置"]):
        return "mdi mdi-cog"
    if any(k in text for k in ["日志", "归档"]):
        return "mdi mdi-file-document"
    if any(k in text for k in ["检索", "搜索"]):
        return "mdi mdi-magnify"
    if any(k in text for k in ["监控", "告警"]):
        return "mdi mdi-monitor"
    return "mdi mdi-view-grid"


def _apply_to_project_plan(plan: Dict[str, Any], project_name: str, page_catalog: List[str], domain: str) -> Dict[str, Any]:
    payload = dict(plan or {})
    payload["project_name"] = project_name
    payload["skill_studio_replanned_at"] = datetime.now().isoformat(timespec="seconds")

    pages: Dict[str, Any] = {}
    menu_list: List[Dict[str, Any]] = []
    for idx, page_title in enumerate(page_catalog, start=1):
        page_id = f"page_{idx}"
        menu_list.append(
            {
                "title": _short_title(page_title),
                "icon": _icon_for_page(page_title),
                "page_id": page_id,
                "url": f"{page_id}.html",
            }
        )
        pages[page_id] = {
            "page_title": _short_title(page_title),
            "page_description": _build_page_description(page_title),
        }

    payload["menu_list"] = menu_list
    payload["pages"] = pages

    intro = payload.get("project_intro") if isinstance(payload.get("project_intro"), dict) else {}
    intro = dict(intro or {})
    intro["overview"] = _build_overview(project_name=project_name, domain=domain)
    intro.setdefault("main_features", [f"{x}功能处理" for x in page_catalog[:5]])
    payload["project_intro"] = intro

    # Invalidate stale derived sections to avoid one-shot mismatches.
    payload.pop("code_blueprint", None)
    payload.pop("executable_spec", None)
    return payload


def run_skill_studio(
    project_name: str,
    project_dir: Path,
    intent_text: str,
    apply_to_plan: bool = True,
    rebuild_ui_skill: bool = True,
    domain_override: str = "",
    ui_mode_override: str = "",
    token_policy_override: str = "",
    page_count_override: int = 0,
    feature_preferences: Optional[List[str]] = None,
    preset_template: str = "",
) -> Dict[str, Any]:
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    plan_path = project_dir / "project_plan.json"
    existing_plan = _load_json(plan_path)

    normalized_features = [str(x).strip() for x in (feature_preferences or []) if str(x).strip()]
    normalized_preset = str(preset_template or "").strip()
    effective_intent = " ".join([str(intent_text or "").strip(), *normalized_features, normalized_preset]).strip()

    domain_candidate = str(domain_override or "").strip().lower()
    domain = domain_candidate if domain_candidate in DOMAIN_PAGE_CATALOG else _detect_domain(project_name, effective_intent)

    token_candidate = str(token_policy_override or "").strip().lower()
    token_policy = token_candidate if token_candidate in {"economy", "balanced", "quality_first"} else _detect_token_policy(effective_intent)

    ui_mode_candidate = str(ui_mode_override or "").strip()
    ui_mode = ui_mode_candidate if ui_mode_candidate in {"narrative_tool_hybrid", "tool_first", "narrative_first"} else _detect_ui_mode(effective_intent)

    if int(page_count_override or 0) > 0:
        page_count = max(6, min(8, int(page_count_override)))
    else:
        page_count = _extract_page_count(effective_intent, min_pages=6, max_pages=8)

    page_catalog = _build_page_catalog(domain=domain, intent_text=effective_intent, page_count=page_count)
    override = _build_runtime_override(effective_intent, domain=domain, page_catalog=page_catalog, token_policy=token_policy)
    override_validation = validate_runtime_skill_override(override)
    if not bool(override_validation.get("passed")):
        issues = [str(x) for x in (override_validation.get("issues") or []) if str(x).strip()]
        raise ValueError(f"Skill Studio 覆盖配置不合法: {';'.join(issues[:6])}")

    studio_plan = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "intent_text": str(intent_text or ""),
        "effective_intent_text": effective_intent,
        "decisions": {
            "domain": domain,
            "ui_mode": ui_mode,
            "token_policy": token_policy,
            "page_count": len(page_catalog),
            "page_catalog": page_catalog,
            "chart_types": DOMAIN_CHART_TYPES.get(domain, DOMAIN_CHART_TYPES["generic"]),
            "feature_preferences": normalized_features,
            "preset_template": normalized_preset,
        },
        "runtime_override_path": str(project_dir / "runtime_skill_override.json"),
        "override_validation": override_validation,
        "apply_to_plan": bool(apply_to_plan),
        "rebuild_ui_skill": bool(rebuild_ui_skill),
    }
    _save_json(project_dir / "skill_studio_plan.json", studio_plan)
    _save_json(project_dir / "runtime_skill_override.json", override)

    actions: List[str] = ["write_skill_studio_plan", "write_runtime_skill_override"]
    updated_plan = existing_plan
    if apply_to_plan:
        updated_plan = _apply_to_project_plan(existing_plan, project_name=project_name, page_catalog=page_catalog, domain=domain)
        _save_json(plan_path, updated_plan)
        actions.append("rewrite_project_plan")

    spec_path = project_dir / "project_executable_spec.json"
    spec_digest = ""
    spec_review_status = "missing_spec"
    if apply_to_plan and updated_plan:
        charter_path = project_dir / "project_charter.json"
        charter = normalize_project_charter(_load_json(charter_path), project_name=project_name)
        spec = build_executable_spec(updated_plan, charter)
        save_executable_spec(project_dir, spec)
        actions.append("rebuild_executable_spec")
        review_artifacts = save_spec_review_artifacts(project_dir, project_name=project_name, spec=spec)
        if review_artifacts.get("ok"):
            actions.append("refresh_spec_review_artifacts")
        status = get_spec_review_status(project_dir, spec_path)
        spec_digest = str(status.get("spec_digest") or "")
        spec_review_status = str(status.get("review_status") or "pending")

    ui_skill_artifacts = {}
    if rebuild_ui_skill and updated_plan:
        try:
            from modules.ui_skill_orchestrator import build_ui_skill_artifacts

            ui_skill_artifacts = build_ui_skill_artifacts(
                project_name=project_name,
                plan=updated_plan,
                project_dir=project_dir,
                force=True,
                settings_override={
                    "ui_skill_enabled": True,
                    "ui_skill_mode": ui_mode,
                    "ui_token_policy": token_policy,
                },
            )
            actions.append("rebuild_ui_skill_artifacts")
        except Exception as e:
            studio_plan["ui_skill_rebuild_error"] = str(e)
            _save_json(project_dir / "skill_studio_plan.json", studio_plan)

    studio_plan["actions"] = actions
    studio_plan["ui_skill_artifacts"] = {
        "profile_path": str(ui_skill_artifacts.get("profile_path") or ""),
        "blueprint_path": str(ui_skill_artifacts.get("blueprint_path") or ""),
        "contract_path": str(ui_skill_artifacts.get("contract_path") or ""),
        "runtime_skill_path": str(ui_skill_artifacts.get("runtime_skill_path") or ""),
        "runtime_rule_graph_path": str(ui_skill_artifacts.get("runtime_rule_graph_path") or ""),
        "report_path": str(ui_skill_artifacts.get("report_path") or ""),
    }
    studio_plan["spec"] = {
        "spec_path": str(spec_path),
        "spec_digest": spec_digest,
        "spec_review_status": spec_review_status,
    }
    _save_json(project_dir / "skill_studio_plan.json", studio_plan)

    return {
        "ok": True,
        "project_name": project_name,
        "project_dir": str(project_dir),
        "skill_studio_plan_path": str(project_dir / "skill_studio_plan.json"),
        "runtime_skill_override_path": str(project_dir / "runtime_skill_override.json"),
        "project_plan_path": str(plan_path),
        "spec_path": str(spec_path),
        "spec_digest": spec_digest,
        "spec_review_status": spec_review_status,
        "override_validation": override_validation,
        "actions": actions,
        "decisions": studio_plan.get("decisions") or {},
        "ui_skill_artifacts": studio_plan.get("ui_skill_artifacts") or {},
    }
