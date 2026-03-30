import json
from pathlib import Path

from modules.skill_compliance_validator import validate_runtime_skill_compliance


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_skill_compliance_validator_detects_critical_failures(tmp_path: Path):
    project_name = "校验失败项目"
    project_dir = tmp_path / project_name
    html_dir = tmp_path / "html"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "project_intro": {"overview": "这是一个AI辅助系统。"},
            "pages": {
                "page_1": {
                    "page_title": "首页",
                    "page_description": "页面说明不合规",
                }
            },
        },
    )
    _write_json(project_dir / "runtime_skill_plan.json", {"skillpack": {"id": "skill"}})
    _write_json(
        project_dir / "runtime_rule_graph.json",
        {
            "policy": {
                "min_rule_pass_ratio": 0.85,
                "critical_rule_ids": ["copy.first_sentence_prefix", "action.showmodal_dom_sequence"],
            },
            "graph": {
                "nodes": [
                    {"rule_id": "copy.first_sentence_prefix", "category": "copy", "severity": "critical", "params": {"prefix": "本页面"}},
                    {"rule_id": "copy.overview_ban_topics", "category": "copy", "severity": "critical", "params": {"ban_topics": ["AI", "智能"]}},
                    {"rule_id": "action.showmodal_dom_sequence", "category": "action", "severity": "critical", "params": {"api": "showModal"}},
                ]
            },
        },
    )
    (html_dir / "page_1.html").write_text("<html><body><button>查询</button></body></html>", encoding="utf-8")

    ok, report_path, report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert ok is False
    assert report_path.exists()
    critical_failed = (report.get("summary") or {}).get("critical_failed_rules") or []
    assert "copy.first_sentence_prefix" in critical_failed
    assert "action.showmodal_dom_sequence" in critical_failed
    assert int((report.get("summary") or {}).get("evidence_trace_count") or 0) > 0
    preview = report.get("evidence_preview") or []
    assert isinstance(preview, list) and len(preview) > 0
    assert str((preview[0] or {}).get("jump_anchor") or "").strip() != ""


def test_skill_compliance_validator_passes_when_rules_satisfied(tmp_path: Path):
    project_name = "校验通过项目"
    project_dir = tmp_path / project_name
    html_dir = tmp_path / "html"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    text = (
        "本页面用于处理查询和提交动作，输入框、下拉框和按钮按照操作顺序排列。"
        "首页支持先筛选再查询，查询后保留筛选条件并联动结果区域。"
        "用户点击新增按钮后弹出填写窗口，确认后写入记录并更新状态。"
        "下拉框用于选择处理类型和优先级，选择后会显示对应校验提示。"
        "页面记录每次提交前后的字段变化，便于复核和回看。"
        "首页支持结果确认和导出，处理记录与时间信息会同步留痕。"
    )
    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "project_intro": {"overview": "该系统用于业务录入和处理，不包含禁用话题内容。"},
            "pages": {"page_1": {"page_title": "首页", "page_description": text}},
        },
    )
    _write_json(project_dir / "runtime_skill_plan.json", {"skillpack": {"id": "skill"}})
    _write_json(
        project_dir / "runtime_rule_graph.json",
        {
            "policy": {
                "min_rule_pass_ratio": 0.85,
                "critical_rule_ids": ["copy.first_sentence_prefix", "action.showmodal_dom_sequence"],
            },
            "graph": {
                "nodes": [
                    {"rule_id": "copy.first_sentence_prefix", "category": "copy", "severity": "critical", "params": {"prefix": "本页面"}},
                    {"rule_id": "copy.sentence_count", "category": "copy", "severity": "major", "params": {"required": 6}},
                    {"rule_id": "copy.min_chars", "category": "copy", "severity": "major", "params": {"required": 80}},
                    {"rule_id": "html.no_comments", "category": "html", "severity": "major", "params": {"required": True}},
                    {"rule_id": "html.no_rounded_rectangles", "category": "html", "severity": "major", "params": {"required": True}},
                    {"rule_id": "action.button_action_unique", "category": "action", "severity": "critical", "params": {"required": True}},
                    {"rule_id": "action.button_id_coverage", "category": "action", "severity": "major", "params": {"required": True}},
                    {"rule_id": "action.showmodal_dom_sequence", "category": "action", "severity": "critical", "params": {"api": "showModal"}},
                ]
            },
        },
    )
    html = """
<html><body>
<button id="btn_query">查询</button>
<script>
function openModal(){
  var dialog=document.createElement('dialog');
  dialog.innerHTML='<button id="cancel">取消</button><button id="confirm">确认</button>';
  document.body.appendChild(dialog);
  document.getElementById('cancel').addEventListener('click', function(){ dialog.close(); dialog.remove(); });
  document.getElementById('confirm').addEventListener('click', function(){ dialog.close(); dialog.remove(); });
  dialog.showModal();
}
document.getElementById('btn_query').addEventListener('click', function(){ openModal(); });
</script>
</body></html>
"""
    (html_dir / "page_1.html").write_text(html, encoding="utf-8")

    ok, _, report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert ok is True
    assert (report.get("summary") or {}).get("critical_failed_rules") == []


def test_skill_compliance_validator_external_script_policy_allowlist(tmp_path: Path):
    project_name = "外链白名单项目"
    project_dir = tmp_path / project_name
    html_dir = tmp_path / "html_allowlist"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    _write_json(project_dir / "project_plan.json", {"project_name": project_name, "pages": {}})
    _write_json(project_dir / "runtime_skill_plan.json", {"skillpack": {"id": "skill"}})
    _write_json(
        project_dir / "runtime_rule_graph.json",
        {
            "policy": {"min_rule_pass_ratio": 0.85, "critical_rule_ids": []},
            "graph": {
                "nodes": [
                    {
                        "rule_id": "html.external_script_policy",
                        "category": "html",
                        "severity": "major",
                        "params": {
                            "mode": "allowlist_with_vendor_fallback",
                            "allowed_domains": ["cdn.jsdelivr.net", "unpkg.com"],
                            "vendor_fallback": {"echarts": "vendor/echarts/5.4.3/echarts.min.js"},
                        },
                    }
                ]
            },
        },
    )
    (html_dir / "page_1.html").write_text(
        "<html><body>"
        "<script src='https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js'></script>"
        "<script>if(typeof echarts==='undefined'){var s=document.createElement('script');s.src='vendor/echarts/5.4.3/echarts.min.js';document.head.appendChild(s);}</script>"
        "</body></html>",
        encoding="utf-8",
    )

    ok, _, report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert ok is True
    assert int((report.get("summary") or {}).get("failed_rules") or 0) == 0


def test_skill_compliance_validator_external_script_policy_blocks_disallowed_domain(tmp_path: Path):
    project_name = "外链拦截项目"
    project_dir = tmp_path / project_name
    html_dir = tmp_path / "html_blocked"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    _write_json(project_dir / "project_plan.json", {"project_name": project_name, "pages": {}})
    _write_json(project_dir / "runtime_skill_plan.json", {"skillpack": {"id": "skill"}})
    _write_json(
        project_dir / "runtime_rule_graph.json",
        {
            "policy": {"min_rule_pass_ratio": 0.85, "critical_rule_ids": []},
            "graph": {
                "nodes": [
                    {
                        "rule_id": "html.external_script_policy",
                        "category": "html",
                        "severity": "major",
                        "params": {
                            "mode": "allowlist_with_vendor_fallback",
                            "allowed_domains": ["cdn.jsdelivr.net"],
                            "vendor_fallback": {"echarts": "vendor/echarts/5.4.3/echarts.min.js"},
                        },
                    }
                ]
            },
        },
    )
    (html_dir / "page_1.html").write_text(
        "<html><body>"
        "<script src='https://evil.example.com/echarts.min.js'></script>"
        "<script src='vendor/echarts/5.4.3/echarts.min.js'></script>"
        "</body></html>",
        encoding="utf-8",
    )

    ok, _, report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert ok is False
    failed_ids = set((report.get("summary") or {}).get("failed_rule_ids") or [])
    assert "html.external_script_policy" in failed_ids


def test_skill_compliance_validator_detects_date_mentions_and_phrase_reuse(tmp_path: Path):
    project_name = "文案规则项目"
    project_dir = tmp_path / project_name
    html_dir = tmp_path / "html_copy_rules"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "project_intro": {"overview": "业务系统说明。"},
            "pages": {
                "page_1": {
                    "page_title": "首页",
                    "page_description": "本页面用于处理记录。2026-01-01 发布记录可查询。本页面继续说明筛选步骤。",
                },
                "page_2": {
                    "page_title": "工单页",
                    "page_description": "本页面用于处理记录。2026-01-01 发布记录可查询。本页面继续说明筛选步骤。",
                },
            },
        },
    )
    _write_json(project_dir / "runtime_skill_plan.json", {"skillpack": {"id": "skill"}})
    _write_json(
        project_dir / "runtime_rule_graph.json",
        {
            "policy": {"min_rule_pass_ratio": 0.85, "critical_rule_ids": []},
            "graph": {
                "nodes": [
                    {"rule_id": "copy.no_date_mentions", "category": "copy", "severity": "major", "params": {"required": True}},
                    {"rule_id": "copy.forbid_phrase_after_first", "category": "copy", "severity": "major", "params": {"phrase": "本页面"}},
                    {"rule_id": "copy.page_similarity_diversity", "category": "copy", "severity": "major", "params": {"max_similarity": 0.95}},
                ]
            },
        },
    )
    (html_dir / "page_1.html").write_text("<html><body><button id='btn'>查询</button></body></html>", encoding="utf-8")
    (html_dir / "page_2.html").write_text("<html><body><button id='btn2'>查询</button></body></html>", encoding="utf-8")

    ok, _, report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert ok is False
    failed_ids = set((report.get("summary") or {}).get("failed_rule_ids") or [])
    assert "copy.no_date_mentions" in failed_ids
    assert "copy.forbid_phrase_after_first" in failed_ids
    assert "copy.page_similarity_diversity" in failed_ids
