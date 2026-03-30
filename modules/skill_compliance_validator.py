"""
Runtime skill compliance validator.

Includes three lint domains:
1) CopyLint   - page narration and overview copy constraints.
2) HtmlLint   - HTML/CSS/Chart structural constraints.
3) ActionLint - button action and modal behavior constraints.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from modules.runtime_skill_compiler import build_runtime_rule_graph


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


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _line_of(content: str, offset: int) -> int:
    if offset <= 0:
        return 1
    return content[:offset].count("\n") + 1


def _find_line_by_snippet(content: str, snippet: str) -> int:
    text = str(snippet or "").strip()
    if not text:
        return 1
    idx = content.find(text[:50])
    return _line_of(content, idx) if idx >= 0 else 1


def _split_sentences(text: str) -> List[str]:
    raw = re.split(r"[。！？!?]+", str(text or ""))
    return [x.strip() for x in raw if x and x.strip()]


def _count_chars(text: str) -> int:
    cleaned = re.sub(r"\s+", "", str(text or ""))
    return len(cleaned)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _strip_html_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or ""))


def _is_non_zero_radius(value: str) -> bool:
    token = str(value or "").strip().lower()
    if not token:
        return False
    if token in {"0", "0px", "0rem", "0em", "0%"}:
        return False
    if re.fullmatch(r"0(?:\.0+)?[a-z%]*", token):
        return False
    return True


def _script_src_is_external(src: str) -> bool:
    text = str(src or "").strip().lower()
    return text.startswith(("http://", "https://", "//"))


def _script_src_domain(src: str) -> str:
    text = str(src or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    try:
        parsed = urlparse(text)
        return str(parsed.netloc or "").strip().lower()
    except Exception:
        return ""


def _domain_allowed(domain: str, allowed_domains: List[str]) -> bool:
    host = str(domain or "").strip().lower()
    if not host:
        return False
    normalized = [str(x or "").strip().lower() for x in (allowed_domains or []) if str(x or "").strip()]
    for item in normalized:
        if host == item or host.endswith(f".{item}"):
            return True
    return False


def _collect_html_files(html_dir: Path) -> List[Path]:
    if not Path(html_dir).exists():
        return []
    return sorted([p for p in Path(html_dir).glob("*.html") if p.is_file()])


def _resolve_evidence_file_rel(file_value: Any, project_dir: Path, html_dir: Path) -> Tuple[str, str]:
    raw = str(file_value or "").strip()
    if not raw:
        return "", "unknown"
    normalized = raw.replace("\\", "/")
    p = Path(raw)
    if not p.is_absolute():
        lower = normalized.lower()
        if lower.endswith(".html"):
            return normalized, "html"
        if lower.endswith(".json"):
            return normalized, "json"
        return normalized, "artifact"

    try:
        rel_html = p.relative_to(Path(html_dir))
        return str(rel_html).replace("\\", "/"), "html"
    except Exception:
        pass
    try:
        rel_project = p.relative_to(Path(project_dir))
        return str(rel_project).replace("\\", "/"), "project"
    except Exception:
        pass
    return p.name, "external"


def _enrich_evidence_trace(evidence: List[Dict[str, Any]], project_dir: Path, html_dir: Path) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for idx, item in enumerate(evidence or [], start=1):
        row = dict(item or {})
        line_raw = row.get("line")
        try:
            line_no = int(line_raw or 1)
        except Exception:
            line_no = 1
        if line_no <= 0:
            line_no = 1
        file_rel, source_group = _resolve_evidence_file_rel(row.get("file"), project_dir=project_dir, html_dir=html_dir)
        row["trace_id"] = f"ev_{idx:04d}"
        row["line"] = line_no
        row["file_rel"] = file_rel
        row["source_group"] = source_group
        row["jump_anchor"] = f"{file_rel or 'unknown'}:{line_no}"
        enriched.append(row)
    return enriched


def _load_runtime_rule_graph(project_dir: Path) -> Tuple[Dict[str, Any], Path]:
    graph_path = Path(project_dir) / "runtime_rule_graph.json"
    payload = _load_json(graph_path)
    if payload:
        return payload, graph_path

    runtime_plan_path = Path(project_dir) / "runtime_skill_plan.json"
    runtime_plan = _load_json(runtime_plan_path)
    path, compiled = build_runtime_rule_graph(Path(project_dir), runtime_skill_plan=runtime_plan)
    return compiled, path


def _record_result(
    *,
    results: List[Dict[str, Any]],
    rule_id: str,
    category: str,
    severity: str,
    passed: bool,
    checked_count: int,
    failed_count: int,
    message: str,
) -> None:
    results.append(
        {
            "rule_id": rule_id,
            "category": category,
            "severity": severity,
            "passed": bool(passed),
            "checked_count": int(checked_count),
            "failed_count": int(failed_count),
            "message": str(message or ""),
        }
    )


def _copy_rule_eval(
    *,
    rule_id: str,
    params: Dict[str, Any],
    plan: Dict[str, Any],
    html_map: Dict[str, str],
    plan_text: str,
    results: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    severity: str,
) -> None:
    pages = plan.get("pages") or {}
    if not isinstance(pages, dict):
        pages = {}
    project_intro = plan.get("project_intro") or {}
    if not isinstance(project_intro, dict):
        project_intro = {}

    page_items: List[Tuple[str, Dict[str, Any]]] = []
    for page_id, page in pages.items():
        if isinstance(page, dict):
            page_items.append((str(page_id), page))

    def page_has_chart(page_id: str, page_payload: Dict[str, Any]) -> bool:
        if isinstance(page_payload.get("charts"), list) and len(page_payload.get("charts") or []) > 0:
            return True
        html = html_map.get(f"{page_id}.html", "") or html_map.get(str(page_id), "")
        return ("widget_chart_" in html) or ("echarts" in html.lower()) or ("new chart(" in html.lower())

    failed = 0
    checked = 0

    if rule_id == "copy.first_sentence_prefix":
        prefix = str(params.get("prefix") or "本页面")
        for page_id, page in page_items:
            checked += 1
            desc = str(page.get("page_description") or "").strip()
            sentences = _split_sentences(desc)
            first = sentences[0] if sentences else ""
            if not first.startswith(prefix):
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": first[:180],
                        "message": f"首句未以“{prefix}”开头",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="页面首句前缀检查",
        )
        return

    if rule_id == "copy.forbid_phrase_after_first":
        phrase = str(params.get("phrase") or "本页面").strip()
        if not phrase:
            _record_result(
                results=results,
                rule_id=rule_id,
                category="copy",
                severity=severity,
                passed=True,
                checked_count=0,
                failed_count=0,
                message="禁用短语为空，跳过",
            )
            return
        for page_id, page in page_items:
            checked += 1
            desc = str(page.get("page_description") or "").strip()
            sentences = _split_sentences(desc)
            tail_sentences = sentences[1:] if len(sentences) > 1 else []
            tail_text = "。".join(tail_sentences)
            if phrase and phrase in tail_text:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": _normalize_whitespace(tail_text)[:180],
                        "message": f"首句之后仍出现禁用短语: {phrase}",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="首句后禁用短语检查",
        )
        return

    if rule_id == "copy.sentence_count":
        required = int(params.get("required") or 6)
        for page_id, page in page_items:
            checked += 1
            desc = str(page.get("page_description") or "")
            count = len(_split_sentences(desc))
            if count != required:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": _normalize_whitespace(desc)[:180],
                        "message": f"句数不符合要求: {count} != {required}",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="页面句数检查",
        )
        return

    if rule_id == "copy.min_chars":
        required = int(params.get("required") or 300)
        for page_id, page in page_items:
            checked += 1
            desc = str(page.get("page_description") or "")
            char_count = _count_chars(desc)
            if char_count < required:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": _normalize_whitespace(desc)[:180],
                        "message": f"字数不足: {char_count} < {required}",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="页面字数检查",
        )
        return

    if rule_id in {"copy.ban_words", "copy.avoid_terms"}:
        words = [str(x).strip() for x in (params.get("ban_words") or params.get("terms") or []) if str(x).strip()]
        for page_id, page in page_items:
            checked += 1
            desc = str(page.get("page_description") or "")
            hits = [w for w in words if w and w in desc]
            if hits:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": _normalize_whitespace(desc)[:180],
                        "message": f"出现禁用词: {'/'.join(hits[:5])}",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="页面禁用词检查",
        )
        return

    if rule_id == "copy.page_ban_topics":
        topics = [str(x).strip() for x in (params.get("ban_topics") or []) if str(x).strip()]
        for page_id, page in page_items:
            checked += 1
            desc = str(page.get("page_description") or "")
            hits = [w for w in topics if w and w.lower() in desc.lower()]
            if hits:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": _normalize_whitespace(desc)[:180],
                        "message": f"页面描述包含禁用话题: {'/'.join(hits[:5])}",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="页面禁用话题检查",
        )
        return

    if rule_id == "copy.no_date_mentions":
        required = bool(params.get("required", True))
        if not required:
            _record_result(
                results=results,
                rule_id=rule_id,
                category="copy",
                severity=severity,
                passed=True,
                checked_count=0,
                failed_count=0,
                message="未启用日期叙述检查",
            )
            return
        date_patterns = [
            r"(?:19|20)\d{2}[年/\-.]\d{1,2}(?:[月/\-.]\d{1,2}日?)?",
            r"\d{1,2}月\d{1,2}日",
            r"(?:19|20)\d{2}年",
            r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b",
        ]
        combined = re.compile("|".join(date_patterns), flags=re.IGNORECASE)
        for page_id, page in page_items:
            checked += 1
            desc = str(page.get("page_description") or "")
            match = combined.search(desc)
            if match:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": _normalize_whitespace(match.group(0))[:120],
                        "message": "页面描述中存在日期叙述",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="页面日期叙述检查",
        )
        return

    if rule_id == "copy.page_similarity_diversity":
        max_similarity = float(params.get("max_similarity") or 0.98)
        descriptions: List[Tuple[str, str]] = []
        for page_id, page in page_items:
            desc = _normalize_whitespace(str(page.get("page_description") or ""))
            if desc:
                descriptions.append((page_id, desc))
        checked = len(descriptions)
        for idx in range(len(descriptions)):
            left_id, left_text = descriptions[idx]
            for jdx in range(idx + 1, len(descriptions)):
                right_id, right_text = descriptions[jdx]
                score = difflib.SequenceMatcher(a=left_text, b=right_text).ratio()
                if score > max_similarity:
                    failed += 1
                    evidence.append(
                        {
                            "rule_id": rule_id,
                            "severity": severity,
                            "category": "copy",
                            "page_id": left_id,
                            "related_page_id": right_id,
                            "file": "project_plan.json",
                            "line": _find_line_by_snippet(plan_text, left_text),
                            "snippet": f"{left_id}<->{right_id} similarity={score:.3f}",
                            "message": f"页面文案相似度过高（>{max_similarity:.2f}）",
                        }
                    )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="跨页面文案相似度检查",
        )
        return

    if rule_id == "copy.chart_append_sentence":
        value = str(params.get("value") or "").strip()
        if not value:
            _record_result(
                results=results,
                rule_id=rule_id,
                category="copy",
                severity=severity,
                passed=True,
                checked_count=0,
                failed_count=0,
                message="图表附加句为空，跳过",
            )
            return
        for page_id, page in page_items:
            has_chart = page_has_chart(page_id, page)
            if not has_chart:
                continue
            checked += 1
            desc = str(page.get("page_description") or "")
            if value not in desc:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "copy",
                        "page_id": page_id,
                        "file": "project_plan.json",
                        "line": _find_line_by_snippet(plan_text, desc),
                        "snippet": _normalize_whitespace(desc)[:180],
                        "message": "含图表页面缺少指定附加句",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="图表页面附加句检查",
        )
        return

    overview = str(project_intro.get("overview") or "").strip()
    if rule_id == "copy.overview_target_chars":
        required = int(params.get("required") or 250)
        checked = 1
        count = _count_chars(overview)
        failed = 1 if count < required else 0
        if failed:
            evidence.append(
                {
                    "rule_id": rule_id,
                    "severity": severity,
                    "category": "copy",
                    "page_id": "",
                    "file": "project_plan.json",
                    "line": _find_line_by_snippet(plan_text, overview),
                    "snippet": _normalize_whitespace(overview)[:180],
                    "message": f"总述字数不足: {count} < {required}",
                }
            )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="总述长度检查",
        )
        return

    if rule_id == "copy.overview_ban_words":
        words = [str(x).strip() for x in (params.get("ban_words") or []) if str(x).strip()]
        checked = 1
        hits = [w for w in words if w in overview]
        failed = 1 if hits else 0
        if failed:
            evidence.append(
                {
                    "rule_id": rule_id,
                    "severity": severity,
                    "category": "copy",
                    "page_id": "",
                    "file": "project_plan.json",
                    "line": _find_line_by_snippet(plan_text, overview),
                    "snippet": _normalize_whitespace(overview)[:180],
                    "message": f"总述含禁用词: {'/'.join(hits[:8])}",
                }
            )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="总述禁用词检查",
        )
        return

    if rule_id == "copy.overview_ban_topics":
        words = [str(x).strip() for x in (params.get("ban_topics") or []) if str(x).strip()]
        checked = 1
        hits = [w for w in words if w.lower() in overview.lower()]
        failed = 1 if hits else 0
        if failed:
            evidence.append(
                {
                    "rule_id": rule_id,
                    "severity": severity,
                    "category": "copy",
                    "page_id": "",
                    "file": "project_plan.json",
                    "line": _find_line_by_snippet(plan_text, overview),
                    "snippet": _normalize_whitespace(overview)[:180],
                    "message": f"总述包含禁用话题: {'/'.join(hits[:8])}",
                }
            )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="copy",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="总述禁用话题检查",
        )
        return

    _record_result(
        results=results,
        rule_id=rule_id,
        category="copy",
        severity=severity,
        passed=True,
        checked_count=0,
        failed_count=0,
        message="未实现的 copy 规则，默认通过",
    )


def _html_rule_eval(
    *,
    rule_id: str,
    params: Dict[str, Any],
    html_files: List[Path],
    html_texts: Dict[Path, str],
    results: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    severity: str,
) -> None:
    failed = 0
    checked = 0

    if rule_id == "html.no_comments":
        for path in html_files:
            content = html_texts.get(path, "")
            checked += 1
            for regex in (r"<!--[\s\S]*?-->", r"/\*[\s\S]*?\*/"):
                for match in re.finditer(regex, content, flags=re.IGNORECASE):
                    failed += 1
                    evidence.append(
                        {
                            "rule_id": rule_id,
                            "severity": severity,
                            "category": "html",
                            "page_id": path.stem,
                            "file": str(path),
                            "line": _line_of(content, match.start()),
                            "snippet": _normalize_whitespace(match.group(0))[:180],
                            "message": "发现注释，违反 no_comments 约束",
                        }
                    )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="html",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="HTML/CSS 注释检查",
        )
        return

    if rule_id == "html.no_rounded_rectangles":
        for path in html_files:
            content = html_texts.get(path, "")
            checked += 1
            for match in re.finditer(r"border-radius\s*:\s*([^;}{]+)", content, flags=re.IGNORECASE):
                value = str(match.group(1) or "").strip()
                if _is_non_zero_radius(value):
                    failed += 1
                    evidence.append(
                        {
                            "rule_id": rule_id,
                            "severity": severity,
                            "category": "html",
                            "page_id": path.stem,
                            "file": str(path),
                            "line": _line_of(content, match.start()),
                            "snippet": _normalize_whitespace(match.group(0))[:180],
                            "message": "检测到非零圆角样式",
                        }
                    )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="html",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="圆角样式检查",
        )
        return

    if rule_id in {"html.no_external_script", "html.external_script_policy"}:
        # Backward compatibility:
        # - html.no_external_script(required=true) => strict_no_external
        # - html.external_script_policy => fine-grained policy
        mode = str(params.get("mode") or "").strip().lower()
        if not mode:
            required = bool(params.get("required", True))
            mode = "strict_no_external" if required else "allow_all"
        allowed_domains = [str(x).strip().lower() for x in (params.get("allowed_domains") or []) if str(x).strip()]
        vendor_fallback = params.get("vendor_fallback") if isinstance(params.get("vendor_fallback"), dict) else {}
        vendor_echarts = str(vendor_fallback.get("echarts") or "").strip()

        if mode == "allow_all":
            _record_result(
                results=results,
                rule_id=rule_id,
                category="html",
                severity=severity,
                passed=True,
                checked_count=0,
                failed_count=0,
                message="未启用外链脚本限制（allow_all）",
            )
            return

        for path in html_files:
            content = html_texts.get(path, "")
            checked += 1
            if mode == "allowlist_with_vendor_fallback" and vendor_echarts and vendor_echarts not in content:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "html",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": vendor_echarts[:180],
                        "message": "缺少本地 vendor 回退脚本引用",
                    }
                )
            for match in re.finditer(r"<script[^>]+src=['\"]([^'\"]+)['\"]", content, flags=re.IGNORECASE):
                src = str(match.group(1) or "").strip()
                if not _script_src_is_external(src):
                    continue
                if mode == "strict_no_external":
                    failed += 1
                    evidence.append(
                        {
                            "rule_id": rule_id,
                            "severity": severity,
                            "category": "html",
                            "page_id": path.stem,
                            "file": str(path),
                            "line": _line_of(content, match.start()),
                            "snippet": src[:180],
                            "message": "检测到外链 script",
                        }
                    )
                    continue
                if mode == "allowlist_with_vendor_fallback":
                    domain = _script_src_domain(src)
                    if not _domain_allowed(domain, allowed_domains):
                        failed += 1
                        evidence.append(
                            {
                                "rule_id": rule_id,
                                "severity": severity,
                                "category": "html",
                                "page_id": path.stem,
                                "file": str(path),
                                "line": _line_of(content, match.start()),
                                "snippet": src[:180],
                                "message": f"外链 script 域名不在白名单: {domain or 'unknown'}",
                            }
                        )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="html",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message=f"外链脚本策略检查（mode={mode}）",
        )
        return

    if rule_id in {"html.chart_responsive_false", "html.chart_maintain_aspect_ratio_true"}:
        required = bool(params.get("required", True))
        expected_value = bool(params.get("value", rule_id.endswith("true")))
        flag_name = "responsive" if "responsive" in rule_id else "maintainAspectRatio"
        flag_regex = rf"{flag_name}\s*:\s*{'true' if expected_value else 'false'}"
        default_regex = rf"Chart\.defaults\.{flag_name}\s*=\s*{'true' if expected_value else 'false'}"
        for path in html_files:
            content = html_texts.get(path, "")
            has_chart = ("widget_chart_" in content) or ("echarts" in content.lower()) or ("new chart(" in content.lower())
            if not required or not has_chart:
                continue
            checked += 1
            ok = bool(
                re.search(flag_regex, content, flags=re.IGNORECASE)
                or re.search(default_regex, content, flags=re.IGNORECASE)
            )
            if not ok:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "html",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": f"missing {flag_name}={'true' if expected_value else 'false'}",
                        "message": "图表参数未按约束设置",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="html",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message=f"{flag_name} 参数检查",
        )
        return

    _record_result(
        results=results,
        rule_id=rule_id,
        category="html",
        severity=severity,
        passed=True,
        checked_count=0,
        failed_count=0,
        message="未实现的 html 规则，默认通过",
    )


def _extract_buttons(content: str) -> List[Dict[str, Any]]:
    buttons: List[Dict[str, Any]] = []
    clean = re.sub(r"<script[\s\S]*?</script>", "", content, flags=re.IGNORECASE)
    for match in re.finditer(r"<button\b([^>]*)>([\s\S]*?)</button>", clean, flags=re.IGNORECASE):
        attrs = str(match.group(1) or "")
        label = _normalize_whitespace(_strip_html_tags(match.group(2) or ""))
        id_match = re.search(r"\bid=['\"]([^'\"]+)['\"]", attrs, flags=re.IGNORECASE)
        onclick_match = re.search(r"\bonclick=['\"]([^'\"]+)['\"]", attrs, flags=re.IGNORECASE)
        buttons.append(
            {
                "id": str(id_match.group(1)).strip() if id_match else "",
                "label": label,
                "onclick": str(onclick_match.group(1)).strip() if onclick_match else "",
                "offset": match.start(),
            }
        )
    return buttons


def _extract_click_handlers(content: str) -> List[str]:
    handlers: List[str] = []
    for match in re.finditer(
        r"addEventListener\(\s*['\"]click['\"]\s*,\s*(function\s*\([^)]*\)\s*\{[\s\S]*?\}|[a-zA-Z0-9_$.]+)\s*\)",
        content,
        flags=re.IGNORECASE,
    ):
        handlers.append(_normalize_whitespace(match.group(1) or ""))
    return handlers


def _action_rule_eval(
    *,
    rule_id: str,
    params: Dict[str, Any],
    html_files: List[Path],
    html_texts: Dict[Path, str],
    results: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    severity: str,
) -> None:
    checked = 0
    failed = 0

    if rule_id == "action.button_action_unique":
        required = bool(params.get("required", True))
        if not required:
            _record_result(
                results=results,
                rule_id=rule_id,
                category="action",
                severity=severity,
                passed=True,
                checked_count=0,
                failed_count=0,
                message="未启用按钮动作唯一性规则",
            )
            return
        for path in html_files:
            content = html_texts.get(path, "")
            buttons = _extract_buttons(content)
            if not buttons:
                continue
            checked += 1
            button_handlers: Dict[str, str] = {}
            for b in buttons:
                button_id = str(b.get("id") or "").strip()
                if not button_id:
                    continue
                pattern_get = (
                    rf"getElementById\(\s*['\"]{re.escape(button_id)}['\"]\s*\)"
                    rf"\.addEventListener\(\s*['\"]click['\"]\s*,\s*function\s*\([^)]*\)\s*\{{([\s\S]*?)\}}\s*\)"
                )
                pattern_query = (
                    rf"querySelector\(\s*['\"]#{re.escape(button_id)}['\"]\s*\)"
                    rf"\.addEventListener\(\s*['\"]click['\"]\s*,\s*function\s*\([^)]*\)\s*\{{([\s\S]*?)\}}\s*\)"
                )
                m = re.search(pattern_get, content, flags=re.IGNORECASE)
                if not m:
                    m = re.search(pattern_query, content, flags=re.IGNORECASE)
                if m:
                    button_handlers[button_id] = _normalize_whitespace(m.group(1) or "")
                elif b.get("onclick"):
                    button_handlers[button_id] = _normalize_whitespace(str(b.get("onclick") or ""))

            body_hashes: List[str] = [hashlib.md5(v.encode("utf-8")).hexdigest()[:12] for v in button_handlers.values() if v]
            if len(buttons) <= 1:
                if len(body_hashes) == 0:
                    failed += 1
                    evidence.append(
                        {
                            "rule_id": rule_id,
                            "severity": severity,
                            "category": "action",
                            "page_id": path.stem,
                            "file": str(path),
                            "line": 1,
                            "snippet": "missing click handlers",
                            "message": "按钮存在但未绑定动作",
                        }
                    )
                continue
            if len(body_hashes) <= 1:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "action",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": "insufficient action handlers",
                        "message": "按钮存在但动作处理不足，无法证明“各自有具体功能”",
                    }
                )
                continue
            if len(button_handlers) < len([x for x in buttons if str(x.get("id") or "").strip()]):
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "action",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": f"mapped_handlers={len(button_handlers)}, buttons={len(buttons)}",
                        "message": "部分按钮未绑定独立动作",
                    }
                )
                continue
            if len(set(body_hashes)) < len(body_hashes):
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "action",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": f"handlers={len(body_hashes)}, unique={len(set(body_hashes))}",
                        "message": "按钮动作存在重复实现",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="action",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="按钮动作唯一性检查",
        )
        return

    if rule_id == "action.button_id_coverage":
        required = bool(params.get("required", True))
        if not required:
            _record_result(
                results=results,
                rule_id=rule_id,
                category="action",
                severity=severity,
                passed=True,
                checked_count=0,
                failed_count=0,
                message="未启用按钮ID覆盖规则",
            )
            return
        for path in html_files:
            content = html_texts.get(path, "")
            buttons = _extract_buttons(content)
            if not buttons:
                continue
            checked += 1
            missing_id = [b for b in buttons if not b.get("id")]
            if missing_id:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "action",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": f"missing_ids={len(missing_id)}",
                        "message": "存在无ID按钮，无法稳定绑定行为",
                    }
                )
                continue
            ids = [str(b.get("id") or "") for b in buttons if str(b.get("id") or "").strip()]
            referenced = 0
            for bid in ids:
                if re.search(rf"getElementById\(\s*['\"]{re.escape(bid)}['\"]\s*\)", content):
                    referenced += 1
                    continue
                if re.search(rf"querySelector\(\s*['\"]#{re.escape(bid)}['\"]\s*\)", content):
                    referenced += 1
            ratio = (referenced / len(ids)) if ids else 1.0
            if ratio < 0.85:
                failed += 1
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "action",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": f"id_ref_ratio={ratio:.2f}",
                        "message": "按钮ID绑定覆盖率不足（<85%）",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="action",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="按钮ID覆盖率检查",
        )
        return

    if rule_id == "action.showmodal_dom_sequence":
        api = str(params.get("api") or "showModal")
        for path in html_files:
            content = html_texts.get(path, "")
            buttons = _extract_buttons(content)
            if not buttons:
                continue
            checked += 1
            has_api = bool(re.search(rf"\b{re.escape(api)}\b", content))
            has_create = "document.createElement(" in content
            has_innerhtml = ".innerHTML" in content
            has_append = "document.body.appendChild(" in content
            has_cancel = bool(re.search(r"(取消|cancel)", content, flags=re.IGNORECASE))
            has_confirm = bool(re.search(r"(确认|confirm)", content, flags=re.IGNORECASE))
            has_listener = bool(re.search(r"addEventListener\(\s*['\"]click['\"]", content, flags=re.IGNORECASE))
            passed_file = all([has_api, has_create, has_innerhtml, has_append, has_cancel, has_confirm, has_listener])
            if not passed_file:
                failed += 1
                missing = []
                if not has_api:
                    missing.append(api)
                if not has_create:
                    missing.append("document.createElement")
                if not has_innerhtml:
                    missing.append("innerHTML")
                if not has_append:
                    missing.append("appendChild")
                if not has_cancel:
                    missing.append("cancel")
                if not has_confirm:
                    missing.append("confirm")
                if not has_listener:
                    missing.append("click_listener")
                evidence.append(
                    {
                        "rule_id": rule_id,
                        "severity": severity,
                        "category": "action",
                        "page_id": path.stem,
                        "file": str(path),
                        "line": 1,
                        "snippet": ",".join(missing),
                        "message": "弹窗DOM序列不完整",
                    }
                )
        _record_result(
            results=results,
            rule_id=rule_id,
            category="action",
            severity=severity,
            passed=(failed == 0),
            checked_count=checked,
            failed_count=failed,
            message="showModal DOM序列检查",
        )
        return

    _record_result(
        results=results,
        rule_id=rule_id,
        category="action",
        severity=severity,
        passed=True,
        checked_count=0,
        failed_count=0,
        message="未实现的 action 规则，默认通过",
    )


def validate_runtime_skill_compliance(
    project_name: str,
    project_dir: Path,
    html_dir: Path,
    runtime_rule_graph: Optional[Dict[str, Any]] = None,
    write_report: bool = True,
) -> Tuple[bool, Path, Dict[str, Any]]:
    project_dir = Path(project_dir)
    html_dir = Path(html_dir)
    report_path = project_dir / "skill_compliance_report.json"
    plan_path = project_dir / "project_plan.json"
    runtime_skill_plan_path = project_dir / "runtime_skill_plan.json"

    runtime_skill_plan = _load_json(runtime_skill_plan_path)
    if runtime_rule_graph and isinstance(runtime_rule_graph, dict):
        graph = runtime_rule_graph
        graph_path = project_dir / "runtime_rule_graph.json"
        if write_report and not graph_path.exists():
            _save_json(graph_path, graph)
    else:
        graph, graph_path = _load_runtime_rule_graph(project_dir)

    nodes = (((graph.get("graph") or {}).get("nodes") or []) if isinstance(graph, dict) else [])
    if not isinstance(nodes, list):
        nodes = []
    policy = graph.get("policy") or {}
    min_ratio = float(policy.get("min_rule_pass_ratio") or 0.85)
    critical_rule_ids = [str(x) for x in (policy.get("critical_rule_ids") or []) if str(x).strip()]

    plan = _load_json(plan_path)
    plan_text = _read_text(plan_path)
    html_files = _collect_html_files(html_dir)
    html_texts = {path: _read_text(path) for path in html_files}
    html_map = {path.name: text for path, text in html_texts.items()}
    html_map.update({path.stem: text for path, text in html_texts.items()})

    rule_results: List[Dict[str, Any]] = []
    evidence_trace: List[Dict[str, Any]] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        rule_id = str(node.get("rule_id") or "").strip()
        if not rule_id:
            continue
        category = str(node.get("category") or "").strip() or "unknown"
        severity = str(node.get("severity") or "").strip() or "minor"
        params = node.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if category == "copy":
            _copy_rule_eval(
                rule_id=rule_id,
                params=params,
                plan=plan,
                html_map=html_map,
                plan_text=plan_text,
                results=rule_results,
                evidence=evidence_trace,
                severity=severity,
            )
        elif category == "html":
            _html_rule_eval(
                rule_id=rule_id,
                params=params,
                html_files=html_files,
                html_texts=html_texts,
                results=rule_results,
                evidence=evidence_trace,
                severity=severity,
            )
        elif category == "action":
            _action_rule_eval(
                rule_id=rule_id,
                params=params,
                html_files=html_files,
                html_texts=html_texts,
                results=rule_results,
                evidence=evidence_trace,
                severity=severity,
            )
        else:
            _record_result(
                results=rule_results,
                rule_id=rule_id,
                category=category,
                severity=severity,
                passed=True,
                checked_count=0,
                failed_count=0,
                message="未知分类规则，默认通过",
            )

    total_rules = len(rule_results)
    passed_rules = len([x for x in rule_results if bool(x.get("passed"))])
    failed_rules = total_rules - passed_rules
    pass_ratio = (passed_rules / total_rules) if total_rules > 0 else 0.0

    failed_rule_ids = [str(x.get("rule_id") or "") for x in rule_results if not bool(x.get("passed"))]
    critical_failed = []
    for item in rule_results:
        if bool(item.get("passed")):
            continue
        rid = str(item.get("rule_id") or "")
        if rid in critical_rule_ids or str(item.get("severity")) == "critical":
            critical_failed.append(rid)
    critical_failed = sorted(list(set(critical_failed)))
    enriched_evidence = _enrich_evidence_trace(evidence_trace, project_dir=project_dir, html_dir=html_dir)
    preview = [
        item
        for item in enriched_evidence
        if str(item.get("severity") or "").strip().lower() in {"critical", "major"}
    ][:30]
    if not preview:
        preview = enriched_evidence[:30]
    evidence_group_counter: Dict[str, int] = {}
    for item in enriched_evidence:
        group = str(item.get("source_group") or "unknown")
        evidence_group_counter[group] = int(evidence_group_counter.get(group) or 0) + 1

    passed = (pass_ratio >= min_ratio) and (len(critical_failed) == 0)
    report = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_rule_graph_path": str(graph_path),
        "runtime_skill_plan_path": str(runtime_skill_plan_path),
        "project_plan_path": str(plan_path),
        "html_dir": str(html_dir),
        "policy": {
            "min_rule_pass_ratio": min_ratio,
            "critical_rule_ids": critical_rule_ids,
            "max_auto_repair_rounds": int(policy.get("max_auto_repair_rounds") or 2),
        },
        "summary": {
            "passed": passed,
            "total_rules": total_rules,
            "passed_rules": passed_rules,
            "failed_rules": failed_rules,
            "rule_pass_ratio": round(pass_ratio, 4),
            "critical_failed_rules": critical_failed,
            "failed_rule_ids": failed_rule_ids,
            "evidence_trace_count": len(enriched_evidence),
            "evidence_preview_count": len(preview),
            "evidence_group_counter": evidence_group_counter,
            "runtime_skillpack_id": str((runtime_skill_plan.get("skillpack") or {}).get("id") or ""),
        },
        "rules": rule_results,
        "evidence_trace": enriched_evidence[:1000],
        "evidence_preview": preview,
    }

    if write_report:
        _save_json(report_path, report)
    return passed, report_path, report
