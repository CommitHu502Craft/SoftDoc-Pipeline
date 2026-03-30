"""
LLM 调用预算与缓存管理。

能力：
1) 按 run_id + stage 统计调用预算。
2) 超限时返回阻断原因，避免无上限消耗额度。
3) 提供进程内 prompt 结果缓存（TTL + 容量上限）。
4) 统计 UI Skill 前缀缓存命中（用于稳定前缀缓存观测）。
5) 提供 block 级预算控制（支持按 block 与 stage 约束）。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple

from config import load_api_config


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class LlmBudgetManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._local = threading.local()
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_order = []

    @staticmethod
    def _normalize_int(value: Any) -> int:
        try:
            parsed = int(value)
        except Exception:
            return 0
        return max(0, parsed)

    @staticmethod
    def _new_run_state() -> Dict[str, Any]:
        return {
            "started_at": time.time(),
            "total_calls": 0,
            "total_failures": 0,
            "stage_calls": {},
            "stage_failures": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "stage_input_tokens": {},
            "stage_output_tokens": {},
            "stage_total_tokens": {},
            "provider_calls": {},
            "provider_failures": {},
            "provider_input_tokens": {},
            "provider_output_tokens": {},
            "provider_total_tokens": {},
            "provider_models": {},
            "provider_api_styles": {},
            "skill_prefix_cache_hits": 0,
            "skill_prefix_cache_misses": 0,
            "skill_prefix_cache_by_key": {},
            "block_calls": {},
            "stage_block_calls": {},
            "block_calls_by_stage": {},
            "block_rejections": 0,
            "block_rejections_by_stage": {},
            "block_rejections_by_block": {},
        }

    @staticmethod
    def _bump_counter(target: Dict[str, int], key: str, delta: int = 1) -> None:
        if delta <= 0:
            return
        target[key] = int(target.get(key, 0)) + int(delta)

    @staticmethod
    def _bump_nested_counter(target: Dict[str, Dict[str, int]], key_a: str, key_b: str, delta: int = 1) -> None:
        if delta <= 0:
            return
        row = target.setdefault(str(key_a), {})
        row[str(key_b)] = int(row.get(str(key_b), 0)) + int(delta)

    def _config(self) -> Dict[str, Any]:
        cfg = load_api_config() or {}
        budget_cfg = cfg.get("llm_budget") or {}
        stages = budget_cfg.get("stages") or {}
        block_stages = budget_cfg.get("block_stage_limits") or {}
        return {
            "total_calls": max(1, _safe_int(budget_cfg.get("total_calls"), 120)),
            "total_failures": max(1, _safe_int(budget_cfg.get("total_failures"), 32)),
            "stages": {
                "default": max(1, _safe_int(stages.get("default"), 40)),
                "plan": max(1, _safe_int(stages.get("plan"), 12)),
                "spec": max(1, _safe_int(stages.get("spec"), 8)),
                "html": max(1, _safe_int(stages.get("html"), 24)),
                "code": max(1, _safe_int(stages.get("code"), 72)),
                "document": max(1, _safe_int(stages.get("document"), 16)),
                "other": max(1, _safe_int(stages.get("other"), 16)),
            },
            "block_calls_per_block": max(1, _safe_int(budget_cfg.get("block_calls_per_block"), 2)),
            "block_stage_limits": {
                "default": max(1, _safe_int(block_stages.get("default"), 200)),
                "plan": max(1, _safe_int(block_stages.get("plan"), 80)),
                "spec": max(1, _safe_int(block_stages.get("spec"), 80)),
                "html": max(1, _safe_int(block_stages.get("html"), 200)),
                "code": max(1, _safe_int(block_stages.get("code"), 200)),
                "document": max(1, _safe_int(block_stages.get("document"), 80)),
                "other": max(1, _safe_int(block_stages.get("other"), 80)),
            },
            "cache_ttl_seconds": max(30.0, _safe_float(budget_cfg.get("cache_ttl_seconds"), 1800.0)),
            "cache_max_entries": max(2, _safe_int(budget_cfg.get("cache_max_entries"), 256)),
        }

    def reset_run(self, run_id: str) -> None:
        with self._lock:
            self._runs[str(run_id)] = self._new_run_state()

    @contextmanager
    def run_scope(self, run_id: str):
        previous = getattr(self._local, "run_id", None)
        self._local.run_id = str(run_id)
        try:
            yield
        finally:
            if previous is None:
                try:
                    delattr(self._local, "run_id")
                except Exception:
                    pass
            else:
                self._local.run_id = previous

    @contextmanager
    def stage_scope(self, stage: str):
        previous = getattr(self._local, "stage", None)
        self._local.stage = str(stage or "default")
        try:
            yield
        finally:
            if previous is None:
                try:
                    delattr(self._local, "stage")
                except Exception:
                    pass
            else:
                self._local.stage = previous

    @contextmanager
    def block_scope(self, block_id: str):
        previous = getattr(self._local, "block_id", None)
        self._local.block_id = str(block_id or "").strip()
        try:
            yield
        finally:
            if previous is None:
                try:
                    delattr(self._local, "block_id")
                except Exception:
                    pass
            else:
                self._local.block_id = previous

    def current_run_id(self) -> str:
        return str(getattr(self._local, "run_id", "") or "global")

    def current_stage(self) -> str:
        return str(getattr(self._local, "stage", "") or "default")

    def current_block_id(self) -> str:
        return str(getattr(self._local, "block_id", "") or "")

    def consume_call(self, stage: Optional[str] = None) -> Tuple[bool, str]:
        cfg = self._config()
        run_id = self.current_run_id()
        stage_name = str(stage or self.current_stage() or "default")
        stage_limits = cfg["stages"]
        stage_limit = int(stage_limits.get(stage_name, stage_limits.get("other", stage_limits["default"])))

        with self._lock:
            state = self._runs.setdefault(run_id, self._new_run_state())
            if int(state["total_calls"]) >= int(cfg["total_calls"]):
                return False, f"run[{run_id}] total_calls 超限({state['total_calls']}/{cfg['total_calls']})"

            stage_calls = state["stage_calls"]
            current_stage_calls = int(stage_calls.get(stage_name, 0))
            if current_stage_calls >= stage_limit:
                return False, f"run[{run_id}] stage[{stage_name}] calls 超限({current_stage_calls}/{stage_limit})"

            state["total_calls"] = int(state["total_calls"]) + 1
            stage_calls[stage_name] = current_stage_calls + 1

        return True, ""

    def _record_block_rejection(
        self,
        state: Dict[str, Any],
        stage_name: str,
        block_key: str,
    ) -> None:
        state["block_rejections"] = int(state.get("block_rejections", 0)) + 1
        self._bump_counter(state.setdefault("block_rejections_by_stage", {}), stage_name, 1)
        self._bump_counter(state.setdefault("block_rejections_by_block", {}), block_key, 1)

    def consume_block_call(self, block_id: str = "", stage: Optional[str] = None) -> Tuple[bool, str]:
        """
        消耗一次 block 级预算。
        用于按功能块控制高成本重试，避免页面级“整页重跑”。
        """
        cfg = self._config()
        run_id = self.current_run_id()
        stage_name = str(stage or self.current_stage() or "default")
        stage_limits = cfg["block_stage_limits"]
        stage_limit = int(stage_limits.get(stage_name, stage_limits.get("other", stage_limits["default"])))
        block_limit = int(cfg.get("block_calls_per_block") or 1)
        block_key = str(block_id or self.current_block_id() or "unknown_block").strip() or "unknown_block"

        with self._lock:
            state = self._runs.setdefault(run_id, self._new_run_state())
            stage_block_calls = state.setdefault("stage_block_calls", {})
            current_stage_calls = int(stage_block_calls.get(stage_name, 0))
            if current_stage_calls >= stage_limit:
                self._record_block_rejection(state, stage_name, block_key)
                return False, f"run[{run_id}] stage[{stage_name}] block_calls 超限({current_stage_calls}/{stage_limit})"

            block_calls = state.setdefault("block_calls", {})
            current_block_calls = int(block_calls.get(block_key, 0))
            if current_block_calls >= block_limit:
                self._record_block_rejection(state, stage_name, block_key)
                return False, f"run[{run_id}] block[{block_key}] calls 超限({current_block_calls}/{block_limit})"

            block_calls[block_key] = current_block_calls + 1
            stage_block_calls[stage_name] = current_stage_calls + 1
            self._bump_nested_counter(state.setdefault("block_calls_by_stage", {}), stage_name, block_key, 1)

        return True, ""

    def record_call(
        self,
        provider_name: str = "",
        model: str = "",
        api_style: str = "",
        stage: Optional[str] = None,
    ) -> None:
        run_id = self.current_run_id()
        stage_name = str(stage or self.current_stage() or "default")
        provider = str(provider_name or "unknown")
        model_name = str(model or "unknown")
        style_name = str(api_style or "unknown")
        with self._lock:
            state = self._runs.setdefault(run_id, self._new_run_state())
            self._bump_counter(state.setdefault("provider_calls", {}), provider, 1)
            self._bump_nested_counter(state.setdefault("provider_models", {}), provider, model_name, 1)
            self._bump_nested_counter(state.setdefault("provider_api_styles", {}), provider, style_name, 1)
            # stage 维度记录 provider 调用，便于后续扩展分析
            self._bump_nested_counter(
                state.setdefault("stage_provider_calls", {}),
                stage_name,
                provider,
                1,
            )

    def record_failure(
        self,
        stage: Optional[str] = None,
        provider_name: str = "",
    ) -> None:
        cfg = self._config()
        run_id = self.current_run_id()
        stage_name = str(stage or self.current_stage() or "default")
        provider = str(provider_name or "unknown")
        with self._lock:
            state = self._runs.setdefault(run_id, self._new_run_state())
            state["total_failures"] = int(state["total_failures"]) + 1
            stage_failures = state["stage_failures"]
            stage_failures[stage_name] = int(stage_failures.get(stage_name, 0)) + 1
            self._bump_counter(state.setdefault("provider_failures", {}), provider, 1)
            if int(state["total_failures"]) > int(cfg["total_failures"]):
                state["exhausted_by_failures"] = True

    def record_usage(
        self,
        provider_name: str = "",
        model: str = "",
        api_style: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        stage: Optional[str] = None,
    ) -> None:
        run_id = self.current_run_id()
        stage_name = str(stage or self.current_stage() or "default")
        provider = str(provider_name or "unknown")
        model_name = str(model or "unknown")
        style_name = str(api_style or "unknown")
        input_count = self._normalize_int(input_tokens)
        output_count = self._normalize_int(output_tokens)
        total_count = self._normalize_int(total_tokens)
        if total_count <= 0:
            total_count = input_count + output_count
        with self._lock:
            state = self._runs.setdefault(run_id, self._new_run_state())
            state["input_tokens"] = int(state.get("input_tokens", 0)) + input_count
            state["output_tokens"] = int(state.get("output_tokens", 0)) + output_count
            state["total_tokens"] = int(state.get("total_tokens", 0)) + total_count
            self._bump_counter(state.setdefault("stage_input_tokens", {}), stage_name, input_count)
            self._bump_counter(state.setdefault("stage_output_tokens", {}), stage_name, output_count)
            self._bump_counter(state.setdefault("stage_total_tokens", {}), stage_name, total_count)
            self._bump_counter(state.setdefault("provider_input_tokens", {}), provider, input_count)
            self._bump_counter(state.setdefault("provider_output_tokens", {}), provider, output_count)
            self._bump_counter(state.setdefault("provider_total_tokens", {}), provider, total_count)
            # 若调用路径未显式打点 record_call，这里兜底补一次 model/style 观察值
            self._bump_nested_counter(state.setdefault("provider_models", {}), provider, model_name, 0)
            self._bump_nested_counter(state.setdefault("provider_api_styles", {}), provider, style_name, 0)

    def record_skill_prefix_cache_hit(self, prefix_key: str, hit: bool, stage: Optional[str] = None) -> None:
        """
        记录 UI Skill 稳定前缀缓存命中情况。
        该指标独立于 LLM 文本缓存，用于观察技能层是否复用既有决策产物。
        """
        run_id = self.current_run_id()
        stage_name = str(stage or self.current_stage() or "default")
        key = str(prefix_key or "unknown_prefix").strip() or "unknown_prefix"
        with self._lock:
            state = self._runs.setdefault(run_id, self._new_run_state())
            row = state.setdefault("skill_prefix_cache_by_key", {}).setdefault(
                key,
                {"hits": 0, "misses": 0, "stage_last": stage_name},
            )
            row["stage_last"] = stage_name
            if bool(hit):
                state["skill_prefix_cache_hits"] = int(state.get("skill_prefix_cache_hits", 0)) + 1
                row["hits"] = int(row.get("hits", 0)) + 1
            else:
                state["skill_prefix_cache_misses"] = int(state.get("skill_prefix_cache_misses", 0)) + 1
                row["misses"] = int(row.get("misses", 0)) + 1

    def get_state(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        target_run = str(run_id or self.current_run_id() or "global")
        with self._lock:
            state = self._runs.get(target_run) or {}
            return json.loads(json.dumps(state, ensure_ascii=False))

    def get_runtime_snapshot(self, max_runs: int = 20) -> Dict[str, Any]:
        cfg = self._config()
        with self._lock:
            all_run_items = []
            for run_id, state in self._runs.items():
                all_run_items.append(
                    {
                        "run_id": run_id,
                        "started_at": float(state.get("started_at") or 0.0),
                        "total_calls": int(state.get("total_calls") or 0),
                        "total_failures": int(state.get("total_failures") or 0),
                        "input_tokens": int(state.get("input_tokens") or 0),
                        "output_tokens": int(state.get("output_tokens") or 0),
                        "total_tokens": int(state.get("total_tokens") or 0),
                        "stage_calls": dict(state.get("stage_calls") or {}),
                        "stage_failures": dict(state.get("stage_failures") or {}),
                        "stage_input_tokens": dict(state.get("stage_input_tokens") or {}),
                        "stage_output_tokens": dict(state.get("stage_output_tokens") or {}),
                        "stage_total_tokens": dict(state.get("stage_total_tokens") or {}),
                        "provider_calls": dict(state.get("provider_calls") or {}),
                        "provider_failures": dict(state.get("provider_failures") or {}),
                        "provider_input_tokens": dict(state.get("provider_input_tokens") or {}),
                        "provider_output_tokens": dict(state.get("provider_output_tokens") or {}),
                        "provider_total_tokens": dict(state.get("provider_total_tokens") or {}),
                        "provider_models": dict(state.get("provider_models") or {}),
                        "provider_api_styles": dict(state.get("provider_api_styles") or {}),
                        "skill_prefix_cache_hits": int(state.get("skill_prefix_cache_hits") or 0),
                        "skill_prefix_cache_misses": int(state.get("skill_prefix_cache_misses") or 0),
                        "skill_prefix_cache_by_key": dict(state.get("skill_prefix_cache_by_key") or {}),
                        "block_calls": dict(state.get("block_calls") or {}),
                        "stage_block_calls": dict(state.get("stage_block_calls") or {}),
                        "block_calls_by_stage": dict(state.get("block_calls_by_stage") or {}),
                        "block_rejections": int(state.get("block_rejections") or 0),
                        "block_rejections_by_stage": dict(state.get("block_rejections_by_stage") or {}),
                        "block_rejections_by_block": dict(state.get("block_rejections_by_block") or {}),
                        "exhausted_by_failures": bool(state.get("exhausted_by_failures")),
                    }
                )
            all_run_items.sort(key=lambda x: x.get("started_at", 0.0), reverse=True)

            run_items = list(all_run_items)
            if max_runs > 0:
                run_items = run_items[: max(1, int(max_runs))]

            total_calls = sum(int(x.get("total_calls") or 0) for x in all_run_items)
            total_failures = sum(int(x.get("total_failures") or 0) for x in all_run_items)
            total_input_tokens = sum(int(x.get("input_tokens") or 0) for x in all_run_items)
            total_output_tokens = sum(int(x.get("output_tokens") or 0) for x in all_run_items)
            total_tokens = sum(int(x.get("total_tokens") or 0) for x in all_run_items)
            total_skill_prefix_hits = sum(int(x.get("skill_prefix_cache_hits") or 0) for x in all_run_items)
            total_skill_prefix_misses = sum(int(x.get("skill_prefix_cache_misses") or 0) for x in all_run_items)
            total_block_rejections = sum(int(x.get("block_rejections") or 0) for x in all_run_items)

            stage_calls: Dict[str, int] = {}
            stage_failures: Dict[str, int] = {}
            stage_input_tokens: Dict[str, int] = {}
            stage_output_tokens: Dict[str, int] = {}
            stage_total_tokens: Dict[str, int] = {}
            stage_block_calls: Dict[str, int] = {}
            block_rejections_by_stage: Dict[str, int] = {}
            block_calls: Dict[str, int] = {}
            block_rejections_by_block: Dict[str, int] = {}
            skill_prefix_cache_by_key: Dict[str, Dict[str, int]] = {}
            provider_summary: Dict[str, Dict[str, Any]] = {}

            for run in all_run_items:
                for stage, value in (run.get("stage_calls") or {}).items():
                    stage_calls[stage] = int(stage_calls.get(stage, 0)) + int(value or 0)
                for stage, value in (run.get("stage_failures") or {}).items():
                    stage_failures[stage] = int(stage_failures.get(stage, 0)) + int(value or 0)
                for stage, value in (run.get("stage_input_tokens") or {}).items():
                    stage_input_tokens[stage] = int(stage_input_tokens.get(stage, 0)) + int(value or 0)
                for stage, value in (run.get("stage_output_tokens") or {}).items():
                    stage_output_tokens[stage] = int(stage_output_tokens.get(stage, 0)) + int(value or 0)
                for stage, value in (run.get("stage_total_tokens") or {}).items():
                    stage_total_tokens[stage] = int(stage_total_tokens.get(stage, 0)) + int(value or 0)
                for stage, value in (run.get("stage_block_calls") or {}).items():
                    stage_block_calls[stage] = int(stage_block_calls.get(stage, 0)) + int(value or 0)
                for stage, value in (run.get("block_rejections_by_stage") or {}).items():
                    block_rejections_by_stage[stage] = int(block_rejections_by_stage.get(stage, 0)) + int(value or 0)
                for block_key, value in (run.get("block_calls") or {}).items():
                    block_calls[block_key] = int(block_calls.get(block_key, 0)) + int(value or 0)
                for block_key, value in (run.get("block_rejections_by_block") or {}).items():
                    block_rejections_by_block[block_key] = int(block_rejections_by_block.get(block_key, 0)) + int(value or 0)

                for key, payload in (run.get("skill_prefix_cache_by_key") or {}).items():
                    row = skill_prefix_cache_by_key.setdefault(str(key), {"hits": 0, "misses": 0})
                    if isinstance(payload, dict):
                        row["hits"] = int(row.get("hits", 0)) + int(payload.get("hits") or 0)
                        row["misses"] = int(row.get("misses", 0)) + int(payload.get("misses") or 0)

                provider_calls = run.get("provider_calls") or {}
                provider_failures = run.get("provider_failures") or {}
                provider_input = run.get("provider_input_tokens") or {}
                provider_output = run.get("provider_output_tokens") or {}
                provider_total = run.get("provider_total_tokens") or {}
                provider_models = run.get("provider_models") or {}
                provider_styles = run.get("provider_api_styles") or {}

                provider_names = set(provider_calls.keys()) | set(provider_failures.keys()) | set(provider_input.keys()) | set(provider_output.keys()) | set(provider_total.keys())
                for provider in provider_names:
                    row = provider_summary.setdefault(
                        provider,
                        {
                            "calls": 0,
                            "failures": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                            "models": {},
                            "api_styles": {},
                        },
                    )
                    row["calls"] = int(row["calls"]) + int(provider_calls.get(provider, 0) or 0)
                    row["failures"] = int(row["failures"]) + int(provider_failures.get(provider, 0) or 0)
                    row["input_tokens"] = int(row["input_tokens"]) + int(provider_input.get(provider, 0) or 0)
                    row["output_tokens"] = int(row["output_tokens"]) + int(provider_output.get(provider, 0) or 0)
                    row["total_tokens"] = int(row["total_tokens"]) + int(provider_total.get(provider, 0) or 0)

                    for model_name, model_calls in (provider_models.get(provider) or {}).items():
                        row["models"][model_name] = int(row["models"].get(model_name, 0)) + int(model_calls or 0)
                    for style_name, style_calls in (provider_styles.get(provider) or {}).items():
                        row["api_styles"][style_name] = int(row["api_styles"].get(style_name, 0)) + int(style_calls or 0)

            return {
                "generated_at": time.time(),
                "config": cfg,
                "cache": {
                    "entries": len(self._cache),
                    "max_entries": int(cfg.get("cache_max_entries") or 0),
                },
                "summary": {
                    "active_runs": len(all_run_items),
                    "total_calls": total_calls,
                    "total_failures": total_failures,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_tokens,
                    "skill_prefix_cache_hits": total_skill_prefix_hits,
                    "skill_prefix_cache_misses": total_skill_prefix_misses,
                    "skill_prefix_cache_by_key": skill_prefix_cache_by_key,
                    "block_calls": block_calls,
                    "stage_block_calls": stage_block_calls,
                    "block_rejections": total_block_rejections,
                    "block_rejections_by_stage": block_rejections_by_stage,
                    "block_rejections_by_block": block_rejections_by_block,
                    "stage_calls": stage_calls,
                    "stage_failures": stage_failures,
                    "stage_input_tokens": stage_input_tokens,
                    "stage_output_tokens": stage_output_tokens,
                    "stage_total_tokens": stage_total_tokens,
                },
                "provider_summary": provider_summary,
                "runs": run_items,
            }

    @staticmethod
    def make_cache_key(provider_name: str, model: str, api_style: str, messages: Any) -> str:
        payload = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{provider_name}|{model}|{api_style}|{digest}"

    def get_cached(self, key: str) -> Optional[str]:
        cfg = self._config()
        ttl = float(cfg["cache_ttl_seconds"])
        now = time.time()
        with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            created_at = float(item.get("created_at") or 0.0)
            if (now - created_at) > ttl:
                self._cache.pop(key, None)
                try:
                    self._cache_order.remove(key)
                except Exception:
                    pass
                return None
            return str(item.get("value") or "")

    def set_cached(self, key: str, value: str) -> None:
        cfg = self._config()
        max_entries = int(cfg["cache_max_entries"])
        with self._lock:
            self._cache[key] = {
                "value": str(value),
                "created_at": time.time(),
            }
            if key in self._cache_order:
                self._cache_order.remove(key)
            self._cache_order.append(key)

            while len(self._cache_order) > max_entries:
                oldest = self._cache_order.pop(0)
                self._cache.pop(oldest, None)


llm_budget = LlmBudgetManager()
