"""
Runtime skill auto-repair runner.

Repairs only failed pages/files and reruns compliance checks up to max rounds.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urlparse

from modules.runtime_skill_engine import resolve_external_script_policy
from modules.skill_compliance_validator import validate_runtime_skill_compliance
from modules.vendor_assets import ensure_vendor_assets_for_html_dir


POLICY_ACTION_PREFIX_MAP: Dict[str, Set[str]] = {
    "rewrite_failed_page_copy": {"copy."},
    "repair_failed_html_structure": {"html."},
    "repair_failed_button_actions": {"action."},
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


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _sanitize_copy_text(text: str, ban_words: List[str], avoid_terms: List[str], replacement_map: Dict[str, Any]) -> str:
    output = str(text or "")
    for source, target in (replacement_map or {}).items():
        s = str(source or "").strip()
        t = str(target or "").strip()
        if s:
            output = output.replace(s, t)
    for w in list(ban_words or []) + list(avoid_terms or []):
        token = str(w or "").strip()
        if token:
            output = output.replace(token, "")
    return output


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
    for item in [str(x).strip().lower() for x in (allowed_domains or []) if str(x).strip()]:
        if host == item or host.endswith(f".{item}"):
            return True
    return False


def _rewrite_external_scripts(content: str, script_policy: Dict[str, Any]) -> Tuple[str, int]:
    mode = str((script_policy or {}).get("mode") or "allowlist_with_vendor_fallback").strip().lower()
    allowed_domains = [str(x).strip().lower() for x in ((script_policy or {}).get("allowed_domains") or []) if str(x).strip()]
    vendor_fallback = (script_policy or {}).get("vendor_fallback") or {}
    vendor_echarts = str(vendor_fallback.get("echarts") or "vendor/echarts/5.4.3/echarts.min.js").strip()

    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        full = str(match.group(0) or "")
        src = str(match.group(1) or "").strip()
        if not _script_src_is_external(src):
            return full
        if mode == "allow_all":
            return full
        if mode == "allowlist_with_vendor_fallback":
            domain = _script_src_domain(src)
            if _domain_allowed(domain, allowed_domains):
                return full
        changed += 1
        return ""

    updated = re.sub(
        r"<script[^>]+src=['\"]([^'\"]+)['\"][^>]*>\s*</script>",
        repl,
        content,
        flags=re.IGNORECASE,
    )

    if mode in {"strict_no_external", "allowlist_with_vendor_fallback"} and vendor_echarts and vendor_echarts not in updated:
        snippet = f"<script src=\"{vendor_echarts}\"></script>"
        if "</head>" in updated.lower():
            updated = re.sub(r"</head>", snippet + "\n</head>", updated, flags=re.IGNORECASE)
        elif "</body>" in updated.lower():
            updated = re.sub(r"</body>", snippet + "\n</body>", updated, flags=re.IGNORECASE)
        else:
            updated += "\n" + snippet
        changed += 1
    return updated, changed


def _build_page_copy(
    page_title: str,
    *,
    first_sentence_prefix: str,
    include_chart_sentence: str,
    ban_words: List[str],
    avoid_terms: List[str],
    replacement_map: Dict[str, Any],
) -> str:
    title = str(page_title or "业务页").strip() or "业务页"
    prefix = str(first_sentence_prefix or "本页面").strip() or "本页面"
    chart_sentence = str(include_chart_sentence or "").strip()

    sentences = [
        f"{prefix}围绕{title}组织日常录入、查询与状态变更操作，页面中的输入框、下拉框和按钮按照处理顺序排列。",
        f"{title}支持先填写筛选条件再执行查询按钮，查询结果在列表中保留当前筛选上下文，避免重复输入。",
        f"{title}提供新增与编辑入口，点击对应按钮后弹出填写窗口，确认后立即写入当前记录并更新状态字段。",
        f"{title}中的下拉框用于选择处理类型、优先级和责任项，切换选项后会联动展示不同字段与校验提示。",
        f"{title}把处理记录、时间戳和操作说明写入同一视图，便于对照前后差异并复核执行结果。",
        f"{title}支持在同一页面完成结果确认、导出和回看，不需要跳转额外页面即可核对本次操作留痕。",
    ]
    if chart_sentence:
        sentences[-1] = chart_sentence

    def _compose(texts: List[str]) -> str:
        return "。".join([s.strip("。 ") for s in texts if s.strip()]) + "。"

    merged = _sanitize_copy_text(
        _compose(sentences),
        ban_words=ban_words,
        avoid_terms=avoid_terms,
        replacement_map=replacement_map,
    )
    if len(re.sub(r"\s+", "", merged)) < 320:
        extension = "并记录每次提交前后的字段变化，在弹窗中展示必要的校验提示与处理说明，保证操作链路能够被完整复核"
        if len(sentences) >= 2:
            sentences[-2] = sentences[-2].rstrip("。 ") + f"，{extension}。"
        else:
            sentences[-1] = sentences[-1].rstrip("。 ") + f"，{extension}。"
        merged = _sanitize_copy_text(
            _compose(sentences),
            ban_words=ban_words,
            avoid_terms=avoid_terms,
            replacement_map=replacement_map,
        )
    return merged


def _build_overview_copy(
    project_name: str,
    target_chars: int,
    ban_words: List[str],
    replacement_map: Dict[str, Any],
) -> str:
    name = str(project_name or "本系统").strip() or "本系统"
    base = (
        f"{name}用于处理日常业务数据的录入、查询、审核、归档和统计工作。"
        f"系统把页面操作和后台接口按统一规则串联，首页提供关键数据入口，业务页提供筛选、表单提交和状态流转。"
        f"用户在同一套页面中可以完成事项登记、记录跟进、异常处理、结果复核和报表导出。"
        f"每次操作都会生成可回溯记录，包含时间、处理动作和变更字段。"
        f"系统支持按照角色显示不同操作入口，并在提交前执行必填与格式校验，避免错误数据进入后续流程。"
        f"项目输出的页面截图、接口映射和代码定位信息保持一致，便于按材料要求完成文档编制与核查。"
    )
    text = _sanitize_copy_text(base, ban_words=ban_words, avoid_terms=[], replacement_map=replacement_map)
    if len(re.sub(r"\s+", "", text)) < max(250, int(target_chars or 250)):
        text += (
            "系统还提供批量处理、条件组合筛选和流程回看能力，支持按处理状态、时间范围和责任对象进行组合检索，"
            "并在页面内直接完成确认与回退操作。"
        )
    return text


def _repair_project_plan_copy(
    project_name: str,
    project_dir: Path,
    failed_page_ids: Set[str],
    failed_rule_ids: Set[str],
    constraints: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    plan_path = Path(project_dir) / "project_plan.json"
    plan = _load_json(plan_path)
    if not plan:
        return False, []

    page_rules = constraints.get("page_narration") or {}
    overview_rules = constraints.get("overview_copy") or {}
    first_prefix = str(page_rules.get("first_sentence_prefix") or "本页面")
    chart_sentence = str(page_rules.get("chart_append_sentence") or "").strip()
    ban_words = [str(x) for x in (page_rules.get("ban_words") or []) if str(x).strip()]
    avoid_terms = [str(x) for x in (page_rules.get("avoid_terms") or []) if str(x).strip()]
    replacement_map = page_rules.get("replacement_map") or {}
    if not isinstance(replacement_map, dict):
        replacement_map = {}

    changed_pages: List[str] = []
    pages = plan.get("pages") or {}
    if isinstance(pages, dict):
        for page_id, page in pages.items():
            if not isinstance(page, dict):
                continue
            pid = str(page_id)
            if failed_page_ids and pid not in failed_page_ids:
                continue
            page["page_description"] = _build_page_copy(
                str(page.get("page_title") or pid),
                first_sentence_prefix=first_prefix,
                include_chart_sentence=chart_sentence,
                ban_words=ban_words,
                avoid_terms=avoid_terms,
                replacement_map=replacement_map,
            )
            changed_pages.append(pid)

    if {"copy.overview_target_chars", "copy.overview_ban_words", "copy.overview_ban_topics"} & failed_rule_ids:
        intro = plan.get("project_intro") or {}
        if not isinstance(intro, dict):
            intro = {}
        target_chars = int(overview_rules.get("target_chars") or 250)
        overview_ban = [str(x) for x in (overview_rules.get("ban_words") or []) if str(x).strip()]
        intro["overview"] = _build_overview_copy(
            project_name=project_name,
            target_chars=target_chars,
            ban_words=overview_ban,
            replacement_map=replacement_map,
        )
        plan["project_intro"] = intro

    if not changed_pages and not ({"copy.overview_target_chars", "copy.overview_ban_words", "copy.overview_ban_topics"} & failed_rule_ids):
        return False, []

    _save_json(plan_path, plan)
    return True, changed_pages


def _ensure_button_ids(content: str) -> Tuple[str, List[Tuple[str, str]]]:
    assigned: List[Tuple[str, str]] = []
    counter = 0
    scripts: List[str] = []

    def stash_script(match: re.Match[str]) -> str:
        scripts.append(match.group(0))
        return f"__SKILL_SCRIPT_PLACEHOLDER_{len(scripts) - 1}__"

    masked = re.sub(r"<script[\s\S]*?</script>", stash_script, content, flags=re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        nonlocal counter
        attrs = str(match.group(1) or "")
        label_raw = str(match.group(2) or "")
        label = re.sub(r"<[^>]+>", "", label_raw).strip()
        if re.search(r"\bid=['\"]([^'\"]+)['\"]", attrs, flags=re.IGNORECASE):
            id_val = re.search(r"\bid=['\"]([^'\"]+)['\"]", attrs, flags=re.IGNORECASE)
            if id_val:
                assigned.append((str(id_val.group(1)).strip(), label))
            return match.group(0)
        counter += 1
        button_id = f"btn_skill_{counter}"
        attrs = attrs.rstrip() + f" id=\"{button_id}\""
        assigned.append((button_id, label))
        return f"<button{attrs}>{label_raw}</button>"

    updated = re.sub(r"<button\b([^>]*)>([\s\S]*?)</button>", repl, masked, flags=re.IGNORECASE)
    for idx, script in enumerate(scripts):
        updated = updated.replace(f"__SKILL_SCRIPT_PLACEHOLDER_{idx}__", script)
    return updated, assigned


def _collect_button_ids(content: str) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    masked = re.sub(r"<script[\s\S]*?</script>", "", content, flags=re.IGNORECASE)
    for match in re.finditer(r"<button\b([^>]*)>([\s\S]*?)</button>", masked, flags=re.IGNORECASE):
        attrs = str(match.group(1) or "")
        label = re.sub(r"<[^>]+>", "", str(match.group(2) or "")).strip()
        id_match = re.search(r"\bid=['\"]([^'\"]+)['\"]", attrs, flags=re.IGNORECASE)
        if id_match:
            result.append((str(id_match.group(1)).strip(), label))
    return result


def _build_action_script(buttons: List[Tuple[str, str]]) -> str:
    if not buttons:
        return ""
    button_lines = []
    for idx, (bid, label) in enumerate(buttons, start=1):
        title = label or f"操作{idx}"
        body = (
            f"<p>{title}需要填写本次操作说明，并确认处理对象、状态和时间信息。</p>"
            f"<p>确认后将写入当前记录并刷新列表状态，序号 {idx}。</p>"
        )
        safe_title = title.replace("'", "\\'")
        safe_body = body.replace("'", "\\'")
        safe_bid = bid.replace("'", "\\'")
        button_lines.append(
            "document.getElementById('{bid}').addEventListener('click', function(ev) {{"
            "ev.preventDefault();"
            "var actionKey='skill_action_{idx}_{bid}';"
            "window.__skill_last_action=actionKey;"
            "openSkillModal('{title}','{body}<p>按钮标识：{bid}</p><p>动作编号：{idx}</p>');"
            "}});".format(
                bid=safe_bid,
                idx=idx,
                title=safe_title,
                body=safe_body,
            )
        )

    body = "\n".join(button_lines)
    return f"""
<script id="skill-action-repair">
(function() {{
  function openSkillModal(title, bodyHtml) {{
    var dialog = document.createElement('dialog');
    dialog.className = 'skill-modal';
    dialog.innerHTML = '<form method="dialog" style="padding:16px;border:1px solid #d0d7de;border-radius:0;background:#ffffff;min-width:420px;">'
      + '<h3 style="margin:0 0 8px 0;">' + title + '</h3>'
      + '<div style="font-size:14px;line-height:1.6;margin-bottom:12px;">' + bodyHtml + '</div>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end;">'
      + '<button id="skill-cancel" value="cancel" style="border-radius:0;">取消</button>'
      + '<button id="skill-confirm" value="confirm" style="border-radius:0;">确认</button>'
      + '</div></form>';
    document.body.appendChild(dialog);
    var cancelBtn = dialog.querySelector('#skill-cancel');
    var confirmBtn = dialog.querySelector('#skill-confirm');
    cancelBtn.addEventListener('click', function() {{
      dialog.close();
      dialog.remove();
    }});
    confirmBtn.addEventListener('click', function() {{
      dialog.close();
      dialog.remove();
    }});
    if (typeof dialog.showModal === 'function') {{
      dialog.showModal();
    }} else {{
      dialog.setAttribute('open', 'open');
    }}
  }}
  function attachAction(buttonId, title, bodyHtml) {{
    var btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.addEventListener('click', function(ev) {{
      ev.preventDefault();
      openSkillModal(title, bodyHtml);
    }});
  }}
  {body}
  if (window.Chart && window.Chart.defaults) {{
    window.Chart.defaults.responsive = false;
    window.Chart.defaults.maintainAspectRatio = true;
  }}
}})();
</script>
""".strip()


def _repair_html_file(path: Path, script_policy: Dict[str, Any]) -> Tuple[bool, List[str]]:
    content = _read_text(path)
    if not content:
        return False, []
    original = content
    actions: List[str] = []

    # Remove HTML/CSS comments.
    content = re.sub(r"<!--[\s\S]*?-->", "", content, flags=re.IGNORECASE)
    content = re.sub(r"/\*[\s\S]*?\*/", "", content, flags=re.IGNORECASE)

    # Rewrite external scripts according to allowlist policy instead of blanket deletion.
    content, external_rewritten = _rewrite_external_scripts(content, script_policy=script_policy)
    if external_rewritten > 0:
        actions.append("rewrite_external_scripts")

    # Force no rounded rectangles.
    content = re.sub(r"border-radius\s*:\s*([^;}{]+)", "border-radius: 0", content, flags=re.IGNORECASE)

    # Remove previous injected block.
    content = re.sub(
        r"<script id=\"skill-action-repair\">[\s\S]*?</script>",
        "",
        content,
        flags=re.IGNORECASE,
    )

    # Ensure button ids and inject unique action handlers.
    content, _ = _ensure_button_ids(content)
    button_pairs = _collect_button_ids(content)
    if button_pairs:
        action_script = _build_action_script(button_pairs)
        if action_script:
            if "</body>" in content.lower():
                content = re.sub(r"</body>", action_script + "\n</body>", content, flags=re.IGNORECASE)
            else:
                content += "\n" + action_script
            actions.append("inject_button_actions")

    # Ensure chart flags exist (Chart.js fallback defaults).
    if "responsive" not in content or "maintainAspectRatio" not in content:
        snippet = (
            "<script id=\"skill-chart-defaults\">"
            "if(window.Chart&&window.Chart.defaults){"
            "window.Chart.defaults.responsive=false;"
            "window.Chart.defaults.maintainAspectRatio=true;"
            "}</script>"
        )
        if "</body>" in content.lower():
            content = re.sub(r"</body>", snippet + "\n</body>", content, flags=re.IGNORECASE)
        else:
            content += "\n" + snippet
        actions.append("inject_chart_defaults")

    # Final cleanup: remove double blank lines.
    content = re.sub(r"\n{3,}", "\n\n", content)

    if content == original:
        return False, []
    _write_text(path, content)
    actions.extend(["remove_comments", "remove_rounded_corners"])
    return True, sorted(set(actions))


def _repair_html_and_actions(
    html_dir: Path,
    target_files: Set[str],
    script_policy: Dict[str, Any],
) -> Tuple[List[str], Dict[str, List[str]]]:
    changed: List[str] = []
    file_actions: Dict[str, List[str]] = {}
    html_files = sorted([p for p in Path(html_dir).glob("*.html") if p.is_file()]) if Path(html_dir).exists() else []

    for html_file in html_files:
        if target_files and str(html_file) not in target_files and html_file.name not in target_files:
            continue
        ok, actions = _repair_html_file(html_file, script_policy=script_policy)
        if ok:
            changed.append(str(html_file))
            file_actions[str(html_file)] = actions
    return changed, file_actions


def run_skill_autorepair(
    project_name: str,
    project_dir: Path,
    html_dir: Path,
    max_rounds: int = 2,
    policy_actions: List[str] | None = None,
) -> Dict[str, Any]:
    project_dir = Path(project_dir)
    html_dir = Path(html_dir)
    report_path = project_dir / "skill_autorepair_report.json"

    runtime_skill_plan = _load_json(project_dir / "runtime_skill_plan.json")
    constraints = runtime_skill_plan.get("constraints") or {}
    if not isinstance(constraints, dict):
        constraints = {}
    script_policy = resolve_external_script_policy((constraints.get("frontend") or {}))
    ensure_vendor_assets_for_html_dir(
        html_dir=html_dir,
        frontend_constraints=(constraints.get("frontend") or {}),
    )

    rounds: List[Dict[str, Any]] = []
    max_rounds = max(1, int(max_rounds))
    requested_policy_actions = [str(x).strip() for x in (policy_actions or []) if str(x).strip()]
    selected_prefixes: Set[str] = set()
    use_policy_scope = bool(requested_policy_actions)
    if requested_policy_actions:
        for action in requested_policy_actions:
            selected_prefixes.update(POLICY_ACTION_PREFIX_MAP.get(action, set()))

    final_ok = False
    final_report_path = project_dir / "skill_compliance_report.json"
    final_report: Dict[str, Any] = {}

    for round_idx in range(1, max_rounds + 1):
        before_ok, before_path, before_report = validate_runtime_skill_compliance(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            write_report=True,
        )
        final_report_path = before_path
        final_report = before_report
        if before_ok:
            final_ok = True
            rounds.append(
                {
                    "round": round_idx,
                    "before_passed": True,
                    "after_passed": True,
                    "changed_pages": [],
                    "changed_files": [],
                    "file_actions": {},
                    "failed_rules_before": [],
                    "failed_rules_after": [],
                }
            )
            break

        failed_rule_ids = set(str(x) for x in ((before_report.get("summary") or {}).get("failed_rule_ids") or []) if str(x).strip())
        evidence = before_report.get("evidence_trace") or []
        failed_pages: Set[str] = set()
        failed_files: Set[str] = set()
        for item in evidence:
            if not isinstance(item, dict):
                continue
            page_id = str(item.get("page_id") or "").strip()
            file_name = str(item.get("file") or "").strip()
            if page_id:
                failed_pages.add(page_id)
            if file_name:
                failed_files.add(file_name)

        changed_pages: List[str] = []
        changed_files: List[str] = []
        file_actions: Dict[str, List[str]] = {}

        if use_policy_scope:
            allow_copy = "copy." in selected_prefixes
            allow_html = "html." in selected_prefixes
            allow_action = "action." in selected_prefixes
        else:
            allow_copy = True
            allow_html = True
            allow_action = True

        if allow_copy and any(x.startswith("copy.") for x in failed_rule_ids):
            changed_copy, pages = _repair_project_plan_copy(
                project_name=project_name,
                project_dir=project_dir,
                failed_page_ids=failed_pages,
                failed_rule_ids=failed_rule_ids,
                constraints=constraints,
            )
            if changed_copy:
                changed_pages = pages

        if (allow_html or allow_action) and any(
            (allow_html and x.startswith("html.")) or (allow_action and x.startswith("action."))
            for x in failed_rule_ids
        ):
            changed_files, file_actions = _repair_html_and_actions(
                html_dir=html_dir,
                target_files=failed_files,
                script_policy=script_policy,
            )

        after_ok, after_path, after_report = validate_runtime_skill_compliance(
            project_name=project_name,
            project_dir=project_dir,
            html_dir=html_dir,
            write_report=True,
        )
        final_ok = after_ok
        final_report_path = after_path
        final_report = after_report

        rounds.append(
            {
                "round": round_idx,
                "before_passed": bool(before_ok),
                "after_passed": bool(after_ok),
                "changed_pages": changed_pages,
                "changed_files": changed_files,
                "file_actions": file_actions,
                "failed_rules_before": sorted(list(failed_rule_ids)),
                "failed_rules_after": sorted(
                    [str(x) for x in ((after_report.get("summary") or {}).get("failed_rule_ids") or []) if str(x).strip()]
                ),
            }
        )

        if after_ok:
            break
        if not changed_pages and not changed_files:
            break

    output = {
        "project_name": project_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "attempted": True,
        "fixed": bool(final_ok),
        "max_rounds": max_rounds,
        "requested_policy_actions": requested_policy_actions,
        "policy_scope_enabled": use_policy_scope,
        "selected_prefixes": sorted(list(selected_prefixes)),
        "rounds": rounds,
        "final_compliance_report_path": str(final_report_path),
        "final_summary": final_report.get("summary") or {},
    }
    _save_json(report_path, output)
    output["report_path"] = str(report_path)
    return output
