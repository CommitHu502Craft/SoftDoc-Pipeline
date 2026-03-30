"""
跨项目语义同质化闸门（业务语义层）。

用途：
1) 在规格阶段对实体/流程/API 语义做跨项目相似度检测。
2) 相似度过高时执行“可控重写”（不改业务边界，只拉开语义指纹）。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _slugify(text: str, fallback: str = "proj") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(text or "").strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if slug:
        return slug[:20]
    # 中文名回退：取哈希前缀，避免空 slug
    digest = hashlib.sha1(str(text or fallback).encode("utf-8")).hexdigest()[:8]
    return f"{fallback}_{digest}"


def _extract_tokens(spec: Dict[str, Any]) -> Dict[str, List[str]]:
    entity_tokens: List[str] = []
    flow_tokens: List[str] = []
    api_tokens: List[str] = []

    for item in spec.get("entities") or []:
        name = str((item or {}).get("name") or "").strip().lower()
        if name:
            entity_tokens.append(name)

    for flow in spec.get("state_machines") or []:
        flow_name = str((flow or {}).get("name") or "").strip().lower()
        if flow_name:
            flow_tokens.append(flow_name)
        for state in (flow or {}).get("states") or []:
            label = str((state or {}).get("label") or "").strip().lower()
            if label:
                flow_tokens.append(label)

    for api in spec.get("api_contracts") or []:
        method = str((api or {}).get("http_method") or "").strip().upper()
        path = str((api or {}).get("path") or "").strip().lower()
        desc = str((api or {}).get("description") or "").strip().lower()
        method_name = str((api or {}).get("method_name") or "").strip().lower()
        if method and path:
            api_tokens.append(f"{method}:{path}")
        if desc:
            api_tokens.append(desc)
        if method_name:
            api_tokens.append(method_name)

    return {
        "entities": sorted(set(entity_tokens)),
        "flows": sorted(set(flow_tokens)),
        "apis": sorted(set(api_tokens)),
    }


def _jaccard(a: List[str], b: List[str]) -> float:
    sa = set([x for x in a if x])
    sb = set([x for x in b if x])
    if not sa and not sb:
        return 0.0
    return float(len(sa & sb)) / float(max(1, len(sa | sb)))


def _score_similarity(current_tokens: Dict[str, List[str]], other_tokens: Dict[str, List[str]]) -> Dict[str, float]:
    entity_sim = _jaccard(current_tokens.get("entities", []), other_tokens.get("entities", []))
    flow_sim = _jaccard(current_tokens.get("flows", []), other_tokens.get("flows", []))
    api_sim = _jaccard(current_tokens.get("apis", []), other_tokens.get("apis", []))
    weighted = round(entity_sim * 0.35 + flow_sim * 0.35 + api_sim * 0.30, 4)
    return {
        "weighted_similarity": weighted,
        "entity_similarity": round(entity_sim, 4),
        "flow_similarity": round(flow_sim, 4),
        "api_similarity": round(api_sim, 4),
    }


def _collect_other_specs(output_root: Path, project_name: str, sample_limit: int = 120) -> List[Tuple[str, Dict[str, Any]]]:
    specs: List[Tuple[str, Dict[str, Any]]] = []
    if not output_root.exists():
        return specs
    for spec_path in list(output_root.glob("*/project_executable_spec.json"))[:sample_limit]:
        candidate_name = spec_path.parent.name
        if candidate_name == project_name:
            continue
        data = _load_json(spec_path)
        if data:
            specs.append((candidate_name, data))
    return specs


def evaluate_semantic_homogeneity(
    project_name: str,
    project_dir: Path,
    output_root: Optional[Path] = None,
    threshold: float = 0.82,
) -> Dict[str, Any]:
    project_dir = Path(project_dir)
    output_root = Path(output_root) if output_root else project_dir.parent
    spec = _load_json(project_dir / "project_executable_spec.json")
    tokens = _extract_tokens(spec)

    comparisons: List[Dict[str, Any]] = []
    for other_name, other_spec in _collect_other_specs(output_root, project_name):
        sim = _score_similarity(tokens, _extract_tokens(other_spec))
        comparisons.append(
            {
                "project_name": other_name,
                **sim,
            }
        )

    comparisons.sort(key=lambda x: float(x.get("weighted_similarity", 0.0)), reverse=True)
    top = comparisons[:10]
    top_score = float(top[0]["weighted_similarity"]) if top else 0.0
    should_rewrite = top_score >= float(threshold)

    report = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "threshold": float(threshold),
        "top_similarity": round(top_score, 4),
        "should_rewrite": should_rewrite,
        "comparison_count": len(comparisons),
        "top_matches": top,
        "token_stats": {
            "entity_count": len(tokens.get("entities") or []),
            "flow_count": len(tokens.get("flows") or []),
            "api_count": len(tokens.get("apis") or []),
        },
    }
    return report


def _rewrite_spec_semantics(spec: Dict[str, Any], project_name: str) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, str]]:
    rewritten = copy.deepcopy(spec or {})
    signature = _slugify(project_name, fallback="proj")
    entity_name_map: Dict[str, str] = {}
    api_id_map: Dict[str, str] = {}

    for entity in rewritten.get("entities") or []:
        old_name = str((entity or {}).get("name") or "").strip()
        if not old_name:
            continue
        new_name = old_name if old_name.lower().startswith(signature) else f"{signature}_{old_name}"
        entity["name"] = new_name
        entity_name_map[old_name] = new_name

    for machine in rewritten.get("state_machines") or []:
        old_name = str((machine or {}).get("name") or "").strip()
        if old_name and signature not in old_name.lower():
            machine["name"] = f"{old_name}_{signature}"

    for api in rewritten.get("api_contracts") or []:
        old_api_id = str((api or {}).get("id") or "").strip()
        old_path = str((api or {}).get("path") or "").strip()
        old_method_name = str((api or {}).get("method_name") or "").strip()

        normalized_path = old_path if old_path.startswith("/") else f"/{old_path}"
        if not normalized_path.startswith(f"/api/{signature}/"):
            if normalized_path.startswith("/api/"):
                normalized_path = f"/api/{signature}/{normalized_path[5:].lstrip('/')}"
            else:
                normalized_path = f"/api/{signature}/{normalized_path.lstrip('/')}"
        api["path"] = re.sub(r"/{2,}", "/", normalized_path)

        if old_method_name and not old_method_name.lower().startswith(signature):
            api["method_name"] = f"{signature}_{old_method_name}"

        if old_api_id:
            new_api_id = old_api_id if old_api_id.endswith(f"_{signature}") else f"{old_api_id}_{signature}"
            api["id"] = new_api_id
            api_id_map[old_api_id] = new_api_id

    for mapping in rewritten.get("page_api_mapping") or []:
        api_ids = mapping.get("api_ids") or []
        mapping["api_ids"] = [api_id_map.get(str(api_id), str(api_id)) for api_id in api_ids]

    rewritten["semantic_signature"] = signature
    rewritten["semantic_rewrite_note"] = "auto_rewrite_for_homogeneity_gate"
    return rewritten, entity_name_map, api_id_map


def _sync_plan_after_spec_rewrite(project_dir: Path, rewritten_spec: Dict[str, Any], entity_map: Dict[str, str]) -> None:
    plan_path = project_dir / "project_plan.json"
    plan = _load_json(plan_path)
    if not plan:
        return

    plan["executable_spec"] = rewritten_spec

    entities = ((plan.get("code_blueprint") or {}).get("entities") or [])
    if isinstance(entities, list) and entities:
        updated_entities = [entity_map.get(str(item), str(item)) for item in entities]
        plan.setdefault("code_blueprint", {})["entities"] = updated_entities

    _save_json(plan_path, plan)


def apply_semantic_homogeneity_gate(
    project_name: str,
    project_dir: Path,
    output_root: Optional[Path] = None,
    threshold: float = 0.82,
    auto_rewrite: bool = True,
) -> Dict[str, Any]:
    """
    执行同质化评估与必要重写；返回报告并落盘。
    """
    project_dir = Path(project_dir)
    report = evaluate_semantic_homogeneity(
        project_name=project_name,
        project_dir=project_dir,
        output_root=output_root,
        threshold=threshold,
    )

    rewritten = False
    if auto_rewrite and report.get("should_rewrite"):
        current_spec = _load_json(project_dir / "project_executable_spec.json")
        if current_spec:
            rewritten_spec, entity_map, _api_map = _rewrite_spec_semantics(current_spec, project_name=project_name)
            _save_json(project_dir / "project_executable_spec.json", rewritten_spec)
            _sync_plan_after_spec_rewrite(project_dir, rewritten_spec, entity_map)
            rewritten = True

    report["auto_rewrite_enabled"] = bool(auto_rewrite)
    report["rewritten"] = bool(rewritten)
    report_path = project_dir / "semantic_homogeneity_report.json"
    _save_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def run_semantic_homogeneity_closed_loop(
    project_name: str,
    project_dir: Path,
    output_root: Optional[Path] = None,
    threshold: float = 0.82,
    max_rounds: int = 2,
    post_rewrite_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    执行“同质化检测 -> 语义重写 -> 外部重跑回调 -> 复检”的闭环。
    """
    rounds: List[Dict[str, Any]] = []
    project_dir = Path(project_dir)
    output_root = Path(output_root) if output_root else project_dir.parent
    max_rounds = max(1, int(max_rounds))
    stabilized = False

    for idx in range(1, max_rounds + 1):
        current = apply_semantic_homogeneity_gate(
            project_name=project_name,
            project_dir=project_dir,
            output_root=output_root,
            threshold=threshold,
            auto_rewrite=True,
        )
        round_item: Dict[str, Any] = {
            "round": idx,
            "top_similarity": float(current.get("top_similarity") or 0.0),
            "should_rewrite": bool(current.get("should_rewrite")),
            "rewritten": bool(current.get("rewritten")),
            "report_path": current.get("report_path"),
        }

        callback_result: Dict[str, Any] = {}
        if round_item["rewritten"] and callable(post_rewrite_callback):
            try:
                cb = post_rewrite_callback(round_idx=idx, gate_report=current)
                callback_result = cb if isinstance(cb, dict) else {"result": cb}
            except Exception as e:
                callback_result = {"error": str(e)}
        round_item["post_rewrite"] = callback_result

        follow_up = evaluate_semantic_homogeneity(
            project_name=project_name,
            project_dir=project_dir,
            output_root=output_root,
            threshold=threshold,
        )
        round_item["post_check_top_similarity"] = float(follow_up.get("top_similarity") or 0.0)
        round_item["post_check_should_rewrite"] = bool(follow_up.get("should_rewrite"))
        rounds.append(round_item)

        if not round_item["post_check_should_rewrite"]:
            stabilized = True
            break

        if not round_item["rewritten"]:
            # 检测需重写但未重写时，继续迭代通常无意义，直接退出。
            break

    final_eval = evaluate_semantic_homogeneity(
        project_name=project_name,
        project_dir=project_dir,
        output_root=output_root,
        threshold=threshold,
    )
    result = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "threshold": float(threshold),
        "max_rounds": int(max_rounds),
        "rounds": rounds,
        "stabilized": bool(stabilized),
        "final_top_similarity": float(final_eval.get("top_similarity") or 0.0),
        "final_should_rewrite": bool(final_eval.get("should_rewrite")),
        "passed": not bool(final_eval.get("should_rewrite")),
    }
    output_path = project_dir / "semantic_homogeneity_closed_loop_report.json"
    _save_json(output_path, result)
    result["report_path"] = str(output_path)
    return result
