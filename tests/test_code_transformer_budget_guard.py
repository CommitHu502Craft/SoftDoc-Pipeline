from modules.code_transformer import CodeTransformer


def _build_budget_stub() -> CodeTransformer:
    transformer = CodeTransformer.__new__(CodeTransformer)
    transformer._llm_calls_total = 0
    transformer._llm_failures_total = 0
    transformer._llm_disabled_reason = ""
    transformer.max_total_llm_calls = 2
    transformer.max_total_llm_failures = 2
    transformer.disable_llm_on_budget_exhausted = True
    transformer.disable_llm_on_failures = True
    return transformer


def test_global_llm_budget_exhaustion_disables_followup_calls():
    transformer = _build_budget_stub()

    assert transformer._consume_global_llm_attempt("a.py") is True
    assert transformer._consume_global_llm_attempt("b.py") is True
    assert transformer._consume_global_llm_attempt("c.py") is False
    assert transformer._llm_calls_total == 2
    assert "global_budget_exhausted" in transformer._llm_disabled_reason


def test_llm_failure_threshold_triggers_disable_on_network_error():
    transformer = _build_budget_stub()

    transformer._record_llm_call_failure(RuntimeError("ConnectionError: reset by peer"))
    assert transformer._llm_disabled_reason == ""
    transformer._record_llm_call_failure(RuntimeError("ConnectionError: reset by peer"))

    assert transformer._llm_failures_total == 2
    assert "network_failures_exhausted" in transformer._llm_disabled_reason
