"""
规格评审辅助模块。

目标：
1) 为可执行规格生成可读摘要，便于人工快速确认。
2) 记录规格哈希与确认状态，避免“规格已变更但实现仍沿用旧确认”。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _compute_spec_digest(spec: Dict[str, Any]) -> str:
    payload = json.dumps(spec or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _spec_paths(project_dir: Path) -> Tuple[Path, Path, Path]:
    return (
        project_dir / "project_executable_spec.json",
        project_dir / "spec_review_status.json",
        project_dir / "spec_review_guide.md",
    )


def _build_guide(project_name: str, spec: Dict[str, Any], digest: str) -> str:
    entities = [str(x.get("name", "")).strip() for x in (spec.get("entities") or []) if str(x.get("name", "")).strip()]
    apis = spec.get("api_contracts") or []
    flows = spec.get("state_machines") or []
    roles = spec.get("permission_matrix") or []

    lines: List[str] = [
        f"# 规格评审清单 - {project_name}",
        "",
        f"- 生成时间: {_now()}",
        f"- 规格哈希: `{digest}`",
        "",
        "## 快速核查项",
        "1. 实体模型是否覆盖核心业务对象（非通用CRUD换皮）",
        "2. API 合约语义是否与业务流程一致",
        "3. 权限矩阵是否满足角色职责边界",
        "4. 状态机是否覆盖关键流程步骤与成功条件",
        "",
        "## 摘要",
        f"- 实体数: {len(entities)}",
        f"- API数: {len(apis)}",
        f"- 流程状态机数: {len(flows)}",
        f"- 角色数: {len(roles)}",
        "",
    ]

    if entities:
        lines.append("## 实体模型")
        for name in entities[:20]:
            lines.append(f"- {name}")
        lines.append("")

    if flows:
        lines.append("## 状态机")
        for item in flows[:10]:
            flow_name = str(item.get("name") or "").strip() or "未命名流程"
            state_count = len(item.get("states") or [])
            lines.append(f"- {flow_name}（状态 {state_count}）")
        lines.append("")

    if apis:
        lines.append("## API 合约（前20条）")
        for api in apis[:20]:
            method = str(api.get("http_method") or "GET").upper()
            path = str(api.get("path") or "/api/undefined")
            desc = str(api.get("description") or "").strip()
            lines.append(f"- {method} {path} | {desc}")
        lines.append("")

    return "\n".join(lines)


def save_spec_review_artifacts(project_dir: Path, project_name: str, spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    生成规格评审摘要，并刷新评审状态（若规格变更则自动回到 pending）。
    """
    project_dir = Path(project_dir)
    spec_path, status_path, guide_path = _spec_paths(project_dir)
    current_spec = spec or _read_json(spec_path)
    if not current_spec:
        return {
            "ok": False,
            "message": f"规格文件不存在或为空: {spec_path}",
            "spec_path": str(spec_path),
        }

    digest = _compute_spec_digest(current_spec)
    old_status = _read_json(status_path)
    old_approved_digest = str(old_status.get("approved_spec_digest") or "")
    approved = bool(old_status.get("approved")) and old_approved_digest == digest

    status = {
        "project_name": project_name,
        "spec_path": str(spec_path),
        "spec_digest": digest,
        "approved": approved,
        "approved_spec_digest": old_approved_digest if approved else "",
        "review_status": "approved" if approved else "pending",
        "updated_at": _now(),
        "reviewed_at": old_status.get("reviewed_at") if approved else "",
        "reviewer": old_status.get("reviewer") if approved else "",
    }

    guide = _build_guide(project_name, current_spec, digest)
    _write_json(status_path, status)
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(guide)

    return {
        "ok": True,
        "status_path": str(status_path),
        "guide_path": str(guide_path),
        "spec_digest": digest,
        "review_status": status["review_status"],
    }


def get_spec_review_status(project_dir: Path, spec_path: Optional[Path] = None) -> Dict[str, Any]:
    project_dir = Path(project_dir)
    resolved_spec_path, status_path, guide_path = _spec_paths(project_dir)
    if spec_path:
        resolved_spec_path = Path(spec_path)

    spec = _read_json(resolved_spec_path)
    if not spec:
        return {
            "approved": False,
            "review_status": "missing_spec",
            "spec_digest": "",
            "status_path": str(status_path),
            "guide_path": str(guide_path),
        }

    digest = _compute_spec_digest(spec)
    status = _read_json(status_path)
    approved = bool(status.get("approved")) and str(status.get("approved_spec_digest") or "") == digest
    return {
        "approved": approved,
        "review_status": "approved" if approved else "pending",
        "spec_digest": digest,
        "status_path": str(status_path),
        "guide_path": str(guide_path),
        "reviewer": str(status.get("reviewer") or ""),
        "reviewed_at": str(status.get("reviewed_at") or ""),
    }


def approve_spec_review(project_dir: Path, reviewer: str = "user") -> Dict[str, Any]:
    """
    标记当前规格为已确认（绑定当前规格哈希）。
    """
    project_dir = Path(project_dir)
    spec_path, status_path, _ = _spec_paths(project_dir)
    spec = _read_json(spec_path)
    if not spec:
        return {"ok": False, "message": f"规格文件不存在或为空: {spec_path}"}

    digest = _compute_spec_digest(spec)
    status = _read_json(status_path)
    status.update(
        {
            "approved": True,
            "approved_spec_digest": digest,
            "spec_digest": digest,
            "review_status": "approved",
            "reviewer": reviewer,
            "reviewed_at": _now(),
            "updated_at": _now(),
        }
    )
    _write_json(status_path, status)
    return {"ok": True, "status_path": str(status_path), "spec_digest": digest}
