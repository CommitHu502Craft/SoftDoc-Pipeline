"""
可执行规格（Executable Spec）构建器。

目标：
1) 在代码生成前产出结构化规格，作为实现阶段事实来源。
2) 将“随机差异”限制在实现细节，不污染业务事实层。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modules.project_charter import resolve_software_identity


def _slugify(text: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(text or ""))
    while "__" in raw:
        raw = raw.replace("__", "_")
    return raw.strip("_") or "item"


def _derive_entities(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    blueprint = plan.get("code_blueprint") or {}
    entities = blueprint.get("entities") or []
    if isinstance(entities, list) and entities:
        return [{"name": str(e), "source": "plan.code_blueprint"} for e in entities if str(e).strip()]

    # 回退：根据菜单标题推断实体
    derived: List[Dict[str, Any]] = []
    for menu in plan.get("menu_list", []) or []:
        title = str(menu.get("title", "")).strip()
        if not title:
            continue
        derived.append({"name": title.replace("管理", "").replace("中心", "") or title, "source": "menu_title"})
    return derived[:8]


def _derive_api_contracts(plan: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    blueprint = plan.get("code_blueprint") or {}
    controllers = blueprint.get("controllers") or []
    contracts: List[Dict[str, Any]] = []
    page_api_map: Dict[str, List[str]] = {}

    for ctrl in controllers:
        ctrl_name = str((ctrl or {}).get("name") or "UnknownController")
        page_id = str((ctrl or {}).get("page_id") or "")
        methods = (ctrl or {}).get("methods") or []
        for method in methods:
            name = str((method or {}).get("name") or "unknown")
            desc = str((method or {}).get("desc") or "")
            http = str((method or {}).get("http") or "POST /api/undefined")
            parts = http.split(maxsplit=1)
            if len(parts) == 2:
                verb, path = parts[0].upper(), parts[1]
            else:
                verb, path = "POST", f"/api/{_slugify(name)}"
            api_id = f"api_{_slugify(ctrl_name)}_{_slugify(name)}"
            contracts.append(
                {
                    "id": api_id,
                    "controller": ctrl_name,
                    "method_name": name,
                    "http_method": verb,
                    "path": path,
                    "description": desc,
                    "page_id": page_id,
                }
            )
            if page_id:
                page_api_map.setdefault(page_id, []).append(api_id)

    # 若控制器为空，按页面生成最小 API 合约
    if not contracts:
        for menu in plan.get("menu_list", []) or []:
            page_id = str(menu.get("page_id") or "")
            if not page_id:
                continue
            api_id = f"api_{_slugify(page_id)}_query"
            contracts.append(
                {
                    "id": api_id,
                    "controller": f"{_slugify(page_id)}_controller",
                    "method_name": "query",
                    "http_method": "GET",
                    "path": f"/api/{_slugify(page_id)}/query",
                    "description": f"{menu.get('title', page_id)}查询",
                    "page_id": page_id,
                }
            )
            page_api_map.setdefault(page_id, []).append(api_id)

    return contracts, page_api_map


def _derive_state_machines(charter: Dict[str, Any]) -> List[Dict[str, Any]]:
    machines: List[Dict[str, Any]] = []
    for flow in charter.get("core_flows") or []:
        name = str((flow or {}).get("name") or "").strip()
        steps = [str(s).strip() for s in ((flow or {}).get("steps") or []) if str(s).strip()]
        if not name or not steps:
            continue
        states = []
        for idx, step in enumerate(steps):
            state_id = f"s{idx+1}_{_slugify(step)}"
            states.append({"id": state_id, "label": step})
        transitions = []
        for i in range(len(states) - 1):
            transitions.append({"from": states[i]["id"], "to": states[i + 1]["id"]})
        machines.append(
            {
                "name": name,
                "states": states,
                "transitions": transitions,
                "success_criteria": str((flow or {}).get("success_criteria") or "").strip(),
            }
        )
    return machines


def _derive_permission_matrix(charter: Dict[str, Any], page_ids: List[str]) -> List[Dict[str, Any]]:
    matrix: List[Dict[str, Any]] = []
    roles = charter.get("user_roles") or []
    for role in roles:
        role_name = str((role or {}).get("name") or "").strip()
        if not role_name:
            continue
        role_key = role_name.lower()
        if "管理员" in role_name or "admin" in role_key:
            actions = ["view", "query", "create", "update", "export", "audit"]
        elif "经理" in role_name or "leader" in role_key:
            actions = ["view", "query", "approve", "export"]
        else:
            actions = ["view", "query", "create"]
        matrix.append(
            {
                "role": role_name,
                "responsibility": str((role or {}).get("responsibility") or "").strip(),
                "grants": [{"page_id": pid, "actions": actions} for pid in page_ids],
            }
        )
    return matrix


def build_executable_spec(plan: Dict[str, Any], charter: Dict[str, Any]) -> Dict[str, Any]:
    identity = resolve_software_identity(charter, fallback_project_name=str(plan.get("project_name") or ""))
    project_name = str(plan.get("project_name") or identity.get("project_name") or "未命名项目")
    page_ids = [str(m.get("page_id")) for m in (plan.get("menu_list") or []) if str(m.get("page_id", "")).strip()]
    entities = _derive_entities(plan)
    api_contracts, page_api_map = _derive_api_contracts(plan)
    state_machines = _derive_state_machines(charter)
    permission_matrix = _derive_permission_matrix(charter, page_ids)

    charter_digest = hashlib.sha256(
        json.dumps(charter, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    spec = {
        "spec_version": "1.0.0",
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "project_charter + project_plan",
        "charter_digest": charter_digest,
        "software_identity": {
            "software_full_name": identity.get("software_full_name"),
            "software_short_name": identity.get("software_short_name"),
            "term_dictionary": identity.get("term_dictionary") or {},
        },
        "entities": entities,
        "state_machines": state_machines,
        "permission_matrix": permission_matrix,
        "api_contracts": api_contracts,
        "page_api_mapping": [
            {"page_id": pid, "api_ids": sorted(list(set(page_api_map.get(pid, []))))}
            for pid in sorted(set(page_ids))
        ],
    }
    return spec


def validate_executable_spec(spec: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not (spec.get("entities") or []):
        errors.append("规格缺少实体模型（entities）")
    if not (spec.get("api_contracts") or []):
        errors.append("规格缺少API合约（api_contracts）")
    if not (spec.get("permission_matrix") or []):
        errors.append("规格缺少权限矩阵（permission_matrix）")
    if not (spec.get("page_api_mapping") or []):
        errors.append("规格缺少页面-接口映射（page_api_mapping）")
    return errors


def save_executable_spec(project_dir: Path, spec: Dict[str, Any]) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    spec_path = project_dir / "project_executable_spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    return spec_path
