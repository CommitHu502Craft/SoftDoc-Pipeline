"""
项目章程（Project Charter）模型与校验工具。

目标：
1) 在生成前强制具备业务上下文，避免“仅项目名驱动”的弱语义输入。
2) 对章程字段做结构化校验，确保后续规格与代码阶段有稳定输入。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


REQUIRED_CHARTER_FIELDS = {
    "business_scope": "业务边界",
    "user_roles": "用户角色",
    "core_flows": "核心流程",
    "non_functional_constraints": "非功能约束",
    "acceptance_criteria": "验收标准",
    "software_full_name": "软件全称",
    "software_short_name": "软件简称",
}


def default_project_charter_template(project_name: str) -> Dict[str, Any]:
    """提供默认章程模板，便于 GUI/API/CLI 引导用户补全。"""
    project_name = _normalize_text(project_name) or "未命名项目"
    default_full_name = _normalize_software_full_name("", project_name)
    default_short_name = _normalize_software_short_name("", default_full_name)
    return {
        "project_name": project_name,
        "software_full_name": default_full_name,
        "software_short_name": default_short_name,
        "term_dictionary": {
            "software_full_name": default_full_name,
            "software_short_name": default_short_name,
            "core_domain_object": "业务记录",
            "primary_operator": "业务操作员",
        },
        "business_scope": "",
        "user_roles": [
            {"name": "系统管理员", "responsibility": ""},
            {"name": "业务操作员", "responsibility": ""},
        ],
        "core_flows": [
            {
                "name": "主业务流程",
                "steps": ["录入业务数据", "校验并提交", "结果查询与导出"],
                "success_criteria": "",
            }
        ],
        "non_functional_constraints": [
            "页面响应时间不超过2秒",
            "关键操作全量审计",
        ],
        "acceptance_criteria": [
            "可完成主业务流程端到端操作",
            "核心数据可追溯、可导出",
        ],
    }


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_software_full_name(value: Any, project_name: str) -> str:
    text = _normalize_text(value) or _normalize_text(project_name) or "未命名软件"
    if not text:
        text = "未命名软件"
    suffixes = ("软件", "系统", "平台")
    if not text.endswith(suffixes):
        text = f"{text}软件"
    return text


def _normalize_software_short_name(value: Any, software_full_name: str) -> str:
    text = _normalize_text(value)
    if text:
        return text
    full_name = _normalize_text(software_full_name)
    for suffix in ("软件", "系统", "平台"):
        if full_name.endswith(suffix):
            trimmed = full_name[: -len(suffix)].strip()
            if trimmed:
                return trimmed
    return full_name or "未命名"


def _normalize_term_dictionary(value: Any, software_full_name: str, software_short_name: str) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            key = _normalize_text(k)
            val = _normalize_text(v)
            if key and val:
                normalized[key] = val
    normalized.setdefault("software_full_name", software_full_name)
    normalized.setdefault("software_short_name", software_short_name)
    return normalized


def _hydrate_with_template(charter: Dict[str, Any], project_name: str) -> Dict[str, Any]:
    """
    用模板补齐章程缺口，确保 AI 草案在结构不完整时也可被快速确认。
    """
    template = normalize_project_charter(default_project_charter_template(project_name), project_name=project_name)
    normalized = normalize_project_charter(charter, project_name=project_name)

    if not normalized.get("business_scope"):
        normalized["business_scope"] = (
            template["business_scope"]
            or f"{project_name} 围绕核心业务数据的录入、审核、查询与导出，不扩展到无关领域。"
        )

    roles = normalized.get("user_roles") or []
    if len(roles) < 2:
        normalized["user_roles"] = template["user_roles"]

    flows = normalized.get("core_flows") or []
    valid_flow_count = 0
    for flow in flows:
        steps = [s for s in (flow.get("steps") or []) if _normalize_text(s)]
        if _normalize_text(flow.get("name")) and len(steps) >= 2:
            valid_flow_count += 1
    if valid_flow_count < 1:
        normalized["core_flows"] = template["core_flows"]

    if not (normalized.get("non_functional_constraints") or []):
        normalized["non_functional_constraints"] = template["non_functional_constraints"]

    if not (normalized.get("acceptance_criteria") or []):
        normalized["acceptance_criteria"] = template["acceptance_criteria"]

    return normalize_project_charter(normalized, project_name=project_name)


def _normalize_list_of_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_user_roles(value: Any) -> List[Dict[str, str]]:
    roles: List[Dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = _normalize_text(item.get("name"))
                responsibility = _normalize_text(item.get("responsibility"))
                if name:
                    roles.append({"name": name, "responsibility": responsibility})
            else:
                name = _normalize_text(item)
                if name:
                    roles.append({"name": name, "responsibility": ""})
    elif isinstance(value, str) and value.strip():
        roles.append({"name": value.strip(), "responsibility": ""})
    return roles


def _normalize_core_flows(value: Any) -> List[Dict[str, Any]]:
    flows: List[Dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = _normalize_text(item.get("name"))
                steps = _normalize_list_of_strings(item.get("steps"))
                success_criteria = _normalize_text(item.get("success_criteria"))
                if name:
                    flows.append(
                        {
                            "name": name,
                            "steps": steps,
                            "success_criteria": success_criteria,
                        }
                    )
            else:
                text = _normalize_text(item)
                if text:
                    flows.append({"name": text, "steps": [], "success_criteria": ""})
    elif isinstance(value, str) and value.strip():
        flows.append({"name": value.strip(), "steps": [], "success_criteria": ""})
    return flows


def normalize_project_charter(raw: Optional[Dict[str, Any]], project_name: str = "") -> Dict[str, Any]:
    """对章程进行归一化，保证结构稳定。"""
    data = dict(raw or {})
    resolved_project_name = _normalize_text(data.get("project_name") or project_name)
    software_full_name = _normalize_software_full_name(data.get("software_full_name"), resolved_project_name)
    software_short_name = _normalize_software_short_name(data.get("software_short_name"), software_full_name)
    normalized = {
        "project_name": resolved_project_name,
        "software_full_name": software_full_name,
        "software_short_name": software_short_name,
        "term_dictionary": _normalize_term_dictionary(data.get("term_dictionary"), software_full_name, software_short_name),
        "business_scope": _normalize_text(data.get("business_scope")),
        "user_roles": _normalize_user_roles(data.get("user_roles")),
        "core_flows": _normalize_core_flows(data.get("core_flows")),
        "non_functional_constraints": _normalize_list_of_strings(data.get("non_functional_constraints")),
        "acceptance_criteria": _normalize_list_of_strings(data.get("acceptance_criteria")),
    }
    return normalized


def validate_project_charter(charter: Dict[str, Any]) -> List[str]:
    """返回章程错误列表；空列表表示通过。"""
    # 兼容旧输入：先归一化，确保 software_full_name/software_short_name/
    # term_dictionary 等新增字段可由事实源自动补齐。
    raw_charter = charter if isinstance(charter, dict) else {}
    charter = normalize_project_charter(raw_charter, project_name=str(raw_charter.get("project_name") or ""))
    errors: List[str] = []
    software_full_name = _normalize_text(charter.get("software_full_name"))
    software_short_name = _normalize_text(charter.get("software_short_name"))

    if not software_full_name:
        errors.append("缺少软件全称（software_full_name）")
    elif not software_full_name.endswith(("软件", "系统", "平台")):
        errors.append("软件全称需以“软件/系统/平台”结尾")
    if not software_short_name:
        errors.append("缺少软件简称（software_short_name）")

    term_dictionary = charter.get("term_dictionary") or {}
    if not isinstance(term_dictionary, dict):
        errors.append("术语字典（term_dictionary）必须为对象")
    else:
        if not _normalize_text(term_dictionary.get("software_full_name")):
            errors.append("term_dictionary 缺少 software_full_name")
        if not _normalize_text(term_dictionary.get("software_short_name")):
            errors.append("term_dictionary 缺少 software_short_name")

    if not _normalize_text(charter.get("business_scope")):
        errors.append("缺少业务边界（business_scope）")

    roles = charter.get("user_roles") or []
    if not isinstance(roles, list) or len(roles) < 2:
        errors.append("用户角色（user_roles）至少需要2个角色")
    else:
        for idx, role in enumerate(roles, 1):
            if not _normalize_text((role or {}).get("name")):
                errors.append(f"user_roles 第{idx}项缺少角色名")

    flows = charter.get("core_flows") or []
    if not isinstance(flows, list) or len(flows) < 1:
        errors.append("核心流程（core_flows）至少需要1条流程")
    else:
        for idx, flow in enumerate(flows, 1):
            if not _normalize_text((flow or {}).get("name")):
                errors.append(f"core_flows 第{idx}项缺少流程名称")
            steps = flow.get("steps") if isinstance(flow, dict) else None
            if not isinstance(steps, list) or len([s for s in steps if _normalize_text(s)]) < 2:
                errors.append(f"core_flows 第{idx}项至少需要2个步骤")

    nfr = charter.get("non_functional_constraints") or []
    if not isinstance(nfr, list) or len(nfr) < 1:
        errors.append("非功能约束（non_functional_constraints）至少需要1条")

    ac = charter.get("acceptance_criteria") or []
    if not isinstance(ac, list) or len(ac) < 1:
        errors.append("验收标准（acceptance_criteria）至少需要1条")

    return errors


def summarize_project_charter(charter: Dict[str, Any]) -> Dict[str, Any]:
    """章程简要摘要，便于 API/GUI 列表展示。"""
    roles = charter.get("user_roles") or []
    flows = charter.get("core_flows") or []
    return {
        "software_full_name": _normalize_text(charter.get("software_full_name")),
        "software_short_name": _normalize_text(charter.get("software_short_name")),
        "business_scope": _normalize_text(charter.get("business_scope")),
        "role_count": len(roles),
        "flow_count": len(flows),
        "nfr_count": len(charter.get("non_functional_constraints") or []),
        "acceptance_count": len(charter.get("acceptance_criteria") or []),
    }


def build_charter_prompt_context(charter: Dict[str, Any]) -> str:
    """将结构化章程转换为可嵌入 Prompt 的约束块。"""
    if not charter:
        return ""

    roles = "\n".join(
        f"- {r.get('name', '').strip()}: {r.get('responsibility', '').strip()}"
        for r in (charter.get("user_roles") or [])
        if str(r.get("name", "")).strip()
    )
    flows = "\n".join(
        f"- {f.get('name', '').strip()} | 步骤: {' -> '.join(f.get('steps') or [])}"
        for f in (charter.get("core_flows") or [])
        if str(f.get("name", "")).strip()
    )
    nfr = "\n".join(f"- {x}" for x in (charter.get("non_functional_constraints") or []))
    ac = "\n".join(f"- {x}" for x in (charter.get("acceptance_criteria") or []))
    scope = _normalize_text(charter.get("business_scope"))
    full_name = _normalize_text(charter.get("software_full_name"))
    short_name = _normalize_text(charter.get("software_short_name"))
    terms = charter.get("term_dictionary") or {}
    terms_lines = "\n".join(
        f"- {k}: {v}"
        for k, v in terms.items()
        if _normalize_text(k) and _normalize_text(v)
    )

    return f"""# 项目章程（必须严格遵循）
## 软件标识
- 全称: {full_name or "（未定义）"}
- 简称: {short_name or "（未定义）"}

## 业务边界
{scope}

## 角色与职责
{roles or "- （无）"}

## 核心流程
{flows or "- （无）"}

## 非功能约束
{nfr or "- （无）"}

## 验收标准
{ac or "- （无）"}

## 术语字典
{terms_lines or "- （无）"}
"""


def resolve_software_identity(charter: Optional[Dict[str, Any]], fallback_project_name: str = "") -> Dict[str, Any]:
    """返回统一的软件命名事实源。"""
    normalized = normalize_project_charter(charter or {}, project_name=fallback_project_name)
    full_name = _normalize_software_full_name(
        normalized.get("software_full_name"),
        normalized.get("project_name") or fallback_project_name,
    )
    short_name = _normalize_software_short_name(normalized.get("software_short_name"), full_name)
    terms = _normalize_term_dictionary(normalized.get("term_dictionary"), full_name, short_name)
    return {
        "project_name": _normalize_text(normalized.get("project_name") or fallback_project_name),
        "software_full_name": full_name,
        "software_short_name": short_name,
        "term_dictionary": terms,
    }


def draft_project_charter_with_ai(
    project_name: str,
    context_hint: str = "",
    client: Any = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    使用 AI 草拟项目章程；失败时自动回退模板。
    """
    prompt = f"""请为项目《{project_name}》生成一份项目章程草案，输出纯 JSON：
{{
  "project_name": "{project_name}",
  "business_scope": "...",
  "user_roles": [{{"name":"...", "responsibility":"..."}}, ...],
  "core_flows": [{{"name":"...", "steps":["...","..."], "success_criteria":"..."}}, ...],
  "non_functional_constraints": ["...", "..."],
  "acceptance_criteria": ["...", "..."]
}}

约束：
1. user_roles 至少 2 个角色，角色职责要具体。
2. core_flows 至少 1 条，每条至少 2 个步骤，步骤必须是可执行动作。
3. non_functional_constraints 至少 1 条，acceptance_criteria 至少 1 条。
4. 不要输出 markdown，不要额外解释文字。
5. 业务必须围绕项目名，不得扩展到无关行业。

补充上下文（可选）：
{context_hint or "无"}
"""

    drafted: Dict[str, Any]
    try:
        if client is None:
            from core.deepseek_client import DeepSeekClient

            client = DeepSeekClient()
        drafted = client.generate_json(prompt, max_retries=max_retries)
    except Exception:
        drafted = default_project_charter_template(project_name)

    normalized = _hydrate_with_template(drafted, project_name=project_name)
    return normalized


def project_charter_path(project_dir: Path) -> Path:
    return project_dir / "project_charter.json"


def load_project_charter(project_dir: Path) -> Optional[Dict[str, Any]]:
    path = project_charter_path(project_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return normalize_project_charter(data)
    except Exception:
        return None


def save_project_charter(project_dir: Path, charter: Dict[str, Any]) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_charter_path(project_dir)
    normalized = normalize_project_charter(charter or {}, project_name=project_dir.name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    return path
