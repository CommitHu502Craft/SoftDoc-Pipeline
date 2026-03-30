"""
统一流水线编排器
将步骤解析、权重配置、LLM 步骤判定集中到一处，供 GUI/API/CLI 复用。
"""

from typing import Dict, List

from core.pipeline_config import DEFAULT_PIPELINE_STEPS, STEP_NAMES, STEP_WEIGHTS


class PipelineOrchestrator:
    """轻量级流水线编排器"""

    LLM_STEPS = {"plan", "html", "code"}

    @classmethod
    def resolve_steps(cls, steps: List[str] = None) -> List[str]:
        """解析并过滤步骤，未传时回退统一默认流程"""
        if not steps:
            return list(DEFAULT_PIPELINE_STEPS)
        resolved = [s for s in steps if s in STEP_NAMES]
        return resolved or list(DEFAULT_PIPELINE_STEPS)

    @classmethod
    def needs_llm_preflight(cls, steps: List[str]) -> bool:
        """判断是否需要执行 API 连通性预检"""
        return bool(set(cls.resolve_steps(steps)) & cls.LLM_STEPS)

    @classmethod
    def build_step_config(cls, steps: List[str]) -> Dict[str, Dict[str, int | str]]:
        """构建步骤配置（名称 + 权重）"""
        resolved = cls.resolve_steps(steps)
        return {
            step: {
                "name": STEP_NAMES[step],
                "weight": STEP_WEIGHTS.get(step, 0)
            }
            for step in resolved
        }

