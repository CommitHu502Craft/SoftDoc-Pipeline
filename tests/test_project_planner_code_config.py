from modules.project_planner import ProjectPlanner


def _build_planner_stub() -> ProjectPlanner:
    planner = ProjectPlanner.__new__(ProjectPlanner)
    return planner


def test_code_generation_config_override_and_clamp():
    planner = _build_planner_stub()

    cfg = planner._build_code_generation_config(
        {
            "novelty_threshold": 1.8,
            "file_novelty_budget": -0.2,
            "project_novelty_threshold": 0.5,
            "rewrite_candidates": 9,
            "max_rewrite_rounds": 0,
            "heavy_search_ratio": 0.9,
            "max_risky_files": -2,
            "max_syntax_fail_files": -1,
            "min_ai_line_ratio": 2.0,
            "history_forbidden_max_files": -10,
            "max_total_llm_calls": 9999,
            "max_total_llm_failures": -4,
        }
    )

    assert cfg["novelty_threshold"] == 1.0
    assert cfg["file_novelty_budget"] == 0.0
    assert cfg["project_novelty_threshold"] == 0.5
    assert cfg["rewrite_candidates"] == 3
    assert cfg["max_rewrite_rounds"] == 1
    assert cfg["heavy_search_ratio"] == 0.5
    assert cfg["max_risky_files"] == 0
    assert cfg["max_syntax_fail_files"] == 0
    assert cfg["min_ai_line_ratio"] == 1.0
    assert cfg["history_forbidden_max_files"] == 0
    assert cfg["max_total_llm_calls"] == 300
    assert cfg["max_total_llm_failures"] == 0


def test_code_generation_quality_profile_switch():
    planner = _build_planner_stub()

    economy = planner._build_code_generation_config({"quality_profile": "economy"})
    strict = planner._build_code_generation_config({"quality_profile": "high_constraint"})

    assert economy["quality_profile"] == "economy"
    assert strict["quality_profile"] == "high_constraint"
    assert economy["rewrite_candidates"] < strict["rewrite_candidates"]
    assert economy["max_rewrite_rounds"] < strict["max_rewrite_rounds"]
    assert economy["max_llm_attempts_per_file"] < strict["max_llm_attempts_per_file"]
    assert economy["max_total_llm_calls"] < strict["max_total_llm_calls"]


def test_code_generation_config_accepts_llm_override_fields():
    planner = _build_planner_stub()

    cfg = planner._build_code_generation_config(
        {
            "llm_provider_override": "  provider_x  ",
            "llm_model_override": "  model-y  ",
        }
    )

    assert cfg["llm_provider_override"] == "provider_x"
    assert cfg["llm_model_override"] == "model-y"
