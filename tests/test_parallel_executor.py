import asyncio

from core.parallel_executor import ParallelExecutor
from core.llm_budget import llm_budget


def test_run_sync_executes_without_existing_loop():
    executor = ParallelExecutor()
    result = executor.run_sync(asyncio.sleep(0, result="ok"))
    assert result == "ok"


def test_run_sync_raises_within_existing_loop():
    executor = ParallelExecutor()

    async def _inner():
        coro = asyncio.sleep(0, result="ok")
        try:
            executor.run_sync(coro)
        except RuntimeError as e:
            # run_sync 在事件循环内提前抛错时，需要手动关闭协程避免 warning。
            coro.close()
            return str(e)
        return ""

    message = asyncio.run(_inner())
    assert "Cannot use run_sync within an existing event loop" in message


def test_run_llm_tasks_propagates_llm_budget_scope(monkeypatch):
    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 10,
                "stages": {"default": 10, "plan": 10},
                "cache_ttl_seconds": 300,
                "cache_max_entries": 8,
            }
        },
    )

    executor = ParallelExecutor()
    llm_budget.reset_run("ctx-run")

    def _task():
        ok, _ = llm_budget.consume_call()
        return {
            "ok": ok,
            "run_id": llm_budget.current_run_id(),
            "stage": llm_budget.current_stage(),
        }

    with llm_budget.run_scope("ctx-run"), llm_budget.stage_scope("plan"):
        result = executor.run_sync(
            executor.run_llm_tasks([_task], concurrency=1, delay=0),
        )

    assert result[0]["ok"] is True
    assert result[0]["run_id"] == "ctx-run"
    assert result[0]["stage"] == "plan"
