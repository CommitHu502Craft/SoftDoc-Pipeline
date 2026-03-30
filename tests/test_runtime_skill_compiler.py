from modules.runtime_skill_compiler import compile_runtime_rule_graph


def test_runtime_skill_compiler_includes_critical_rules():
    runtime_plan = {
        "skillpack": {"id": "x", "version": "1.0"},
        "orchestration": {
            "trigger_order": ["intent", "visual", "functional", "evidence", "token"],
            "conflict_priority": ["evidence_auditability", "functional_completeness", "visual_expression", "token_saving"],
            "degrade_path": ["advanced_skills", "base_skills", "rules_template"],
            "stages": ["a", "b"],
        },
        "constraints": {
            "page_narration": {
                "first_sentence_prefix": "本页面",
                "sentence_count_per_page": 6,
                "min_chars_per_page": 300,
                "ban_words": ["核心"],
                "avoid_terms": ["模块"],
                "chart_append_sentence": "鼠标悬停在图表自己想了解的数据上方，可以查看具体数值。",
            },
            "overview_copy": {
                "target_chars": 250,
                "ban_words": ["聚焦"],
                "ban_topics": ["AI", "智能"],
            },
            "frontend": {
                "no_comments_required": True,
                "no_rounded_rectangles": True,
                "chart_required": True,
                "chart_responsive": False,
                "chart_maintain_aspect_ratio": True,
                "button_action_required": True,
                "button_action_unique": True,
                "modal_api_required": "showModal",
            },
        },
    }
    graph = compile_runtime_rule_graph(runtime_plan)
    nodes = (graph.get("graph") or {}).get("nodes") or []
    node_ids = {str(n.get("rule_id") or "") for n in nodes}
    assert "copy.overview_ban_topics" in node_ids
    assert "action.showmodal_dom_sequence" in node_ids
    assert "copy.no_date_mentions" in node_ids
    assert "copy.forbid_phrase_after_first" in node_ids
    assert "copy.page_similarity_diversity" in node_ids
    policy = graph.get("policy") or {}
    assert float(policy.get("min_rule_pass_ratio") or 0) == 0.85
    critical = set(policy.get("critical_rule_ids") or [])
    assert "copy.first_sentence_prefix" in critical
    assert "action.button_action_unique" in critical
