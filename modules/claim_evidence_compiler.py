"""
声称-证据编译器（Claim-Evidence Compiler）。

目标：
1) 将“说明书/流程声称”绑定到可验证证据（代码/API/截图/运行回放）。
2) 输出结构化矩阵，供运行验证、风险门禁、冻结包复用。
"""
from __future__ import annotations

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


def _tokenize(text: str) -> List[str]:
    cleaned = str(text or "").strip().lower()
    if not cleaned:
        return []
    parts = [p for p in re.split(r"[\s,/|，。；;、:：()（）\-_]+", cleaned) if p]
    tokens: List[str] = []
    for p in parts:
        if len(p) >= 2:
            tokens.append(p)
    return sorted(list(set(tokens)), key=len, reverse=True)


def _expand_keywords(raw_keywords: List[str]) -> List[str]:
    expanded: List[str] = []
    for item in raw_keywords:
        text = str(item or "").strip().lower()
        if not text:
            continue
        if len(text) >= 2:
            expanded.append(text)
        expanded.extend(_tokenize(text))

        # 路径/蛇形命名补充拆分，提高“接口路径/方法名 -> 代码”命中率
        if "/" in text:
            for seg in text.split("/"):
                seg = seg.strip()
                if len(seg) >= 2:
                    expanded.append(seg)
        if "_" in text:
            for seg in text.split("_"):
                seg = seg.strip()
                if len(seg) >= 2:
                    expanded.append(seg)
        if "-" in text:
            for seg in text.split("-"):
                seg = seg.strip()
                if len(seg) >= 2:
                    expanded.append(seg)

    return sorted(list(set(expanded)), key=len, reverse=True)


def _collect_structural_code_hits(code_dir: Path, limit: int = 20) -> List[str]:
    """
    当关键词检索无法命中时，回退到结构化代码证据：
    Controller / Service / Routes / Model 文件作为“实现落点”。
    """
    if not code_dir.exists():
        return []

    patterns = [
        "**/*Controller*.php",
        "**/*Service*.php",
        "**/Routes/*.php",
        "**/routes/*.php",
        "**/*Repository*.php",
        "**/*Model*.php",
        "**/Models/*.php",
        "**/api.php",
        "**/*.py",
        "**/*.java",
        "**/*.go",
        "**/*.js",
        "**/*.ts",
    ]

    hits: List[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for path in code_dir.glob(pattern):
            if not path.is_file():
                continue
            rel = str(path.relative_to(code_dir.parent)).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            hits.append(rel)
            if len(hits) >= limit:
                return hits
    return hits


def _collect_code_hits(
    code_dir: Path,
    method_names: List[str],
    api_paths: List[str],
    flow_keywords: Optional[List[str]] = None,
    sample_limit: int = 120,
    allow_structural_fallback: bool = False,
) -> List[str]:
    if not code_dir.exists():
        return []

    keywords = [k for k in method_names if str(k).strip()]
    keywords.extend([k for k in api_paths if str(k).strip()])
    keywords.extend([k for k in (flow_keywords or []) if str(k).strip()])

    lowered_keywords = _expand_keywords([str(k) for k in keywords])
    if not lowered_keywords and not allow_structural_fallback:
        return []

    hits: List[str] = []
    seen: set[str] = set()
    for path in list(code_dir.rglob("*.*"))[:sample_limit]:
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".py", ".java", ".js", ".ts", ".go", ".php", ".kt", ".cs"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        if any(k in content for k in lowered_keywords):
            rel = str(path.relative_to(code_dir.parent)).replace("\\", "/")
            if rel not in seen:
                seen.add(rel)
                hits.append(rel)
            if len(hits) >= 20:
                break

    if not hits and allow_structural_fallback:
        hits = _collect_structural_code_hits(code_dir, limit=20)
    return hits


def _load_ui_blueprint(project_dir: Path) -> Dict[str, Any]:
    payload = _load_json(project_dir / "ui_blueprint.json")
    if not isinstance(payload, dict):
        return {}
    page_map = payload.get("page_map")
    if isinstance(page_map, dict):
        return payload
    pages = payload.get("pages") or []
    if isinstance(pages, list):
        payload["page_map"] = {
            str(item.get("page_id") or "").strip(): item
            for item in pages
            if isinstance(item, dict) and str(item.get("page_id") or "").strip()
        }
    else:
        payload["page_map"] = {}
    return payload


def _load_screenshot_capture_report(project_dir: Path) -> Dict[str, Any]:
    payload = _load_json(project_dir / "screenshot_capture_report.json")
    return payload if isinstance(payload, dict) else {}


def _find_claim_screenshot_refs(
    project_dir: Path,
    page_id: str,
    claim_id: str,
    capture_report: Dict[str, Any],
) -> List[str]:
    refs: List[str] = []
    pages = (capture_report.get("pages") or {}) if isinstance(capture_report, dict) else {}
    page_entry = pages.get(page_id) if isinstance(pages, dict) else {}
    if isinstance(page_entry, dict):
        for item in page_entry.get("claims") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("claim_id") or "").strip() != claim_id:
                continue
            file_name = str(item.get("file") or "").strip()
            if file_name:
                refs.append(f"screenshots/{file_name}")

    # Fallback by filename pattern.
    screenshot_dir = project_dir / "screenshots"
    if screenshot_dir.exists():
        safe_claim = re.sub(r"[^a-zA-Z0-9_\-]", "_", claim_id)
        for path in screenshot_dir.glob(f"*_{page_id}_claim_*{safe_claim}*.png"):
            rel = str(path.relative_to(project_dir)).replace("\\", "/")
            if rel not in refs:
                refs.append(rel)
    return refs


def _build_page_claims(
    project_dir: Path,
    plan: Dict[str, Any],
    spec: Dict[str, Any],
    runtime_report: Dict[str, Any],
    ui_blueprint: Dict[str, Any],
    capture_report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    pages = plan.get("pages") or {}
    menu_title_map = {
        str(item.get("page_id") or ""): str(item.get("title") or "").strip()
        for item in (plan.get("menu_list") or [])
        if str(item.get("page_id") or "").strip()
    }
    mapping_map = {
        str(item.get("page_id") or ""): [str(x) for x in (item.get("api_ids") or []) if str(x).strip()]
        for item in (spec.get("page_api_mapping") or [])
        if str(item.get("page_id") or "").strip()
    }
    contract_map = {
        str(item.get("id") or ""): item
        for item in (spec.get("api_contracts") or [])
        if str(item.get("id") or "").strip()
    }
    replay_items = ((runtime_report.get("checks") or {}).get("business_path_replay") or {}).get("items") or []
    replay_page_scope: set[str] = set()
    for item in replay_items:
        for rp in (item.get("related_pages") or []):
            page_token = str(rp or "").strip()
            if page_token:
                replay_page_scope.add(page_token)

    screenshot_dir = project_dir / "screenshots"
    code_dir = project_dir / "aligned_code"
    blueprint_map = (ui_blueprint.get("page_map") or {}) if isinstance(ui_blueprint, dict) else {}
    if not isinstance(blueprint_map, dict):
        blueprint_map = {}

    claims: List[Dict[str, Any]] = []

    for page_id, page_data in pages.items():
        pid = str(page_id).strip()
        if not pid:
            continue
        page_title = str((page_data or {}).get("page_title") or menu_title_map.get(pid, pid)).strip() or pid
        page_desc = str((page_data or {}).get("page_description") or "").strip()
        full_screenshot = screenshot_dir / f"{pid}_full.png"
        fuzzy_screenshots = list(screenshot_dir.glob(f"*_{pid}_full.png")) if screenshot_dir.exists() else []
        screenshot_exists = full_screenshot.exists() or bool(fuzzy_screenshots)
        screenshot_paths = []
        if full_screenshot.exists():
            screenshot_paths.append(str(full_screenshot.relative_to(project_dir)).replace("\\", "/"))
        screenshot_paths.extend(
            [str(p.relative_to(project_dir)).replace("\\", "/") for p in fuzzy_screenshots if p.exists()]
        )

        api_ids = mapping_map.get(pid, [])
        contracts: List[Dict[str, Any]] = []
        method_names: List[str] = []
        api_paths: List[str] = []
        semantic_keywords: List[str] = [page_title, page_desc]
        for api_id in api_ids:
            contract = contract_map.get(api_id, {})
            if not contract:
                continue
            method_name = str(contract.get("method_name") or api_id).strip()
            http_method = str(contract.get("http_method") or "GET").upper()
            path = str(contract.get("path") or "").strip()
            desc = str(contract.get("description") or "").strip()
            contracts.append(
                {
                    "api_id": api_id,
                    "method_name": method_name,
                    "http_method": http_method,
                    "path": path,
                    "description": desc,
                }
            )
            if method_name:
                method_names.append(method_name)
            if path:
                api_paths.append(path)
            if desc:
                semantic_keywords.append(desc)

        replay_matches = []
        for item in replay_items:
            related_pages = [str(x) for x in (item.get("related_pages") or [])]
            if pid in related_pages:
                replay_matches.append(
                    {
                        "flow": str(item.get("flow") or ""),
                        "passed": bool(item.get("passed")),
                        "reason": str(item.get("reason") or ""),
                    }
                )

        runtime_required = pid in replay_page_scope
        runtime_linked = (not runtime_required) or any(x.get("passed") for x in replay_matches)
        code_hits = _collect_code_hits(
            code_dir,
            method_names=method_names,
            api_paths=api_paths,
            flow_keywords=semantic_keywords,
            allow_structural_fallback=runtime_linked,
        )

        # 显式映射为空（如系统监控页）时，不强制要求 API 合约绑定
        api_required = (pid in mapping_map) and len(api_ids) > 0
        api_linked = (len(contracts) > 0) if api_required else True
        code_linked = len(code_hits) > 0
        passed = bool(screenshot_exists and api_linked and code_linked and runtime_linked)

        missing_items: List[str] = []
        if not screenshot_exists:
            missing_items.append("screenshot")
        if api_required and not api_linked:
            missing_items.append("api_contract")
        if not code_linked:
            missing_items.append("code_trace")
        if runtime_required and not runtime_linked:
            missing_items.append("runtime_replay")

        page_claim = {
            "claim_id": f"page:{pid}",
            "claim_type": "page_capability",
            "claim_text": f"{page_title}页面功能可被执行、可被回放、可被截图佐证",
            "page_id": pid,
            "page_title": page_title,
            "page_description": page_desc,
            "block_id": "",
            "selector": "",
            "api_contract_id": str((contracts[0].get("api_id") if contracts else "") or ""),
            "code_ref": str((code_hits[0] if code_hits else "") or ""),
            "evidence": {
                "screenshot_exists": screenshot_exists,
                "screenshot_paths": screenshot_paths,
                "api_contracts": contracts,
                "api_contract_ids": [str(x.get("api_id") or "") for x in contracts if str(x.get("api_id") or "").strip()],
                "api_contract_id": str((contracts[0].get("api_id") if contracts else "") or ""),
                "code_hits": code_hits,
                "code_refs": code_hits,
                "code_ref": str((code_hits[0] if code_hits else "") or ""),
                "runtime_replay_matches": replay_matches,
            },
            "passed": passed,
            "missing_evidence": missing_items,
        }
        claims.append(page_claim)

        # Block-level claims (from ui blueprint).
        page_blueprint = blueprint_map.get(pid) if isinstance(blueprint_map, dict) else {}
        blocks = (page_blueprint.get("functional_blocks") or []) if isinstance(page_blueprint, dict) else []
        if not isinstance(blocks, list):
            blocks = []
        for block_index, block in enumerate(blocks, start=1):
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("block_id") or f"{pid}_block_{block_index}").strip()
            claim_id = str(block.get("claim_id") or f"claim:{pid}:block_{block_index}").strip()
            selector = str(block.get("selector") or "").strip()
            claim_text = str(block.get("claim_text") or f"{page_title}-{block_id} 功能可验证").strip()
            block_api_refs = [str(x).strip() for x in (block.get("api_refs") or []) if str(x).strip()]
            block_requires_api = bool(block.get("requires_api")) and bool(block_api_refs)

            block_contracts: List[Dict[str, Any]] = []
            for api_id in block_api_refs:
                contract = contract_map.get(api_id, {})
                if not contract:
                    continue
                block_contracts.append(
                    {
                        "api_id": api_id,
                        "method_name": str(contract.get("method_name") or api_id).strip(),
                        "http_method": str(contract.get("http_method") or "GET").upper(),
                        "path": str(contract.get("path") or "").strip(),
                        "description": str(contract.get("description") or "").strip(),
                    }
                )
            if not block_contracts and not block_api_refs:
                block_contracts = contracts

            widget_refs: List[str] = []
            for wid in (block.get("required_widgets") or []):
                widget = str(wid or "").strip()
                if not widget:
                    continue
                candidates = list(screenshot_dir.glob(f"*_{pid}_{widget}.png")) if screenshot_dir.exists() else []
                widget_refs.extend([str(x.relative_to(project_dir)).replace("\\", "/") for x in candidates if x.exists()])

            claim_screenshot_refs = _find_claim_screenshot_refs(
                project_dir=project_dir,
                page_id=pid,
                claim_id=claim_id,
                capture_report=capture_report,
            )
            merged_screenshots = []
            for item in (claim_screenshot_refs + widget_refs + screenshot_paths):
                norm = str(item or "").replace("\\", "/").strip()
                if norm and norm not in merged_screenshots:
                    merged_screenshots.append(norm)

            block_keywords = [page_title, page_desc, block_id, claim_text, selector]
            block_keywords.extend([str(x).strip() for x in (block.get("code_keywords") or []) if str(x).strip()])
            block_keywords.extend([str(x.get("method_name") or "") for x in block_contracts])
            block_keywords.extend([str(x.get("path") or "") for x in block_contracts])
            block_code_hits = _collect_code_hits(
                code_dir,
                method_names=[],
                api_paths=[],
                flow_keywords=block_keywords,
                allow_structural_fallback=runtime_linked,
            )
            if not block_code_hits and code_hits:
                block_code_hits = code_hits[:10]

            block_api_linked = bool(block_contracts) if block_requires_api else True
            block_screenshot_linked = bool(merged_screenshots)
            block_code_linked = bool(block_code_hits)
            block_runtime_linked = runtime_linked
            block_passed = bool(block_screenshot_linked and block_api_linked and block_code_linked and block_runtime_linked)

            block_missing: List[str] = []
            if not block_screenshot_linked:
                block_missing.append("screenshot")
            if block_requires_api and not block_api_linked:
                block_missing.append("api_contract")
            if not block_code_linked:
                block_missing.append("code_trace")
            if runtime_required and not block_runtime_linked:
                block_missing.append("runtime_replay")

            claims.append(
                {
                    "claim_id": claim_id,
                    "claim_type": "functional_block",
                    "claim_text": claim_text,
                    "page_id": pid,
                    "page_title": page_title,
                    "page_description": page_desc,
                    "block_id": block_id,
                    "selector": selector,
                    "api_contract_id": str((block_contracts[0].get("api_id") if block_contracts else "") or ""),
                    "code_ref": str((block_code_hits[0] if block_code_hits else "") or ""),
                    "evidence": {
                        "screenshot_exists": block_screenshot_linked,
                        "screenshot_paths": merged_screenshots,
                        "api_contracts": block_contracts,
                        "api_contract_ids": [str(x.get("api_id") or "") for x in block_contracts if str(x.get("api_id") or "").strip()],
                        "api_contract_id": str((block_contracts[0].get("api_id") if block_contracts else "") or ""),
                        "code_hits": block_code_hits,
                        "code_refs": block_code_hits,
                        "code_ref": str((block_code_hits[0] if block_code_hits else "") or ""),
                        "runtime_replay_matches": replay_matches,
                    },
                    "passed": block_passed,
                    "missing_evidence": block_missing,
                }
            )
    return claims


def _build_flow_claims(
    project_dir: Path,
    charter: Dict[str, Any],
    runtime_report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    replay_items = ((runtime_report.get("checks") or {}).get("business_path_replay") or {}).get("items") or []
    replay_map = {str(item.get("flow") or "").strip(): item for item in replay_items if str(item.get("flow") or "").strip()}
    code_dir = project_dir / "aligned_code"
    claims: List[Dict[str, Any]] = []

    for idx, flow in enumerate(charter.get("core_flows") or [], start=1):
        flow_name = str((flow or {}).get("name") or "").strip()
        if not flow_name:
            continue
        flow_steps = [str(x).strip() for x in ((flow or {}).get("steps") or []) if str(x).strip()]
        replay_item = replay_map.get(flow_name, {})
        runtime_linked = bool(replay_item.get("passed"))
        flow_keywords = _tokenize(flow_name)
        for step in flow_steps:
            flow_keywords.extend(_tokenize(step))
        flow_keywords.extend(_tokenize(" ".join([str(x) for x in (replay_item.get("related_pages") or [])])))
        flow_keywords.extend(_tokenize(" ".join([str(x) for x in (replay_item.get("related_apis") or [])])))
        code_hits = _collect_code_hits(
            code_dir,
            method_names=[],
            api_paths=[],
            flow_keywords=flow_keywords,
            allow_structural_fallback=runtime_linked,
        )
        code_linked = len(code_hits) > 0
        passed = bool(runtime_linked and code_linked)

        claims.append(
            {
                "claim_id": f"flow:{idx}",
                "claim_type": "business_flow",
                "claim_text": f"业务流程“{flow_name}”具备端到端可验证执行证据",
                "flow_name": flow_name,
                "flow_steps": flow_steps,
                "evidence": {
                    "runtime_replay": {
                        "present": bool(replay_item),
                        "passed": bool(replay_item.get("passed")),
                        "related_pages": replay_item.get("related_pages") or [],
                        "related_apis": replay_item.get("related_apis") or [],
                    },
                    "code_hits": code_hits,
                },
                "passed": passed,
                "missing_evidence": [
                    x
                    for x, ok in [
                        ("runtime_replay", runtime_linked),
                        ("code_trace", code_linked),
                    ]
                    if not ok
                ],
            }
        )
    return claims


def build_claim_evidence_matrix(
    project_name: str,
    project_dir: Path,
    html_dir: Optional[Path] = None,
    runtime_report_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    project_dir = Path(project_dir)
    html_dir = Path(html_dir) if html_dir else (project_dir.parent.parent / "temp_build" / project_name / "html")
    plan = _load_json(project_dir / "project_plan.json")
    charter = _load_json(project_dir / "project_charter.json")
    spec = _load_json(project_dir / "project_executable_spec.json")
    runtime_report = runtime_report_override or _load_json(project_dir / "runtime_verification_report.json")
    ui_blueprint = _load_ui_blueprint(project_dir)
    capture_report = _load_screenshot_capture_report(project_dir)

    page_claims = _build_page_claims(
        project_dir=project_dir,
        plan=plan,
        spec=spec,
        runtime_report=runtime_report,
        ui_blueprint=ui_blueprint,
        capture_report=capture_report,
    )
    flow_claims = _build_flow_claims(project_dir, charter, runtime_report)
    claims = page_claims + flow_claims
    passed_count = sum(1 for c in claims if c.get("passed"))
    total_count = len(claims)
    block_claim_count = sum(1 for c in claims if str(c.get("claim_type") or "") == "functional_block")
    binding_ratio = float(passed_count) / float(total_count) if total_count else 0.0
    weak_claims = [c for c in claims if not c.get("passed")]

    hard_issues: List[str] = []
    if not runtime_report:
        hard_issues.append("缺少运行回放报告，无法建立声称-证据绑定")
    if total_count == 0:
        hard_issues.append("未识别到可编译声称（页面/流程）")
    if weak_claims:
        hard_issues.append(f"存在未绑定声称 {len(weak_claims)} 条")

    passed = (len(hard_issues) == 0) and binding_ratio >= 0.85
    matrix = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "paths": {
            "project_dir": str(project_dir),
            "html_dir": str(html_dir),
            "plan_path": str(project_dir / "project_plan.json"),
            "charter_path": str(project_dir / "project_charter.json"),
            "spec_path": str(project_dir / "project_executable_spec.json"),
            "runtime_report_path": str(project_dir / "runtime_verification_report.json"),
            "ui_blueprint_path": str(project_dir / "ui_blueprint.json"),
            "screenshot_capture_report_path": str(project_dir / "screenshot_capture_report.json"),
        },
        "summary": {
            "total_claims": total_count,
            "passed_claims": passed_count,
            "weak_claims": len(weak_claims),
            "functional_block_claims": block_claim_count,
            "binding_ratio": round(binding_ratio, 4),
            "passed": bool(passed),
        },
        "hard_blocking_issues": hard_issues,
        "claims": claims,
    }
    return matrix


def compile_claim_evidence_matrix(
    project_name: str,
    project_dir: Path,
    html_dir: Optional[Path] = None,
    runtime_report_override: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Path, Dict[str, Any]]:
    matrix = build_claim_evidence_matrix(
        project_name=project_name,
        project_dir=project_dir,
        html_dir=html_dir,
        runtime_report_override=runtime_report_override,
    )
    output_path = Path(project_dir) / "claim_evidence_matrix.json"
    _save_json(output_path, matrix)
    return bool((matrix.get("summary") or {}).get("passed")), output_path, matrix
