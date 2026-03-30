from core.llm_budget import LlmBudgetManager


def test_llm_budget_stage_limits(monkeypatch):
    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 5,
                "stages": {
                    "default": 3,
                    "plan": 2,
                },
                "cache_ttl_seconds": 300,
                "cache_max_entries": 4,
            }
        },
    )

    manager = LlmBudgetManager()
    manager.reset_run("run-a")
    with manager.run_scope("run-a"):
        with manager.stage_scope("plan"):
            assert manager.consume_call()[0] is True
            assert manager.consume_call()[0] is True
            ok, reason = manager.consume_call()
            assert ok is False
            assert "stage[plan]" in reason


def test_llm_budget_total_limit(monkeypatch):
    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 2,
                "stages": {"default": 10},
                "cache_ttl_seconds": 300,
                "cache_max_entries": 8,
            }
        },
    )

    manager = LlmBudgetManager()
    manager.reset_run("run-b")
    with manager.run_scope("run-b"), manager.stage_scope("html"):
        assert manager.consume_call()[0] is True
        assert manager.consume_call()[0] is True
        ok, reason = manager.consume_call()
        assert ok is False
        assert "total_calls" in reason


def test_llm_budget_cache_eviction(monkeypatch):
    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 100,
                "stages": {"default": 100},
                "cache_ttl_seconds": 300,
                "cache_max_entries": 2,
            }
        },
    )

    manager = LlmBudgetManager()
    manager.set_cached("k1", "v1")
    manager.set_cached("k2", "v2")
    manager.set_cached("k3", "v3")

    assert manager.get_cached("k1") is None
    assert manager.get_cached("k2") == "v2"
    assert manager.get_cached("k3") == "v3"


def test_llm_budget_usage_and_provider_snapshot(monkeypatch):
    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 100,
                "stages": {"default": 100, "plan": 100},
                "cache_ttl_seconds": 300,
                "cache_max_entries": 8,
            }
        },
    )

    manager = LlmBudgetManager()
    manager.reset_run("run-usage")
    with manager.run_scope("run-usage"), manager.stage_scope("plan"):
        assert manager.consume_call()[0] is True
        manager.record_call(provider_name="deepseek", model="deepseek-chat", api_style="chat")
        manager.record_usage(
            provider_name="deepseek",
            model="deepseek-chat",
            api_style="chat",
            input_tokens=120,
            output_tokens=80,
            stage="plan",
        )
        manager.record_failure(stage="plan", provider_name="deepseek")

    snapshot = manager.get_runtime_snapshot(max_runs=5)
    assert snapshot["summary"]["total_calls"] == 1
    assert snapshot["summary"]["total_failures"] == 1
    assert snapshot["summary"]["input_tokens"] == 120
    assert snapshot["summary"]["output_tokens"] == 80
    assert snapshot["summary"]["total_tokens"] == 200
    assert snapshot["provider_summary"]["deepseek"]["calls"] == 1
    assert snapshot["provider_summary"]["deepseek"]["failures"] == 1
    assert snapshot["provider_summary"]["deepseek"]["total_tokens"] == 200
    assert snapshot["runs"][0]["provider_total_tokens"]["deepseek"] == 200


def test_llm_budget_skill_prefix_cache_metrics(monkeypatch):
    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 100,
                "stages": {"default": 100},
                "cache_ttl_seconds": 300,
                "cache_max_entries": 8,
            }
        },
    )

    manager = LlmBudgetManager()
    manager.reset_run("run-skill-prefix")
    with manager.run_scope("run-skill-prefix"), manager.stage_scope("plan"):
        manager.record_skill_prefix_cache_hit(prefix_key="ui_skill:demo", hit=True)
        manager.record_skill_prefix_cache_hit(prefix_key="ui_skill:demo", hit=False)
        manager.record_skill_prefix_cache_hit(prefix_key="ui_skill:demo", hit=True)

    snapshot = manager.get_runtime_snapshot(max_runs=5)
    summary = snapshot["summary"]
    assert summary["skill_prefix_cache_hits"] == 2
    assert summary["skill_prefix_cache_misses"] == 1
    assert summary["skill_prefix_cache_by_key"]["ui_skill:demo"]["hits"] == 2
    assert summary["skill_prefix_cache_by_key"]["ui_skill:demo"]["misses"] == 1


def test_llm_budget_block_call_limit(monkeypatch):
    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 100,
                "stages": {"default": 100, "html": 100},
                "block_calls_per_block": 2,
                "block_stage_limits": {"default": 100, "html": 3},
                "cache_ttl_seconds": 300,
                "cache_max_entries": 8,
            }
        },
    )

    manager = LlmBudgetManager()
    manager.reset_run("run-block")
    with manager.run_scope("run-block"), manager.stage_scope("html"):
        assert manager.consume_block_call("page_1_block_1")[0] is True
        assert manager.consume_block_call("page_1_block_1")[0] is True
        ok, reason = manager.consume_block_call("page_1_block_1")
        assert ok is False
        assert "block[page_1_block_1]" in reason

    snapshot = manager.get_runtime_snapshot(max_runs=5)
    run = snapshot["runs"][0]
    assert run["block_calls"]["page_1_block_1"] == 2
    assert run["block_rejections"] >= 1
