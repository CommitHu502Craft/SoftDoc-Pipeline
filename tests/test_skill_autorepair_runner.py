import json
from pathlib import Path

from modules.skill_autorepair_runner import run_skill_autorepair
from modules.skill_compliance_validator import validate_runtime_skill_compliance


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_skill_autorepair_runner_converges(tmp_path: Path):
    project_name = "自动修复项目"
    project_dir = tmp_path / project_name
    html_dir = tmp_path / "html"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "project_intro": {"overview": "AI系统介绍。"},
            "pages": {
                "page_1": {"page_title": "首页", "page_description": "说明太短"},
            },
        },
    )
    _write_json(
        project_dir / "runtime_skill_plan.json",
        {
            "skillpack": {"id": "skill"},
            "constraints": {
                "overview_copy": {
                    "target_chars": 250,
                    "ban_words": ["聚焦"],
                    "ban_topics": ["AI", "智能"],
                },
                "page_narration": {
                    "first_sentence_prefix": "本页面",
                    "ban_words": ["核心"],
                    "avoid_terms": ["模块", "板块"],
                    "replacement_map": {"展示": "有"},
                    "chart_append_sentence": "鼠标悬停在图表自己想了解的数据上方，可以查看具体数值。",
                },
            },
        },
    )
    _write_json(
        project_dir / "runtime_rule_graph.json",
        {
            "policy": {
                "min_rule_pass_ratio": 0.85,
                "critical_rule_ids": ["copy.first_sentence_prefix", "action.showmodal_dom_sequence"],
                "max_auto_repair_rounds": 2,
            },
            "graph": {
                "nodes": [
                    {"rule_id": "copy.first_sentence_prefix", "category": "copy", "severity": "critical", "params": {"prefix": "本页面"}},
                    {"rule_id": "copy.sentence_count", "category": "copy", "severity": "major", "params": {"required": 6}},
                    {"rule_id": "copy.min_chars", "category": "copy", "severity": "major", "params": {"required": 300}},
                    {"rule_id": "copy.overview_ban_topics", "category": "copy", "severity": "critical", "params": {"ban_topics": ["AI", "智能"]}},
                    {"rule_id": "html.no_comments", "category": "html", "severity": "major", "params": {"required": True}},
                    {"rule_id": "html.no_rounded_rectangles", "category": "html", "severity": "major", "params": {"required": True}},
                    {"rule_id": "action.button_action_unique", "category": "action", "severity": "critical", "params": {"required": True}},
                    {"rule_id": "action.button_id_coverage", "category": "action", "severity": "major", "params": {"required": True}},
                    {"rule_id": "action.showmodal_dom_sequence", "category": "action", "severity": "critical", "params": {"api": "showModal"}},
                ]
            },
        },
    )

    (html_dir / "page_1.html").write_text(
        "<html><body><!-- c --><button style='border-radius:6px'>查询</button></body></html>",
        encoding="utf-8",
    )

    before_ok, _, _ = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert before_ok is False

    repair = run_skill_autorepair(project_name, project_dir, html_dir, max_rounds=2)
    assert Path(repair.get("report_path") or "").exists()
    assert len(repair.get("rounds") or []) >= 1

    after_ok, _, after_report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert after_ok is True
    assert (after_report.get("summary") or {}).get("critical_failed_rules") == []


def test_skill_autorepair_runner_respects_policy_actions_scope(tmp_path: Path):
    project_name = "策略范围修复项目"
    project_dir = tmp_path / project_name
    html_dir = tmp_path / "html_scope"
    project_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        project_dir / "project_plan.json",
        {
            "project_name": project_name,
            "project_intro": {"overview": "普通业务系统介绍。"},
            "pages": {
                "page_1": {"page_title": "首页", "page_description": "描述不足"},
            },
        },
    )
    _write_json(
        project_dir / "runtime_skill_plan.json",
        {
            "skillpack": {"id": "skill"},
            "constraints": {
                "overview_copy": {"target_chars": 250, "ban_words": [], "ban_topics": []},
                "page_narration": {
                    "first_sentence_prefix": "本页面",
                    "ban_words": [],
                    "avoid_terms": [],
                    "replacement_map": {},
                    "chart_append_sentence": "",
                },
            },
        },
    )
    _write_json(
        project_dir / "runtime_rule_graph.json",
        {
            "policy": {"min_rule_pass_ratio": 0.85, "critical_rule_ids": ["copy.first_sentence_prefix"]},
            "graph": {
                "nodes": [
                    {"rule_id": "copy.first_sentence_prefix", "category": "copy", "severity": "critical", "params": {"prefix": "本页面"}},
                    {"rule_id": "copy.sentence_count", "category": "copy", "severity": "major", "params": {"required": 6}},
                    {"rule_id": "html.no_comments", "category": "html", "severity": "major", "params": {"required": True}},
                ]
            },
        },
    )
    (html_dir / "page_1.html").write_text(
        "<html><body><!-- comment --><button id='btn1'>查询</button></body></html>",
        encoding="utf-8",
    )

    before_ok, _, before_report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert before_ok is False
    assert "copy.first_sentence_prefix" in ((before_report.get("summary") or {}).get("failed_rule_ids") or [])
    assert "html.no_comments" in ((before_report.get("summary") or {}).get("failed_rule_ids") or [])

    repair = run_skill_autorepair(
        project_name,
        project_dir,
        html_dir,
        max_rounds=1,
        policy_actions=["rewrite_failed_page_copy"],
    )
    assert "rewrite_failed_page_copy" in (repair.get("requested_policy_actions") or [])

    after_ok, _, after_report = validate_runtime_skill_compliance(project_name, project_dir, html_dir)
    assert after_ok is False
    failed_after = (after_report.get("summary") or {}).get("failed_rule_ids") or []
    assert "copy.first_sentence_prefix" not in failed_after
    assert "html.no_comments" in failed_after
