"""
运行验证器：在文档生成前输出可执行证据。

说明：
- 不增加 LLM 调用，仅做本地可验证检查。
- 产物为 runtime_verification_report.json，供冻结包与申报链路复用。
"""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modules.claim_evidence_compiler import compile_claim_evidence_matrix
from modules.ui_skill_orchestrator import build_ui_skill_artifacts
from core.pipeline_config import PIPELINE_PROTOCOL_VERSION


class RuntimeVerifier:
    def __init__(self, project_name: str, project_dir: Path, html_dir: Path):
        self.project_name = project_name
        self.project_dir = Path(project_dir)
        self.html_dir = Path(html_dir)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _check_required_artifacts(self) -> Tuple[bool, Dict[str, bool]]:
        checks = {
            "project_plan": (self.project_dir / "project_plan.json").exists(),
            "project_charter": (self.project_dir / "project_charter.json").exists(),
            "project_executable_spec": (self.project_dir / "project_executable_spec.json").exists(),
            "runtime_skill_plan": (self.project_dir / "runtime_skill_plan.json").exists(),
            "runtime_rule_graph": (self.project_dir / "runtime_rule_graph.json").exists(),
            "ui_blueprint": (self.project_dir / "ui_blueprint.json").exists(),
            "screenshot_contract": (self.project_dir / "screenshot_contract.json").exists(),
            "html_pages": self.html_dir.exists() and any(self.html_dir.glob("*.html")),
            "screenshots": (self.project_dir / "screenshots").exists()
            and any((self.project_dir / "screenshots").glob("*.png")),
            "aligned_code": (self.project_dir / "aligned_code").exists()
            and any((self.project_dir / "aligned_code").rglob("*.*")),
        }
        return all(checks.values()), checks

    def _ensure_ui_skill_artifacts(self, plan: Dict[str, Any]) -> None:
        try:
            build_ui_skill_artifacts(
                project_name=self.project_name,
                plan=plan or {},
                project_dir=self.project_dir,
                force=False,
            )
        except Exception:
            pass

    def _python_syntax_smoke(self, max_files: int = 120) -> Dict[str, Any]:
        code_dir = self.project_dir / "aligned_code"
        py_files = list(code_dir.rglob("*.py"))[:max_files] if code_dir.exists() else []
        failures: List[Dict[str, str]] = []
        for path in py_files:
            try:
                source = path.read_text(encoding="utf-8")
                ast.parse(source)
            except Exception as e:
                failures.append({"file": str(path.relative_to(self.project_dir)), "error": str(e)})
        return {
            "checked_files": len(py_files),
            "failed_files": len(failures),
            "failure_samples": failures[:20],
            "passed": len(failures) == 0 if py_files else True,
        }

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not cleaned:
            return []

        tokens = set()
        parts = [p for p in re.split(r"[\s,/|，。；;、:：()（）\-]+", cleaned) if p]
        for part in parts:
            if len(part) < 2:
                continue
            tokens.add(part)

            # CJK 文本增加 2/3 字窗口，提升“流程词 -> 页面词”匹配命中率。
            if any("\u4e00" <= ch <= "\u9fff" for ch in part):
                for size in (2, 3):
                    for i in range(0, len(part) - size + 1):
                        tokens.add(part[i:i + size])
            elif len(part) > 4:
                tokens.add(part[:4])
                tokens.add(part[-4:])

        return sorted([t for t in tokens if len(t) >= 2], key=len, reverse=True)

    @staticmethod
    def _contains_keywords(text: str, keywords: List[str]) -> bool:
        hay = str(text or "").lower()
        if not hay:
            return False
        return any(k in hay for k in keywords)

    def _business_path_replay(self, plan: Dict[str, Any], charter: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
        pages = plan.get("pages") or {}
        mapping = {m.get("page_id"): m.get("api_ids", []) for m in (spec.get("page_api_mapping") or [])}
        menu_by_page = {
            str(item.get("page_id") or ""): str(item.get("title") or "").strip()
            for item in (plan.get("menu_list") or [])
            if str(item.get("page_id") or "").strip()
        }

        replay_items: List[Dict[str, Any]] = []
        matched = 0
        for flow in charter.get("core_flows") or []:
            name = str((flow or {}).get("name") or "").strip()
            if not name:
                continue
            flow_steps = [str(s).strip() for s in ((flow or {}).get("steps") or []) if str(s).strip()]
            flow_keywords = self._extract_keywords(name)
            for step in flow_steps:
                flow_keywords.extend(self._extract_keywords(step))
            flow_keywords = sorted(set(flow_keywords), key=len, reverse=True)

            related_pages = []
            related_page_texts: List[str] = []
            for page_id, page_data in pages.items():
                title = str((page_data or {}).get("page_title") or menu_by_page.get(page_id, "")).strip()
                desc = str((page_data or {}).get("page_description") or "").strip()
                menu_title = menu_by_page.get(page_id, "")
                hay = f"{title} {menu_title} {desc}".lower()
                if self._contains_keywords(hay, flow_keywords):
                    related_pages.append(page_id)
                    related_page_texts.append(hay)

            related_apis = []
            for pid in related_pages:
                related_apis.extend(mapping.get(pid, []))
            related_apis = sorted(list(set([a for a in related_apis if a])))

            matched_step_count = 0
            for step in flow_steps:
                step_keywords = self._extract_keywords(step)
                if step_keywords and any(self._contains_keywords(text, step_keywords) for text in related_page_texts):
                    matched_step_count += 1
            required_step_hits = 1 if flow_steps else 0

            is_matched = bool(related_pages) and bool(related_apis) and matched_step_count >= required_step_hits
            matched += 1 if is_matched else 0
            replay_items.append(
                {
                    "flow": name,
                    "steps": flow_steps,
                    "related_pages": related_pages,
                    "related_apis": related_apis,
                    "matched_step_count": matched_step_count,
                    "required_step_hits": required_step_hits,
                    "reason": "ok" if is_matched else "缺少页面映射/API映射/步骤命中",
                    "passed": is_matched,
                }
            )

        total = len(replay_items)
        return {
            "total_flows": total,
            "matched_flows": matched,
            "match_ratio": round(matched / total, 3) if total else 0.0,
            "items": replay_items,
            "passed": (matched == total) and total > 0,
        }

    def _claim_evidence_check(self, replay_report: Dict[str, Any]) -> Dict[str, Any]:
        runtime_report_override = {
            "checks": {
                "business_path_replay": replay_report or {},
            }
        }
        ok, output_path, matrix = compile_claim_evidence_matrix(
            project_name=self.project_name,
            project_dir=self.project_dir,
            html_dir=self.html_dir,
            runtime_report_override=runtime_report_override,
        )
        summary = matrix.get("summary") or {}
        return {
            "path": str(output_path),
            "passed": bool(ok),
            "total_claims": int(summary.get("total_claims") or 0),
            "passed_claims": int(summary.get("passed_claims") or 0),
            "weak_claims": int(summary.get("weak_claims") or 0),
            "binding_ratio": float(summary.get("binding_ratio") or 0.0),
            "hard_blocking_issues": matrix.get("hard_blocking_issues") or [],
        }

    def run(self) -> Dict[str, Any]:
        plan = self._load_json(self.project_dir / "project_plan.json")
        charter = self._load_json(self.project_dir / "project_charter.json")
        spec = self._load_json(self.project_dir / "project_executable_spec.json")
        target_language = str((plan.get("genome") or {}).get("target_language") or "").strip().lower()

        self._ensure_ui_skill_artifacts(plan)

        artifacts_passed, artifact_checks = self._check_required_artifacts()
        syntax_report = self._python_syntax_smoke() if target_language == "python" else {
            "checked_files": 0,
            "failed_files": 0,
            "failure_samples": [],
            "passed": True,
        }
        replay_report = self._business_path_replay(plan, charter, spec)
        claim_report = self._claim_evidence_check(replay_report)

        # 运行验证聚焦“可运行性 + 回放可达性”，声称-证据结果单独输出给最终门禁使用。
        overall_passed = (
            artifacts_passed
            and syntax_report["passed"]
            and replay_report["passed"]
        )
        report = {
            "project_name": self.project_name,
            "pipeline_protocol_version": str(plan.get("pipeline_protocol_version") or PIPELINE_PROTOCOL_VERSION),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "overall_passed": overall_passed,
            "checks": {
                "required_artifacts": artifact_checks,
                "python_syntax_smoke": syntax_report,
                "business_path_replay": replay_report,
                "claim_evidence": claim_report,
            },
            "summary": {
                "artifacts_passed": artifacts_passed,
                "syntax_passed": syntax_report["passed"],
                "replay_passed": replay_report["passed"],
                "claim_evidence_passed": claim_report["passed"],
            },
        }
        return report


def run_runtime_verification(project_name: str, project_dir: Path, html_dir: Path) -> Tuple[bool, Path, Dict[str, Any]]:
    verifier = RuntimeVerifier(project_name, project_dir=project_dir, html_dir=html_dir)
    report = verifier.run()
    output_path = Path(project_dir) / "runtime_verification_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report.get("overall_passed", False), output_path, report
