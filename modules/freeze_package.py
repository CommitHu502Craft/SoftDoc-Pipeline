"""
冻结提交包构建器（开发事实链）。

输出内容：
- freeze_package/manifest.json
- freeze_package/artifact_hashes.json
- freeze_package/reproducibility_report.json
- freeze_package/api_replay_evidence.json
- freeze_package/key_task_logs.json
- freeze_package/artifact_hash_chain.json
- freeze_package/development_change_record.json
- freeze_package/change_log.md
- <project>_freeze_package.zip
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from config import BASE_DIR
from core.pipeline_config import PIPELINE_PROTOCOL_VERSION
from modules.artifact_naming import build_artifact_filenames, candidate_artifact_paths


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _safe_git_revision(base_dir: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(base_dir),
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return out.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _collect_artifacts(project_name: str, project_dir: Path, html_dir: Path) -> List[Path]:
    filenames = build_artifact_filenames(project_name=project_name, project_dir=project_dir)
    candidates = [
        project_dir / "project_plan.json",
        project_dir / "project_charter.json",
        project_dir / "project_executable_spec.json",
        project_dir / "runtime_verification_report.json",
        project_dir / "runtime_skill_plan.json",
        project_dir / "runtime_skill_override.json",
        project_dir / "skill_studio_plan.json",
        project_dir / "runtime_rule_graph.json",
        project_dir / "skill_compliance_report.json",
        project_dir / "skill_autorepair_report.json",
        project_dir / "skill_policy_decision_report.json",
        project_dir / "ui_skill_profile.json",
        project_dir / "ui_blueprint.json",
        project_dir / "screenshot_contract.json",
        project_dir / "screenshot_capture_report.json",
        project_dir / "project_spec.json",
        project_dir / "project_metadata.json",
        project_dir / "novelty_quality_report.json",
    ]
    for key in ("manual_docx", "manual_pdf", "code_pdf"):
        for path in candidate_artifact_paths(project_dir, project_name=project_name, artifact_key=key):
            if path.exists():
                candidates.append(path)

    artifacts = [p for p in candidates if p.exists()]
    for root in [project_dir / "aligned_code", project_dir / "screenshots", html_dir]:
        if root.exists() and root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    artifacts.append(path)

    uniq: List[Path] = []
    seen = set()
    for p in artifacts:
        k = str(p.resolve())
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    return uniq


def _display_path(path: Path, project_dir: Path) -> str:
    candidates = [project_dir.parent, project_dir.parent.parent, project_dir]
    for base in candidates:
        try:
            return str(path.relative_to(base)).replace("\\", "/")
        except Exception:
            continue
    return str(path).replace("\\", "/")


def _load_pipeline_protocol_version(project_dir: Path) -> str:
    plan_path = project_dir / "project_plan.json"
    if not plan_path.exists():
        return PIPELINE_PROTOCOL_VERSION
    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
        return str(plan.get("pipeline_protocol_version") or PIPELINE_PROTOCOL_VERSION)
    except Exception:
        return PIPELINE_PROTOCOL_VERSION


def _build_reproducibility_report(hashes: List[Dict[str, Any]], artifacts: List[Path]) -> Dict[str, Any]:
    checked = 0
    mismatched: List[str] = []
    missing: List[str] = []
    for item, artifact_path in zip(hashes, artifacts):
        rel = str(item.get("path") or "").replace("\\", "/")
        expected = str(item.get("sha256") or "")
        if not rel or not expected:
            continue
        target = Path(artifact_path)
        if not target.exists():
            missing.append(rel)
            continue
        checked += 1
        actual = _sha256_file(target)
        if actual != expected:
            mismatched.append(rel)

    passed = (not mismatched) and (not missing)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checked_files": checked,
        "missing_files": missing,
        "mismatched_files": mismatched,
        "passed": passed,
    }


def _write_api_replay_evidence(project_name: str, project_dir: Path, freeze_dir: Path) -> Path:
    runtime_report = _load_json(project_dir / "runtime_verification_report.json")
    replay = ((runtime_report.get("checks") or {}).get("business_path_replay") or {})
    payload = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_report": str(project_dir / "runtime_verification_report.json"),
        "summary": {
            "passed": bool(replay.get("passed")),
            "coverage": replay.get("coverage"),
            "page_count": replay.get("page_count"),
            "mapped_page_count": replay.get("mapped_page_count"),
            "api_ref_count": replay.get("api_ref_count"),
            "invalid_api_ref_count": replay.get("invalid_api_ref_count"),
        },
        "replay_detail": replay,
    }
    output = freeze_dir / "api_replay_evidence.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output


def _write_key_task_logs(project_name: str, freeze_dir: Path) -> Path:
    logs_dir = BASE_DIR / "data" / "task_logs"
    selected_path = ""
    selected_payload: Dict[str, Any] = {}
    selected_updated = ""
    if logs_dir.exists():
        for path in logs_dir.glob("*.json"):
            payload = _load_json(path)
            if str(payload.get("project_name") or "") != project_name:
                continue
            updated = str(payload.get("last_updated") or "")
            if not selected_payload or updated >= selected_updated:
                selected_payload = payload
                selected_path = str(path)
                selected_updated = updated

    logs = selected_payload.get("logs") or []
    if isinstance(logs, list) and len(logs) > 300:
        logs = logs[-300:]

    output_payload = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_log_file": selected_path,
        "last_updated": selected_updated,
        "log_count": len(logs) if isinstance(logs, list) else 0,
        "logs": logs if isinstance(logs, list) else [],
    }
    output = freeze_dir / "key_task_logs.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)
    return output


def _build_artifact_hash_chain(project_name: str, hashes: List[Dict[str, Any]]) -> Dict[str, Any]:
    prev_chain_hash = "GENESIS"
    chain_items: List[Dict[str, Any]] = []
    for index, item in enumerate(hashes, start=1):
        path = str(item.get("path") or "")
        artifact_hash = str(item.get("sha256") or "")
        chain_input = f"{index}|{path}|{artifact_hash}|{prev_chain_hash}"
        chain_hash = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()
        chain_items.append(
            {
                "index": index,
                "path": path,
                "artifact_sha256": artifact_hash,
                "prev_chain_hash": prev_chain_hash,
                "chain_hash": chain_hash,
            }
        )
        prev_chain_hash = chain_hash
    return {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "algorithm": "sha256",
        "root_hash": "GENESIS",
        "tail_hash": prev_chain_hash,
        "count": len(chain_items),
        "items": chain_items,
    }


def _write_development_change_record(project_name: str, project_dir: Path, artifacts: List[Path], freeze_dir: Path) -> Path:
    timeline = []
    for path in artifacts:
        try:
            stat = path.stat()
            timeline.append(
                {
                    "path": _display_path(path, project_dir),
                    "size": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        except Exception:
            continue
    timeline.sort(key=lambda x: str(x.get("modified_at") or ""))

    payload = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "artifact_timeline": timeline,
        "summary": {
            "artifact_count": len(timeline),
            "first_modified_at": timeline[0]["modified_at"] if timeline else "",
            "last_modified_at": timeline[-1]["modified_at"] if timeline else "",
        },
    }
    output = freeze_dir / "development_change_record.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for parser in (
        lambda x: datetime.fromisoformat(x),
        lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"),
        lambda x: datetime.strptime(x, "%Y-%m-%d"),
    ):
        try:
            return parser(text)
        except Exception:
            continue
    return None


def _build_timeline_consistency_report(
    project_name: str,
    project_dir: Path,
    artifact_timeline: List[Dict[str, Any]],
    frozen_at: str,
) -> Dict[str, Any]:
    metadata = _load_json(project_dir / "project_metadata.json")
    parsed_timeline = []
    for item in artifact_timeline:
        parsed = _parse_datetime(item.get("modified_at"))
        if parsed is None:
            continue
        parsed_timeline.append(
            {
                "path": item.get("path"),
                "modified_at": item.get("modified_at"),
                "dt": parsed,
            }
        )
    parsed_timeline.sort(key=lambda x: x["dt"])

    inferred_started = parsed_timeline[0]["modified_at"] if parsed_timeline else ""
    inferred_completed = parsed_timeline[-1]["modified_at"] if parsed_timeline else ""
    inferred_started_dt = parsed_timeline[0]["dt"] if parsed_timeline else None
    inferred_completed_dt = parsed_timeline[-1]["dt"] if parsed_timeline else None
    frozen_at_dt = _parse_datetime(frozen_at)

    declared = {
        "development_started_at": str(
            metadata.get("development_started_at")
            or metadata.get("dev_started_at")
            or ""
        ).strip(),
        "development_completed_at": str(
            metadata.get("development_completed_at")
            or metadata.get("dev_completed_at")
            or ""
        ).strip(),
        "published_at": str(metadata.get("published_at") or "").strip(),
        "submit_at": str(metadata.get("submit_at") or metadata.get("submitted_at") or "").strip(),
        "organization_established_at": str(
            metadata.get("organization_established_at")
            or metadata.get("company_established_at")
            or metadata.get("entity_established_at")
            or ""
        ).strip(),
    }
    declared_dt = {k: _parse_datetime(v) for k, v in declared.items()}

    issues: List[str] = []
    warnings: List[str] = []

    if inferred_started_dt and inferred_completed_dt and inferred_started_dt > inferred_completed_dt:
        issues.append("推断开发时间线异常：开始时间晚于完成时间")
    if inferred_completed_dt and frozen_at_dt and inferred_completed_dt > frozen_at_dt:
        issues.append("推断开发完成时间晚于冻结时间，存在时序冲突")

    dev_start_dt = declared_dt.get("development_started_at") or inferred_started_dt
    dev_end_dt = declared_dt.get("development_completed_at") or inferred_completed_dt
    published_dt = declared_dt.get("published_at")
    submit_dt = declared_dt.get("submit_at")
    org_dt = declared_dt.get("organization_established_at")

    if dev_start_dt and dev_end_dt and dev_start_dt > dev_end_dt:
        issues.append("声明开发时间线异常：development_started_at 晚于 development_completed_at")
    if published_dt and dev_end_dt and published_dt < dev_end_dt:
        issues.append("声明发布时间早于开发完成时间")
    if submit_dt and dev_end_dt and submit_dt < dev_end_dt:
        issues.append("声明提交时间早于开发完成时间")
    if org_dt and dev_end_dt and dev_end_dt < org_dt:
        warnings.append("开发完成时间早于主体成立时间，需补充前期开发证明")

    passed = len(issues) == 0
    return {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "issues": issues,
        "warnings": warnings,
        "inferred_timeline": {
            "artifact_count": len(parsed_timeline),
            "development_started_at": inferred_started,
            "development_completed_at": inferred_completed,
            "frozen_at": frozen_at,
        },
        "declared_timeline": declared,
        "requires_supporting_note": bool(warnings),
    }


def _write_timeline_support_note(report: Dict[str, Any], freeze_dir: Path) -> Path:
    out = freeze_dir / "timeline_supporting_note.md"
    lines = [
        "# 时间线补充说明",
        "",
        f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- 一致性结论: {'通过' if report.get('passed') else '不通过'}",
        "",
        "## 推断时间线",
        f"- 开发开始（推断）: {(report.get('inferred_timeline') or {}).get('development_started_at') or 'N/A'}",
        f"- 开发完成（推断）: {(report.get('inferred_timeline') or {}).get('development_completed_at') or 'N/A'}",
        f"- 冻结时间: {(report.get('inferred_timeline') or {}).get('frozen_at') or 'N/A'}",
        "",
        "## 声明时间线",
        f"- 开发开始（声明）: {(report.get('declared_timeline') or {}).get('development_started_at') or 'N/A'}",
        f"- 开发完成（声明）: {(report.get('declared_timeline') or {}).get('development_completed_at') or 'N/A'}",
        f"- 发布时间（声明）: {(report.get('declared_timeline') or {}).get('published_at') or 'N/A'}",
        f"- 提交时间（声明）: {(report.get('declared_timeline') or {}).get('submit_at') or 'N/A'}",
        f"- 主体成立时间（声明）: {(report.get('declared_timeline') or {}).get('organization_established_at') or 'N/A'}",
        "",
    ]
    issues = report.get("issues") or []
    warnings = report.get("warnings") or []
    if issues:
        lines.append("## 问题（阻断）")
        lines.extend([f"- {x}" for x in issues])
        lines.append("")
    if warnings:
        lines.append("## 风险提示（需补证）")
        lines.extend([f"- {x}" for x in warnings])
        lines.append("")
    if not issues and not warnings:
        lines.append("## 结论")
        lines.append("- 当前时间线一致性良好，无需额外补充说明。")

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out


def build_freeze_package(project_name: str, project_dir: Path, html_dir: Path) -> Dict[str, Any]:
    project_dir = Path(project_dir)
    html_dir = Path(html_dir)
    freeze_dir = project_dir / "freeze_package"
    freeze_dir.mkdir(parents=True, exist_ok=True)

    artifacts = _collect_artifacts(project_name, project_dir, html_dir)
    hashes = []
    for path in artifacts:
        hashes.append(
            {
                "path": _display_path(path, project_dir),
                "size": path.stat().st_size if path.exists() else 0,
                "sha256": _sha256_file(path) if path.exists() else "",
            }
        )

    manifest_path = freeze_dir / "manifest.json"
    hashes_path = freeze_dir / "artifact_hashes.json"
    reproducibility_path = freeze_dir / "reproducibility_report.json"
    hash_chain_path = freeze_dir / "artifact_hash_chain.json"
    changelog_path = freeze_dir / "change_log.md"

    with open(hashes_path, "w", encoding="utf-8") as f:
        json.dump({"project_name": project_name, "items": hashes}, f, ensure_ascii=False, indent=2)

    reproducibility = _build_reproducibility_report(hashes, artifacts)
    with open(reproducibility_path, "w", encoding="utf-8") as f:
        json.dump(reproducibility, f, ensure_ascii=False, indent=2)

    api_replay_path = _write_api_replay_evidence(project_name, project_dir, freeze_dir)
    key_logs_path = _write_key_task_logs(project_name, freeze_dir)
    hash_chain = _build_artifact_hash_chain(project_name, hashes)
    with open(hash_chain_path, "w", encoding="utf-8") as f:
        json.dump(hash_chain, f, ensure_ascii=False, indent=2)
    change_record_path = _write_development_change_record(project_name, project_dir, artifacts, freeze_dir)
    change_record_payload = _load_json(change_record_path)

    frozen_at = datetime.now().isoformat(timespec="seconds")
    timeline_report = _build_timeline_consistency_report(
        project_name=project_name,
        project_dir=project_dir,
        artifact_timeline=change_record_payload.get("artifact_timeline") or [],
        frozen_at=frozen_at,
    )
    timeline_report_path = freeze_dir / "timeline_consistency_report.json"
    with open(timeline_report_path, "w", encoding="utf-8") as f:
        json.dump(timeline_report, f, ensure_ascii=False, indent=2)
    timeline_note_path = _write_timeline_support_note(timeline_report, freeze_dir)

    evidence_candidates_artifact = [
        "project_charter.json",
        "project_executable_spec.json",
        "runtime_verification_report.json",
        "runtime_skill_override.json",
        "skill_studio_plan.json",
        "runtime_rule_graph.json",
        "skill_compliance_report.json",
        "skill_autorepair_report.json",
        "skill_policy_decision_report.json",
        "ui_skill_profile.json",
        "ui_blueprint.json",
        "screenshot_contract.json",
        "screenshot_capture_report.json",
        "project_metadata.json",
        "novelty_quality_report.json",
    ]
    hashed_paths = [str(item.get("path", "")).replace("\\", "/") for item in hashes]
    evidence_chain = [
        p for p in evidence_candidates_artifact
        if any(h.endswith(p) for h in hashed_paths)
    ]
    evidence_candidates_freeze = [
        "api_replay_evidence.json",
        "key_task_logs.json",
        "artifact_hashes.json",
        "artifact_hash_chain.json",
        "reproducibility_report.json",
        "development_change_record.json",
        "timeline_consistency_report.json",
        "timeline_supporting_note.md",
    ]
    for name in evidence_candidates_freeze:
        if (freeze_dir / name).exists():
            evidence_chain.append(name)
    missing_evidence = [
        p for p in (evidence_candidates_artifact + evidence_candidates_freeze)
        if p not in evidence_chain
    ]

    manifest = {
        "project_name": project_name,
        "pipeline_protocol_version": _load_pipeline_protocol_version(project_dir),
        "frozen_at": frozen_at,
        "git_revision": _safe_git_revision(project_dir.parent),
        "artifact_count": len(hashes),
        "artifacts_file": "artifact_hashes.json",
        "hash_chain_file": "artifact_hash_chain.json",
        "reproducibility_report_file": "reproducibility_report.json",
        "api_replay_evidence_file": "api_replay_evidence.json",
        "task_logs_file": "key_task_logs.json",
        "development_change_record_file": "development_change_record.json",
        "timeline_consistency_report_file": "timeline_consistency_report.json",
        "timeline_supporting_note_file": "timeline_supporting_note.md",
        "hash_chain_tail": hash_chain.get("tail_hash", ""),
        "evidence_chain": evidence_chain,
        "missing_evidence": missing_evidence,
        "timeline_consistency_passed": bool(timeline_report.get("passed")),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    changelog = [
        f"# 冻结提交包 - {project_name}",
        "",
        f"- 冻结时间: {manifest['frozen_at']}",
        f"- Git 版本: {manifest['git_revision'] or 'N/A'}",
        f"- 产物数量: {manifest['artifact_count']}",
        f"- 流程协议版本: {manifest['pipeline_protocol_version']}",
        f"- 复验结果: {'通过' if reproducibility.get('passed') else '失败'}",
        f"- 时间线一致性: {'通过' if timeline_report.get('passed') else '失败'}",
        "",
        "## 事实链",
        "1. 项目章程（需求边界）",
        "2. 可执行规格（实体/状态机/权限/API）",
        "3. 运行验证与接口回放证据",
        "4. 关键任务日志与开发变更记录",
        "5. 产物哈希与哈希链",
        "6. 最终申报文档与可复验报告",
    ]
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write("\n".join(changelog))

    filenames = build_artifact_filenames(project_name=project_name, project_dir=project_dir)
    freeze_zip_name = str(filenames.get("freeze_zip") or f"{project_name}_freeze_package.zip")
    zip_base = project_dir / Path(freeze_zip_name).with_suffix("").name
    zip_path = Path(shutil.make_archive(str(zip_base), "zip", root_dir=str(freeze_dir)))

    return {
        "manifest_path": str(manifest_path),
        "hashes_path": str(hashes_path),
        "hash_chain_path": str(hash_chain_path),
        "api_replay_path": str(api_replay_path),
        "task_logs_path": str(key_logs_path),
        "development_change_record_path": str(change_record_path),
        "change_log_path": str(changelog_path),
        "reproducibility_path": str(reproducibility_path),
        "timeline_consistency_report_path": str(timeline_report_path),
        "timeline_supporting_note_path": str(timeline_note_path),
        "zip_path": str(zip_path),
        "artifact_count": len(hashes),
        "reproducibility_passed": bool(reproducibility.get("passed")),
        "timeline_consistency_passed": bool(timeline_report.get("passed")),
    }
