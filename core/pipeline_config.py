"""
统一流水线配置
三种入口（GUI / API / CLI）尽量复用同一套步骤定义，避免行为漂移。
"""

from typing import Dict, List

PIPELINE_PROTOCOL_VERSION = "2.3.0"

DEFAULT_PIPELINE_STEPS: List[str] = [
    "plan",
    "spec",
    "html",
    "screenshot",
    "code",
    "verify",
    "document",
    "pdf",
    "freeze",
]

STEP_NAMES: Dict[str, str] = {
    "plan": "生成项目规划",
    "spec": "生成可执行规格",
    "html": "生成HTML页面",
    "screenshot": "截图生成",
    "code": "代码生成",
    "verify": "运行验证",
    "document": "说明书生成",
    "pdf": "源码PDF生成",
    "freeze": "冻结提交包",
}

STEP_WEIGHTS: Dict[str, int] = {
    "plan": 18,
    "spec": 10,
    "html": 12,
    "screenshot": 12,
    "code": 18,
    "verify": 10,
    "document": 10,
    "pdf": 5,
    "freeze": 5,
}
