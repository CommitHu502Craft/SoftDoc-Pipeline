"""
Runtime skill engine for software-copyright generation pipeline.

This is NOT Codex development skill loading. It is runtime skillpack loading
for the product pipeline decision layer.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import BASE_DIR


DEFAULT_EXTERNAL_SCRIPT_POLICY: Dict[str, Any] = {
    "mode": "allowlist_with_vendor_fallback",
    "allowed_domains": ["cdn.jsdelivr.net", "unpkg.com"],
    "vendor_fallback": {
        "echarts": "vendor/echarts/5.4.3/echarts.min.js",
    },
}

_OVERRIDE_ALLOWED_ROOT_KEYS = {"meta", "metadata", "constraints"}
_OVERRIDE_ALLOWED_CONSTRAINT_KEYS = {
    "page_catalog",
    "required_pages",
    "required_block_types",
    "preferred_chart_types",
    "page_narration",
    "overview_copy",
    "frontend",
}
_OVERRIDE_ALLOWED_PAGE_CATALOG_KEYS = {"page_count_min", "page_count_max", "page_name_len_max", "ban_topics"}
_OVERRIDE_ALLOWED_PAGE_NARRATION_KEYS = {
    "sentence_count_per_page",
    "min_chars_per_page",
    "first_sentence_prefix",
    "forbid_phrase_after_first",
    "avoid_terms",
    "ban_words",
    "ban_topics",
    "ban_date_mentions",
    "max_cross_page_similarity",
    "replacement_map",
    "chart_append_sentence",
}
_OVERRIDE_ALLOWED_OVERVIEW_KEYS = {"target_chars", "ban_words", "ban_topics"}
_OVERRIDE_ALLOWED_FRONTEND_KEYS = {
    "single_html_required",
    "no_comments_required",
    "no_external_script",
    "external_script_policy",
    "nav_gradient_max_colors",
    "no_rounded_rectangles",
    "chart_required",
    "chart_responsive",
    "chart_maintain_aspect_ratio",
    "chart_aspect_ratio",
    "button_action_required",
    "button_action_unique",
    "modal_api_required",
}
_OVERRIDE_ALLOWED_EXTERNAL_POLICY_KEYS = {"mode", "allowed_domains", "vendor_fallback"}
_OVERRIDE_ALLOWED_EXTERNAL_MODES = {"allowlist_with_vendor_fallback", "strict_no_external", "allow_all"}


DEFAULT_RUNTIME_SKILLPACK: Dict[str, Any] = {
    "id": "soft_copyright_master_v1",
    "version": "1.0.0",
    "description": "软著生成全链路技能包（命名/页面/文案/前端/证据/门禁）",
    "orchestration": {
        "trigger_order": ["intent", "visual", "functional", "evidence", "token"],
        "conflict_priority": [
            "evidence_auditability",
            "functional_completeness",
            "visual_expression",
            "token_saving",
        ],
        "degrade_path": ["advanced_skills", "base_skills", "rules_template"],
    },
    "stages": [
        "sr_global_constraints_v1",
        "sr_naming_v1",
        "sr_overview_copy_v1",
        "sr_page_catalog_v1",
        "sr_palette_cn_v1",
        "sr_frontend_single_html_v1",
        "sr_page_narration_v1",
        "sr_quality_gate_v1",
    ],
    "triggers": {
        "keywords": ["系统", "平台", "软件", "管理", "工单", "监控", "检索"],
        "fallback": True,
        "priority": 100,
    },
    "constraints": {
        "naming": {
            "suffix_whitelist": ["平台", "软件", "系统"],
            "full_name_required": True,
            "short_name_required": True,
        },
        "overview_copy": {
            "target_chars": 250,
            "ban_words": [
                "专注",
                "聚焦",
                "整合",
                "综合",
                "重要",
                "核心",
                "关键",
                "有效",
                "契合",
                "强调",
                "延伸",
                "大量",
                "呼应",
                "确立",
                "明确",
                "基础",
            ],
            "ban_topics": ["AI", "智能"],
        },
        "page_catalog": {
            "page_count_min": 6,
            "page_count_max": 8,
            "page_name_len_max": 5,
            "ban_topics": ["国家法律法规", "AI", "智能"],
        },
        "page_narration": {
            "sentence_count_per_page": 6,
            "min_chars_per_page": 300,
            "first_sentence_prefix": "本页面",
            "forbid_phrase_after_first": "本页面",
            "avoid_terms": ["模块", "板块", "主页面", "区域"],
            "ban_words": ["重要", "高效", "全面", "丰富", "核心", "聚焦"],
            "ban_topics": ["AI", "智能", "导航栏", "页脚"],
            "ban_date_mentions": True,
            "max_cross_page_similarity": 0.98,
            "replacement_map": {"展示": "有"},
            "chart_append_sentence": "鼠标悬停在图表自己想了解的数据上方，可以查看具体数值。",
        },
        "frontend": {
            "single_html_required": True,
            "no_comments_required": True,
            "no_external_script": True,
            "external_script_policy": {
                "mode": "allowlist_with_vendor_fallback",
                "allowed_domains": ["cdn.jsdelivr.net", "unpkg.com"],
                "vendor_fallback": {
                    "echarts": "vendor/echarts/5.4.3/echarts.min.js",
                },
            },
            "nav_gradient_max_colors": 2,
            "no_rounded_rectangles": True,
            "chart_required": True,
            "chart_responsive": False,
            "chart_maintain_aspect_ratio": True,
            "chart_aspect_ratio": "1:1",
            "button_action_required": True,
            "button_action_unique": True,
            "modal_api_required": "showModal",
        },
        "palette": {
            "theme": "chinese_traditional",
            "rgb_required": True,
            "usage_spec_required": True,
        },
    },
    "domain_overrides": [
        {
            "domain": "workflow",
            "keywords": ["工单", "审批", "派单", "流转", "任务"],
            "required_pages": ["首页", "工单池", "处理台", "统计页", "规则页", "日志页"],
            "required_block_types": ["filter_bar", "action_form", "data_table", "detail_panel", "chart_card"],
            "chart_types": ["line", "bar", "funnel", "heatmap", "gauge"],
        },
        {
            "domain": "knowledge",
            "keywords": ["知识", "检索", "文档", "索引", "语料"],
            "required_pages": ["首页", "检索页", "文档页", "标签页", "统计页", "设置页"],
            "required_block_types": ["search_form", "data_table", "detail_panel", "chart_card", "action_form"],
            "chart_types": ["bar", "treemap", "line", "scatter", "pie"],
        },
        {
            "domain": "operations",
            "keywords": ["监控", "告警", "巡检", "容量", "性能"],
            "required_pages": ["首页", "监控页", "告警页", "巡检页", "统计页", "设置页"],
            "required_block_types": ["kpi_strip", "filter_bar", "chart_card", "data_table", "detail_panel"],
            "chart_types": ["line", "heatmap", "scatter", "bar", "gauge"],
        },
    ],
}


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


def _runtime_skill_dir() -> Path:
    return BASE_DIR / "runtime_skills"


def _safe_text_tokens(parts: List[Any]) -> List[str]:
    merged = " ".join([str(x or "") for x in parts]).lower()
    tokens = []
    for raw in merged.replace("/", " ").replace("_", " ").replace("-", " ").split():
        item = raw.strip()
        if len(item) >= 2:
            tokens.append(item)
    return tokens


def _skillpack_files() -> List[Path]:
    root = _runtime_skill_dir()
    if not root.exists():
        return []
    return sorted([p for p in root.glob("*.json") if p.is_file()])


def _validate_skillpack(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    if not isinstance(payload, dict):
        return False, ["skillpack 非法：不是 JSON 对象"]
    if not str(payload.get("id") or "").strip():
        issues.append("缺少 id")
    orchestration = payload.get("orchestration") or {}
    if not isinstance(orchestration, dict):
        issues.append("缺少 orchestration 配置")
    else:
        if not isinstance(orchestration.get("trigger_order"), list):
            issues.append("orchestration.trigger_order 非法")
        if not isinstance(orchestration.get("conflict_priority"), list):
            issues.append("orchestration.conflict_priority 非法")
    constraints = payload.get("constraints") or {}
    if not isinstance(constraints, dict):
        issues.append("缺少 constraints 配置")
    else:
        for key in ("naming", "page_catalog", "page_narration", "frontend"):
            if not isinstance(constraints.get(key), dict):
                issues.append(f"constraints.{key} 缺失或非法")
    return len(issues) == 0, issues


def migrate_runtime_skillpack_schema(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Migrate legacy skillpack fields to current schema without mutating input.

    Current focus:
    - constraints.frontend.no_external_script -> external_script_policy
    """
    data = dict(payload or {})
    constraints = data.get("constraints") if isinstance(data.get("constraints"), dict) else {}
    constraints = dict(constraints)
    frontend = constraints.get("frontend") if isinstance(constraints.get("frontend"), dict) else {}
    frontend = dict(frontend)

    changes: List[str] = []
    policy_raw = frontend.get("external_script_policy")
    if not isinstance(policy_raw, dict) or (not policy_raw):
        mode = "strict_no_external" if bool(frontend.get("no_external_script", False)) else "allow_all"
        frontend["external_script_policy"] = {"mode": mode}
        changes.append("constraints.frontend.external_script_policy")

    normalized_policy = resolve_external_script_policy(frontend)
    if frontend.get("external_script_policy") != normalized_policy:
        frontend["external_script_policy"] = normalized_policy
        changes.append("constraints.frontend.external_script_policy.normalized")

    constraints["frontend"] = frontend
    data["constraints"] = constraints
    return data, changes


def load_runtime_skillpacks() -> List[Dict[str, Any]]:
    packs: List[Dict[str, Any]] = []
    for path in _skillpack_files():
        payload = _load_json(path)
        migrated_payload, migration_changes = migrate_runtime_skillpack_schema(payload)
        ok, issues = _validate_skillpack(migrated_payload)
        migrated_payload = migrated_payload if isinstance(migrated_payload, dict) else {}
        migrated_payload["source_path"] = str(path)
        migrated_payload["schema_migration"] = {
            "applied": bool(migration_changes),
            "changes": migration_changes,
        }
        validation = {"passed": ok, "issues": issues}
        if migration_changes:
            validation["warnings"] = [f"已自动迁移 schema 字段: {','.join(migration_changes)}"]
        migrated_payload["validation"] = validation
        packs.append(migrated_payload)

    if not packs:
        fallback, migration_changes = migrate_runtime_skillpack_schema(dict(DEFAULT_RUNTIME_SKILLPACK))
        fallback["source_path"] = "builtin:soft_copyright_master_v1"
        fallback["schema_migration"] = {
            "applied": bool(migration_changes),
            "changes": migration_changes,
        }
        ok, issues = _validate_skillpack(fallback)
        validation = {"passed": ok, "issues": issues}
        if migration_changes:
            validation["warnings"] = [f"已自动迁移 schema 字段: {','.join(migration_changes)}"]
        fallback["validation"] = validation
        packs = [fallback]
    return packs


def _calc_pack_match_score(pack: Dict[str, Any], tokens: List[str]) -> int:
    triggers = pack.get("triggers") or {}
    keywords = [str(x).lower().strip() for x in (triggers.get("keywords") or []) if str(x).strip()]
    score = 0
    for kw in keywords:
        if kw and any(kw in token or token in kw for token in tokens):
            score += 3
    score += int(triggers.get("priority") or 0)
    if score == 0 and bool(triggers.get("fallback")):
        score = 1
    return score


def _pick_domain_override(pack: Dict[str, Any], tokens: List[str]) -> Dict[str, Any]:
    best: Tuple[Optional[Dict[str, Any]], int] = (None, -1)
    for override in (pack.get("domain_overrides") or []):
        if not isinstance(override, dict):
            continue
        kws = [str(x).lower().strip() for x in (override.get("keywords") or []) if str(x).strip()]
        score = 0
        for kw in kws:
            if any(kw in token or token in kw for token in tokens):
                score += 1
        if score > best[1]:
            best = (override, score)
    return best[0] or {}


def _deep_merge_dict(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(a or {})
    for key, val in (b or {}).items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dict(result.get(key) or {}, val)
        else:
            result[key] = val
    return result


def _calc_constraints_checksum(constraints: Dict[str, Any]) -> str:
    text = json.dumps(constraints or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _normalize_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    normalized: List[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_relative_path(text: Any) -> str:
    raw = str(text or "").replace("\\", "/").strip().lstrip("/")
    raw = re.sub(r"/{2,}", "/", raw)
    return raw


def resolve_external_script_policy(frontend_constraints: Dict[str, Any]) -> Dict[str, Any]:
    frontend = frontend_constraints if isinstance(frontend_constraints, dict) else {}
    policy_raw = frontend.get("external_script_policy")
    policy = policy_raw if isinstance(policy_raw, dict) else {}

    mode = str(policy.get("mode") or "").strip().lower()
    if mode not in _OVERRIDE_ALLOWED_EXTERNAL_MODES:
        # Backward compatibility with old no_external_script field.
        mode = "strict_no_external" if bool(frontend.get("no_external_script", False)) else "allow_all"
        if "external_script_policy" in frontend:
            mode = "allowlist_with_vendor_fallback"

    allowed_domains = _normalize_string_list(policy.get("allowed_domains"))
    if not allowed_domains:
        allowed_domains = list(DEFAULT_EXTERNAL_SCRIPT_POLICY["allowed_domains"])

    vendor_fallback = policy.get("vendor_fallback") if isinstance(policy.get("vendor_fallback"), dict) else {}
    normalized_vendor_fallback: Dict[str, str] = {}
    for key, value in vendor_fallback.items():
        lib = str(key or "").strip().lower()
        rel = _normalize_relative_path(value)
        if lib and rel:
            normalized_vendor_fallback[lib] = rel
    if "echarts" not in normalized_vendor_fallback:
        normalized_vendor_fallback["echarts"] = str(
            (DEFAULT_EXTERNAL_SCRIPT_POLICY.get("vendor_fallback") or {}).get("echarts") or "vendor/echarts/5.4.3/echarts.min.js"
        )

    return {
        "mode": mode,
        "allowed_domains": allowed_domains,
        "vendor_fallback": normalized_vendor_fallback,
    }


def _normalize_frontend_constraints(frontend: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(frontend or {})
    payload["external_script_policy"] = resolve_external_script_policy(payload)
    return payload


def _issue(path: str, message: str) -> str:
    p = str(path or "").strip()
    return f"{p}: {message}" if p else message


def _validate_int_range(value: Any, path: str, minimum: int, maximum: int, issues: List[str]) -> None:
    try:
        ivalue = int(value)
    except Exception:
        issues.append(_issue(path, "必须为整数"))
        return
    if ivalue < minimum or ivalue > maximum:
        issues.append(_issue(path, f"超出范围 [{minimum}, {maximum}]"))


def _validate_float_range(value: Any, path: str, minimum: float, maximum: float, issues: List[str]) -> None:
    try:
        fvalue = float(value)
    except Exception:
        issues.append(_issue(path, "必须为数字"))
        return
    if fvalue < minimum or fvalue > maximum:
        issues.append(_issue(path, f"超出范围 [{minimum}, {maximum}]"))


def _validate_bool(value: Any, path: str, issues: List[str]) -> None:
    if not isinstance(value, bool):
        issues.append(_issue(path, "必须为布尔值"))


def _validate_str(value: Any, path: str, issues: List[str]) -> None:
    if not isinstance(value, str) or not str(value).strip():
        issues.append(_issue(path, "必须为非空字符串"))


def _validate_str_list(value: Any, path: str, issues: List[str], max_items: int = 64) -> None:
    if not isinstance(value, list):
        issues.append(_issue(path, "必须为字符串数组"))
        return
    if len(value) > max_items:
        issues.append(_issue(path, f"元素数量超限（>{max_items}）"))
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(_issue(f"{path}[{idx}]", "必须为非空字符串"))


def validate_runtime_skill_override(override_payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = override_payload if isinstance(override_payload, dict) else {}
    issues: List[str] = []

    unknown_root = sorted([str(k) for k in payload.keys() if str(k) not in _OVERRIDE_ALLOWED_ROOT_KEYS])
    if unknown_root:
        issues.append(_issue("", f"存在未允许根键: {','.join(unknown_root)}"))

    constraints = payload.get("constraints")
    if constraints is None:
        # 允许仅有 meta，视为“无覆盖”。
        return {"passed": len(issues) == 0, "issues": issues}
    if not isinstance(constraints, dict):
        issues.append(_issue("constraints", "必须为对象"))
        return {"passed": False, "issues": issues}

    unknown_constraints = sorted([str(k) for k in constraints.keys() if str(k) not in _OVERRIDE_ALLOWED_CONSTRAINT_KEYS])
    if unknown_constraints:
        issues.append(_issue("constraints", f"存在未允许键: {','.join(unknown_constraints)}"))

    page_catalog = constraints.get("page_catalog")
    if page_catalog is not None:
        if not isinstance(page_catalog, dict):
            issues.append(_issue("constraints.page_catalog", "必须为对象"))
        else:
            unknown = sorted([str(k) for k in page_catalog.keys() if str(k) not in _OVERRIDE_ALLOWED_PAGE_CATALOG_KEYS])
            if unknown:
                issues.append(_issue("constraints.page_catalog", f"存在未允许键: {','.join(unknown)}"))
            if "page_count_min" in page_catalog:
                _validate_int_range(page_catalog.get("page_count_min"), "constraints.page_catalog.page_count_min", 1, 20, issues)
            if "page_count_max" in page_catalog:
                _validate_int_range(page_catalog.get("page_count_max"), "constraints.page_catalog.page_count_max", 1, 20, issues)
            if "page_name_len_max" in page_catalog:
                _validate_int_range(page_catalog.get("page_name_len_max"), "constraints.page_catalog.page_name_len_max", 2, 20, issues)
            if "ban_topics" in page_catalog:
                _validate_str_list(page_catalog.get("ban_topics"), "constraints.page_catalog.ban_topics", issues, max_items=32)

    for key in ("required_pages", "required_block_types", "preferred_chart_types"):
        if key in constraints:
            _validate_str_list(constraints.get(key), f"constraints.{key}", issues, max_items=64)

    page_narration = constraints.get("page_narration")
    if page_narration is not None:
        if not isinstance(page_narration, dict):
            issues.append(_issue("constraints.page_narration", "必须为对象"))
        else:
            unknown = sorted([str(k) for k in page_narration.keys() if str(k) not in _OVERRIDE_ALLOWED_PAGE_NARRATION_KEYS])
            if unknown:
                issues.append(_issue("constraints.page_narration", f"存在未允许键: {','.join(unknown)}"))
            if "sentence_count_per_page" in page_narration:
                _validate_int_range(
                    page_narration.get("sentence_count_per_page"),
                    "constraints.page_narration.sentence_count_per_page",
                    1,
                    20,
                    issues,
                )
            if "min_chars_per_page" in page_narration:
                _validate_int_range(
                    page_narration.get("min_chars_per_page"),
                    "constraints.page_narration.min_chars_per_page",
                    50,
                    2000,
                    issues,
                )
            if "first_sentence_prefix" in page_narration:
                _validate_str(page_narration.get("first_sentence_prefix"), "constraints.page_narration.first_sentence_prefix", issues)
            if "forbid_phrase_after_first" in page_narration:
                _validate_str(
                    page_narration.get("forbid_phrase_after_first"),
                    "constraints.page_narration.forbid_phrase_after_first",
                    issues,
                )
            for key in ("avoid_terms", "ban_words"):
                if key in page_narration:
                    _validate_str_list(page_narration.get(key), f"constraints.page_narration.{key}", issues, max_items=64)
            if "ban_topics" in page_narration:
                _validate_str_list(page_narration.get("ban_topics"), "constraints.page_narration.ban_topics", issues, max_items=64)
            if "ban_date_mentions" in page_narration:
                _validate_bool(page_narration.get("ban_date_mentions"), "constraints.page_narration.ban_date_mentions", issues)
            if "max_cross_page_similarity" in page_narration:
                _validate_float_range(
                    page_narration.get("max_cross_page_similarity"),
                    "constraints.page_narration.max_cross_page_similarity",
                    0.5,
                    1.0,
                    issues,
                )
            if "replacement_map" in page_narration and not isinstance(page_narration.get("replacement_map"), dict):
                issues.append(_issue("constraints.page_narration.replacement_map", "必须为对象"))
            if "chart_append_sentence" in page_narration:
                _validate_str(page_narration.get("chart_append_sentence"), "constraints.page_narration.chart_append_sentence", issues)

    overview_copy = constraints.get("overview_copy")
    if overview_copy is not None:
        if not isinstance(overview_copy, dict):
            issues.append(_issue("constraints.overview_copy", "必须为对象"))
        else:
            unknown = sorted([str(k) for k in overview_copy.keys() if str(k) not in _OVERRIDE_ALLOWED_OVERVIEW_KEYS])
            if unknown:
                issues.append(_issue("constraints.overview_copy", f"存在未允许键: {','.join(unknown)}"))
            if "target_chars" in overview_copy:
                _validate_int_range(overview_copy.get("target_chars"), "constraints.overview_copy.target_chars", 100, 2000, issues)
            for key in ("ban_words", "ban_topics"):
                if key in overview_copy:
                    _validate_str_list(overview_copy.get(key), f"constraints.overview_copy.{key}", issues, max_items=64)

    frontend = constraints.get("frontend")
    if frontend is not None:
        if not isinstance(frontend, dict):
            issues.append(_issue("constraints.frontend", "必须为对象"))
        else:
            unknown = sorted([str(k) for k in frontend.keys() if str(k) not in _OVERRIDE_ALLOWED_FRONTEND_KEYS])
            if unknown:
                issues.append(_issue("constraints.frontend", f"存在未允许键: {','.join(unknown)}"))
            bool_keys = {
                "single_html_required",
                "no_comments_required",
                "no_external_script",
                "no_rounded_rectangles",
                "chart_required",
                "chart_responsive",
                "chart_maintain_aspect_ratio",
                "button_action_required",
                "button_action_unique",
            }
            for key in bool_keys:
                if key in frontend:
                    _validate_bool(frontend.get(key), f"constraints.frontend.{key}", issues)
            if "nav_gradient_max_colors" in frontend:
                _validate_int_range(frontend.get("nav_gradient_max_colors"), "constraints.frontend.nav_gradient_max_colors", 1, 5, issues)
            if "chart_aspect_ratio" in frontend:
                _validate_str(frontend.get("chart_aspect_ratio"), "constraints.frontend.chart_aspect_ratio", issues)
            if "modal_api_required" in frontend:
                _validate_str(frontend.get("modal_api_required"), "constraints.frontend.modal_api_required", issues)

            policy = frontend.get("external_script_policy")
            if policy is not None:
                if not isinstance(policy, dict):
                    issues.append(_issue("constraints.frontend.external_script_policy", "必须为对象"))
                else:
                    unknown = sorted([str(k) for k in policy.keys() if str(k) not in _OVERRIDE_ALLOWED_EXTERNAL_POLICY_KEYS])
                    if unknown:
                        issues.append(_issue("constraints.frontend.external_script_policy", f"存在未允许键: {','.join(unknown)}"))
                    mode = str(policy.get("mode") or "").strip().lower()
                    if mode and mode not in _OVERRIDE_ALLOWED_EXTERNAL_MODES:
                        issues.append(
                            _issue(
                                "constraints.frontend.external_script_policy.mode",
                                f"非法取值: {mode}",
                            )
                        )
                    if "allowed_domains" in policy:
                        _validate_str_list(
                            policy.get("allowed_domains"),
                            "constraints.frontend.external_script_policy.allowed_domains",
                            issues,
                            max_items=16,
                        )
                    if "vendor_fallback" in policy:
                        fallback = policy.get("vendor_fallback")
                        if not isinstance(fallback, dict):
                            issues.append(_issue("constraints.frontend.external_script_policy.vendor_fallback", "必须为对象"))
                        else:
                            for lib, rel in fallback.items():
                                lib_name = str(lib or "").strip().lower()
                                path = _normalize_relative_path(rel)
                                if not lib_name:
                                    issues.append(_issue("constraints.frontend.external_script_policy.vendor_fallback", "库名不能为空"))
                                if not path:
                                    issues.append(
                                        _issue(
                                            f"constraints.frontend.external_script_policy.vendor_fallback.{lib_name or '_'}",
                                            "路径不能为空",
                                        )
                                    )

    return {"passed": len(issues) == 0, "issues": issues}


def _load_runtime_skill_override(project_dir: Path) -> Tuple[Path, Dict[str, Any]]:
    path = Path(project_dir) / "runtime_skill_override.json"
    payload = _load_json(path)
    if not isinstance(payload, dict):
        payload = {}
    return path, payload


def _apply_runtime_override(payload: Dict[str, Any], project_dir: Path) -> Dict[str, Any]:
    result = dict(payload or {})
    override_path, override = _load_runtime_skill_override(project_dir)
    if not override:
        result["override_applied"] = {
            "applied": False,
            "path": str(override_path),
            "blocked": False,
            "validation_issues": [],
        }
        return result

    validation_result = validate_runtime_skill_override(override)
    if not bool(validation_result.get("passed")):
        issues = [str(x) for x in (validation_result.get("issues") or []) if str(x).strip()]
        merged_validation = dict(result.get("validation") or {})
        existing_issues = [str(x) for x in (merged_validation.get("issues") or []) if str(x).strip()]
        merged_validation["issues"] = existing_issues + [f"runtime_skill_override 非法: {item}" for item in issues]
        merged_validation["passed"] = False
        result["validation"] = merged_validation
        result["override_applied"] = {
            "applied": False,
            "path": str(override_path),
            "blocked": True,
            "validation_issues": issues,
            "constraint_keys": [],
            "metadata": {},
        }
        return result

    constraints = result.get("constraints") or {}
    if not isinstance(constraints, dict):
        constraints = {}
    override_constraints = override.get("constraints") if isinstance(override.get("constraints"), dict) else {}

    merged_constraints = _deep_merge_dict(constraints, override_constraints or {})
    merged_constraints["frontend"] = _normalize_frontend_constraints(merged_constraints.get("frontend") or {})
    result["constraints"] = merged_constraints
    result["constraints_checksum"] = _calc_constraints_checksum(merged_constraints)

    warnings = list(((result.get("validation") or {}).get("warnings") or []))
    if override_constraints:
        warnings.append("已应用项目级 runtime_skill_override 约束")
    result["validation"] = {
        **(result.get("validation") or {}),
        "warnings": warnings,
    }
    result["override_applied"] = {
        "applied": bool(override_constraints),
        "path": str(override_path),
        "blocked": False,
        "validation_issues": [],
        "constraint_keys": sorted([str(k) for k in (override_constraints or {}).keys()]),
        "metadata": override.get("meta") if isinstance(override.get("meta"), dict) else (override.get("metadata") or {}),
    }
    return result


def select_runtime_skillpack(
    project_name: str,
    plan: Optional[Dict[str, Any]] = None,
    preferred_id: str = "",
) -> Dict[str, Any]:
    packs = load_runtime_skillpacks()
    plan = plan or {}
    pages = plan.get("pages") or {}
    page_texts = []
    if isinstance(pages, dict):
        for _, page in pages.items():
            if isinstance(page, dict):
                page_texts.append(str(page.get("page_title") or ""))
                page_texts.append(str(page.get("page_description") or ""))
    tokens = _safe_text_tokens([project_name, *page_texts])

    preferred = str(preferred_id or "").strip()
    if preferred:
        for pack in packs:
            if str(pack.get("id") or "").strip() == preferred:
                return pack

    scored = []
    for pack in packs:
        scored.append((_calc_pack_match_score(pack, tokens), pack))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else dict(DEFAULT_RUNTIME_SKILLPACK)


def compile_runtime_skill_plan(
    project_name: str,
    plan: Optional[Dict[str, Any]],
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = settings or {}
    preferred_pack_id = str(settings.get("runtime_skillpack_id") or "").strip()
    selected_pack = select_runtime_skillpack(
        project_name=project_name,
        plan=plan or {},
        preferred_id=preferred_pack_id,
    )
    validation = selected_pack.get("validation") or {}
    plan_dict = plan or {}
    pages = plan_dict.get("pages") or {}
    page_count = len(pages) if isinstance(pages, dict) else 0

    tokens = _safe_text_tokens(
        [
            project_name,
            " ".join(
                [
                    str((v or {}).get("page_title") or "")
                    for v in (pages.values() if isinstance(pages, dict) else [])
                    if isinstance(v, dict)
                ]
            ),
        ]
    )
    domain_override = _pick_domain_override(selected_pack, tokens)
    merged_constraints = _deep_merge_dict(
        selected_pack.get("constraints") or {},
        domain_override.get("constraints") or {},
    )
    if domain_override.get("required_pages"):
        merged_constraints["required_pages"] = list(domain_override.get("required_pages") or [])
    if domain_override.get("required_block_types"):
        merged_constraints["required_block_types"] = list(domain_override.get("required_block_types") or [])
    if domain_override.get("chart_types"):
        merged_constraints["preferred_chart_types"] = list(domain_override.get("chart_types") or [])
    merged_constraints["frontend"] = _normalize_frontend_constraints(merged_constraints.get("frontend") or {})

    checksum_src = json.dumps(merged_constraints, ensure_ascii=False, sort_keys=True)
    constraints_checksum = hashlib.sha256(checksum_src.encode("utf-8")).hexdigest()[:16]

    issues: List[str] = []
    warnings: List[str] = []
    if not bool(validation.get("passed")):
        issues.extend([str(x) for x in (validation.get("issues") or []) if str(x).strip()])
    page_catalog = merged_constraints.get("page_catalog") or {}
    min_pages = int(page_catalog.get("page_count_min") or 6)
    max_pages = int(page_catalog.get("page_count_max") or 8)
    if page_count > 0 and page_count < min_pages:
        warnings.append(f"页面数量不足（{page_count} < {min_pages}）")
    if page_count > max_pages:
        warnings.append(f"页面数量超限（{page_count} > {max_pages}）")

    orchestration = selected_pack.get("orchestration") or {}
    if not orchestration.get("trigger_order"):
        issues.append("缺少触发顺序规则")
    if not orchestration.get("conflict_priority"):
        issues.append("缺少冲突优先级规则")

    return {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "skillpack": {
            "id": str(selected_pack.get("id") or ""),
            "version": str(selected_pack.get("version") or ""),
            "source_path": str(selected_pack.get("source_path") or ""),
            "description": str(selected_pack.get("description") or ""),
        },
        "orchestration": {
            "trigger_order": list(orchestration.get("trigger_order") or []),
            "conflict_priority": list(orchestration.get("conflict_priority") or []),
            "degrade_path": list(orchestration.get("degrade_path") or []),
            "stages": list(selected_pack.get("stages") or []),
        },
        "domain_match": {
            "domain": str(domain_override.get("domain") or "generic"),
            "keywords": [str(x) for x in (domain_override.get("keywords") or []) if str(x).strip()],
        },
        "constraints_checksum": constraints_checksum,
        "constraints": merged_constraints,
        "validation": {
            "passed": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
        },
    }


def build_runtime_skill_plan(
    project_name: str,
    plan: Optional[Dict[str, Any]],
    settings: Optional[Dict[str, Any]],
    project_dir: Path,
) -> Dict[str, Any]:
    payload = compile_runtime_skill_plan(project_name=project_name, plan=plan or {}, settings=settings or {})
    payload = _apply_runtime_override(payload, project_dir=Path(project_dir))
    path = Path(project_dir) / "runtime_skill_plan.json"
    _save_json(path, payload)
    return {
        "path": path,
        "payload": payload,
    }
