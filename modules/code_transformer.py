"""
代码变换引擎 (CodeTransformer)
V2.1 核心组件：将通用种子代码转化为特定领域的业务代码 (并行优化版)
"""
import os
import ast
import random
import re
import logging
import textwrap
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from core.deepseek_client import DeepSeekClient
from core.forbidden_pattern_index import ForbiddenPatternIndex
from core.novelty_analyzer import NoveltyAnalyzer
from modules.code_differentiator import CodeDifferentiator
from modules.control_flow_transformer import ControlFlowTransformer
from modules.spec_builder import SpecBuilder
from modules.structure_transformer import StructureTransformer
from core.parallel_executor import ParallelExecutor
from config import BASE_DIR

logger = logging.getLogger(__name__)

class CodeTransformer:
    """
    代码变换器。

    维护视角下的核心职责：
    1) 先用“依赖/调用/角色权重”挑出核心文件，避免把预算浪费在低价值文件上。
    2) 核心文件走 LLM 闭环改写，非核心文件走本地混淆，平衡效果与成本。
    3) 全流程保留语法闸门与元数据，确保后续 PDF/说明书阶段可追溯。
    """

    # 语言到种子目录的映射
    LANGUAGE_MAP = {
        "Java": "java/spring-boot-crud",
        "Python": "python/fastapi-crud",
        "Go": "go/gin-crud",
        "Node.js": "node/express-crud",  # 修正路径
        "PHP": "php/laravel-crud"
    }

    # 目录结构风格 (Phase 2)
    DIRECTORY_STYLES = {
        "Standard": {
            "controller": "controller",
            "service": "service",
            "repository": "repository",
            "entity": "entity",
            "model": "model",
            "dto": "dto",
            "config": "config",
            "utils": "utils",
            "common": "common"
        },
        "DDD": {
            "controller": "interfaces/web",
            "service": "application/service",
            "repository": "infrastructure/persistence",
            "entity": "domain/entity",
            "model": "domain/model",
            "dto": "interfaces/dto",
            "config": "infrastructure/config",
            "utils": "infrastructure/utils",
            "common": "domain/common"
        },
        "Obscure": {
            "controller": "web/endpoints",
            "service": "biz/logic",
            "repository": "data/access",
            "entity": "data/schema",
            "model": "data/types",
            "dto": "web/transfer",
            "config": "core/settings",
            "utils": "core/helpers",
            "common": "core/shared"
        },
        "Layered": {
            "controller": "presentation/controllers",
            "service": "application/services",
            "repository": "infrastructure/repositories",
            "entity": "domain/entities",
            "model": "domain/models",
            "dto": "application/dto",
            "config": "infrastructure/config",
            "utils": "shared/utils",
            "common": "shared/common"
        },
        "DDD-lite": {
            "controller": "interfaces/http",
            "service": "application/usecases",
            "repository": "domain/repositories",
            "entity": "domain/entities",
            "model": "domain/value_objects",
            "dto": "interfaces/dto",
            "config": "bootstrap/config",
            "utils": "shared/utils",
            "common": "shared/kernel"
        },
        "CQRS-lite": {
            "controller": "interfaces/api",
            "service": "application/commands",
            "repository": "infrastructure/readmodels",
            "entity": "domain/aggregates",
            "model": "application/queries",
            "dto": "interfaces/contracts",
            "config": "bootstrap/config",
            "utils": "shared/support",
            "common": "shared/kernel"
        },
        "ServiceRepo": {
            "controller": "api/controllers",
            "service": "core/services",
            "repository": "core/repositories",
            "entity": "core/entities",
            "model": "core/models",
            "dto": "api/dto",
            "config": "config",
            "utils": "utils",
            "common": "common"
        }
    }

    # 转换 Prompt 模板 (企业级) - 用于核心业务类
    HEAVY_TRANSFORM_PROMPT = """
你是一位资深企业级架构师。请将以下参考代码重构为 "{project_name}" 项目的生产级业务代码。

**设计理念**：本项目是一个真实的企业级生产系统，需要遵循高可用、高安全的架构设计原则。

## 参考代码
```{source_language}
{original_code}
```

## 重构要求（生产级标准）

1.  **企业级命名规范**
    *   **包名**: `{project_package}`
    *   **类名/变量名**: 使用清晰、专业的企业级命名，体现业务语义。
    *   示例：`User` → `{primary_entity}ManagementServiceEntity`
    *   示例：`id` → `primaryResourceIdentifier`
    *   示例：`name` → `businessEntityDisplayName`

2.  **完善的业务流程**
    *   在核心业务方法中，必须包含完整的企业级处理流程：
        1.  **缓存层处理**: 先检查 Redis 缓存，命中则直接返回
        2.  **分布式锁控制**: 使用 Redisson 获取分布式锁，防止并发冲突
        3.  **业务操作审计**: 记录完整的操作日志，包含操作人、时间、IP
        4.  **权限校验**: 使用位掩码计算用户权限级别

3.  **健壮的代码结构**
    *   所有数据库操作必须包含 `try-catch-finally` 异常处理
    *   关键操作前进行系统状态校验 `if (SystemValidator.checkRunningState())`
    *   使用建造者模式或工厂模式创建复杂对象

4.  **专业的中文文档**
    *   使用中文编写详细的 Javadoc/Docstring
    *   说明方法的业务用途、参数含义、返回值、可能的异常

## 项目信息
- 项目名称：{project_name}
- 核心业务实体：{primary_entity}
- 开发语言：{source_language}

## 输出要求
- 直接输出代码，不要包含 markdown 代码块标记
"""

    # 转换 Prompt 模板 (企业级) - 用于实体、工具、配置类
    LIGHT_TRANSFORM_PROMPT = """
你是一位资深企业级架构师。请将以下参考代码重构为 "{project_name}" 项目的生产级辅助代码。

**设计理念**：本项目是真实的企业级生产系统，所有代码都需要遵循高安全、可审计的设计标准。

## 参考代码
```{source_language}
{original_code}
```

## 重构要求（生产级标准）

1.  **企业级命名规范**
    *   **包名**: `{project_package}`
    *   **类名/变量名**: 使用清晰、专业的企业级命名。
    *   示例：`User` → `{primary_entity}DataTransferObject`
    *   示例：`id` → `primaryResourceIdentifier`
    *   示例：`name` → `entityDisplayName`

2.  **完善的实体字段**
    *   在原有字段基础上，添加企业级必备的审计字段：
        -   `createTimestamp`, `updateTimestamp`, `creatorUserId`
        -   `dataVersionNumber`, `recordStatusCode`, `auditTrailReference`
        -   `encryptionSaltValue`, `checksumDigest`
    *   每个字段都要有完整的 Getter/Setter 方法。

3.  **数据安全方法**
    *   为实体类添加以下安全相关方法：
        -   `validateDataIntegrity()`: 校验数据完整性
        -   `computeSecurityHash()`: 计算安全哈希值
        -   `toAuditLogString()`: 生成审计日志
        -   `cloneWithMaskedData()`: 创建脱敏副本
    *   方法内需要有完整的业务逻辑实现。

4.  **工具类扩展**
    *   如果是工具类，添加企业常用的静态方法：
        -   日期时间格式化、数据校验、敏感信息脱敏、摘要计算
    *   每个方法 10-20 行完整实现。

5.  **专业的中文文档**
    *   使用中文编写详细的 Javadoc/Docstring
    *   说明每个字段和方法的业务用途

## 项目信息
- 项目名称：{project_name}
- 核心业务实体：{primary_entity}
- 开发语言：{source_language}

## 输出要求
- 直接输出代码，不要包含 markdown 代码块标记
- 生成的代码量应为参考代码的 3-5 倍
"""

    def __init__(self, plan: Dict[str, Any], api_key: str = None):
        """
        初始化变换器

        Args:
            plan: 项目规划数据 (包含 genome)
            api_key: LLM API Key
        """
        self.plan = plan
        self.project_name = plan.get("project_name", "未命名项目")
        self.genome = plan.get("genome", {})
        self.target_language = self._normalize_language(self.genome.get("target_language", "Python"))
        code_cfg = self.plan.get("code_generation_config", {}) or {}

        # 代码阶段支持独立模型/提供商：不影响规划、页面、说明书等其他步骤。
        self.llm_provider_override = str(code_cfg.get("llm_provider_override", "") or "").strip()
        self.llm_model_override = str(code_cfg.get("llm_model_override", "") or "").strip()

        # 初始化 LLM 客户端
        client_model = self.llm_model_override or None
        client_provider = self.llm_provider_override or None
        self.client = DeepSeekClient(api_key=api_key, model=client_model, provider_name=client_provider)
        if self.llm_provider_override or self.llm_model_override:
            logger.info(
                "代码阶段LLM覆盖已启用: provider=%s, model=%s",
                self.llm_provider_override or "(follow-current)",
                self.llm_model_override or "(provider-default)",
            )

        # 初始化差异化引擎 (用于物理混淆)
        self.differentiator = CodeDifferentiator(plan)

        # 初始化控制流变换引擎 (Phase 1)
        self.control_flow_transformer = ControlFlowTransformer()

        # 初始化并行执行器
        self.executor = ParallelExecutor()

        # 确定主业务实体 (从 code_blueprint 中获取，或者智能推断)
        self.primary_entity = self._determine_primary_entity()

        # 生成项目包名
        self.project_package = self._generate_project_package()

        self.spec_builder = SpecBuilder(self.plan)
        self.structure_transformer = StructureTransformer()

        # 架构族约束下选择目录风格（Spec-first）
        style_name = self._pick_directory_style()
        self.dir_style_name = style_name
        self.dir_mapping = self.DIRECTORY_STYLES[style_name]
        logger.info(f"选定的目录结构风格: {style_name}")

        self.metadata_list = [] # 用于收集元数据
        # 这些参数决定“质量-成本”平衡：阈值越高，二次改写越多，调用成本也越高。
        self.novelty_threshold = float(code_cfg.get("novelty_threshold", self.DEFAULT_NOVELTY_THRESHOLD))
        self.max_rewrite_rounds = int(code_cfg.get("max_rewrite_rounds", self.DEFAULT_MAX_REWRITE_ROUNDS))
        self.rewrite_candidates = int(code_cfg.get("rewrite_candidates", self.DEFAULT_REWRITE_CANDIDATES))
        self.low_novelty_local_retry = bool(code_cfg.get("low_novelty_local_retry", True))
        self.heavy_search_ratio = float(code_cfg.get("heavy_search_ratio", self.DEFAULT_HEAVY_SEARCH_RATIO))
        self.file_novelty_budget = float(code_cfg.get("file_novelty_budget", self.novelty_threshold))
        self.enable_project_novelty_gate = bool(code_cfg.get("enable_project_novelty_gate", True))
        self.project_novelty_threshold = float(
            code_cfg.get("project_novelty_threshold", self.DEFAULT_PROJECT_NOVELTY_THRESHOLD)
        )
        self.max_risky_files = int(code_cfg.get("max_risky_files", self.DEFAULT_MAX_RISKY_FILES))
        self.max_syntax_fail_files = int(
            code_cfg.get("max_syntax_fail_files", self.DEFAULT_MAX_SYNTAX_FAIL_FILES)
        )
        self.min_ai_line_ratio = float(
            code_cfg.get("min_ai_line_ratio", self.DEFAULT_MIN_AI_LINE_RATIO)
        )
        self.enforce_file_gate = bool(
            code_cfg.get("enforce_file_gate", self.DEFAULT_ENFORCE_FILE_GATE)
        )
        # 默认仅对 AI 重写文件执行文件级硬闸门，避免低价值本地混淆文件批量拦截导致流水线中断。
        self.enforce_file_gate_on_obfuscation = bool(
            code_cfg.get("enforce_file_gate_on_obfuscation", False)
        )
        self.max_failed_files = int(
            code_cfg.get("max_failed_files", self.DEFAULT_MAX_FAILED_FILES)
        )
        self.max_llm_attempts_per_file = int(
            code_cfg.get("max_llm_attempts_per_file", self.DEFAULT_MAX_LLM_ATTEMPTS_PER_FILE)
        )
        self.llm_text_retries = int(
            code_cfg.get("llm_text_retries", self.DEFAULT_LLM_TEXT_RETRIES)
        )
        # 全局预算：限制整个项目代码阶段的 LLM 调用量，避免网关抖动时调用雪崩。
        self.max_total_llm_calls = int(
            code_cfg.get("max_total_llm_calls", self.DEFAULT_MAX_TOTAL_LLM_CALLS)
        )
        self.max_total_llm_failures = int(
            code_cfg.get("max_total_llm_failures", self.DEFAULT_MAX_TOTAL_LLM_FAILURES)
        )
        self.disable_llm_on_budget_exhausted = bool(
            code_cfg.get("disable_llm_on_budget_exhausted", self.DEFAULT_DISABLE_LLM_ON_BUDGET_EXHAUSTED)
        )
        self.disable_llm_on_failures = bool(
            code_cfg.get("disable_llm_on_failures", self.DEFAULT_DISABLE_LLM_ON_FAILURES)
        )
        self.history_forbidden_enabled = bool(code_cfg.get("history_forbidden_enabled", True))
        self.history_forbidden_max_files = int(code_cfg.get("history_forbidden_max_files", 120))
        self.enable_embedding_similarity = bool(code_cfg.get("enable_embedding_similarity", False))
        self.embedding_similarity_weight = float(code_cfg.get("embedding_similarity_weight", 0.15))
        self.embedding_model_name = str(
            code_cfg.get("embedding_model_name", "sentence-transformers/all-MiniLM-L6-v2")
        )
        self.embedding_max_chars = int(code_cfg.get("embedding_max_chars", 2400))
        feedback_path_cfg = str(code_cfg.get("forbidden_feedback_path", "data/forbidden_feedback.jsonl"))
        self.forbidden_feedback_path = (BASE_DIR / feedback_path_cfg).resolve()
        # 硬限制用于防止配置失控导致超长时任务（尤其是批量生成时）。
        self.max_rewrite_rounds = max(1, min(self.max_rewrite_rounds, 4))
        self.rewrite_candidates = max(1, min(self.rewrite_candidates, 3))
        self.heavy_search_ratio = max(0.15, min(self.heavy_search_ratio, 0.5))
        self.max_risky_files = max(0, self.max_risky_files)
        self.max_syntax_fail_files = max(0, self.max_syntax_fail_files)
        self.min_ai_line_ratio = max(0.0, min(self.min_ai_line_ratio, 1.0))
        self.max_failed_files = max(0, self.max_failed_files)
        self.max_llm_attempts_per_file = max(1, min(self.max_llm_attempts_per_file, 8))
        self.llm_text_retries = max(1, min(self.llm_text_retries, 3))
        self.max_total_llm_calls = max(0, min(self.max_total_llm_calls, 300))
        self.max_total_llm_failures = max(0, min(self.max_total_llm_failures, 100))
        self.embedding_similarity_weight = max(0.0, min(self.embedding_similarity_weight, 0.4))
        self.embedding_max_chars = max(400, min(self.embedding_max_chars, 8000))

        self.seed_fingerprints_ready = False
        self.novelty_analyzer: Optional[NoveltyAnalyzer] = None
        self.forbidden_index: Optional[ForbiddenPatternIndex] = None
        self.seed_files_cache: Dict[str, str] = {}
        self._llm_attempts_by_file: Dict[str, int] = {}
        self._llm_calls_total: int = 0
        self._llm_failures_total: int = 0
        self._llm_disabled_reason: str = ""

        logger.info(
            "代码阶段预算策略: max_total_llm_calls=%s, max_total_llm_failures=%s, disable_on_budget=%s, disable_on_failures=%s",
            self.max_total_llm_calls if self.max_total_llm_calls > 0 else "unlimited",
            self.max_total_llm_failures if self.max_total_llm_failures > 0 else "unlimited",
            self.disable_llm_on_budget_exhausted,
            self.disable_llm_on_failures,
        )

    @staticmethod
    def _normalize_language(language: str) -> str:
        """将配置中的语言名标准化到内部枚举，避免策略错配"""
        if not language:
            return "Python"
        lang = str(language).strip().lower()
        if lang.startswith("php"):
            return "PHP"
        if "node" in lang or lang in {"javascript", "js"}:
            return "Node.js"
        if lang.startswith("py"):
            return "Python"
        if lang in {"go", "golang"}:
            return "Go"
        if lang.startswith("java"):
            return "Java"
        mapping = {
            "python": "Python",
            "py": "Python",
            "java": "Java",
            "go": "Go",
            "golang": "Go",
            "node.js": "Node.js",
            "nodejs": "Node.js",
            "javascript": "Node.js",
            "js": "Node.js",
            "php": "PHP",
        }
        return mapping.get(lang, language if language in {"Python", "Java", "Go", "Node.js", "PHP"} else "Python")

    @staticmethod
    def _risk_adjusted_score(novelty_report: Dict[str, Any], forbidden_report: Dict[str, Any]) -> float:
        """
        统一比较分：避免只提升 novelty 却引入更高 forbidden 风险。
        """
        novelty = float((novelty_report or {}).get("novelty_score", 0.0))
        forbidden_risk = float((forbidden_report or {}).get("risk_score", 0.0))
        return novelty - forbidden_risk * 0.7

    def _is_quality_passed(
        self,
        novelty_report: Dict[str, Any],
        forbidden_report: Dict[str, Any],
        syntax_ok: bool,
    ) -> bool:
        if not syntax_ok:
            return False
        if float((novelty_report or {}).get("novelty_score", 0.0)) < self.file_novelty_budget:
            return False
        if ForbiddenPatternIndex.is_risky(forbidden_report):
            return False
        return True

    def _should_enforce_file_gate(self, use_llm: bool) -> bool:
        """
        判断当前文件是否执行“文件级硬闸门”。
        默认仅对 AI 重写文件启用；本地混淆文件通常只记录风险，不直接中断。
        """
        return bool(self.enforce_file_gate and (use_llm or self.enforce_file_gate_on_obfuscation))

    @staticmethod
    def _is_low_value_for_ai(path: str) -> bool:
        """
        判定“低业务价值文件”（迁移/样例/测试等），默认不优先消耗 AI 改写预算。
        """
        normalized = (path or "").replace("\\", "/").lower()
        low_keywords = (
            "/migration/", "/migrations/", "migration_", "migrate_", "alembic", "changelog",
            "/seed/", "/seeder/", "seed_", "fixture", "/fixtures/",
            "/test/", "/tests/", "_test.", ".spec.", ".mock.", "mock_", "example", "demo",
            "/vendor/", "/node_modules/", "/dist/", "/build/",
        )
        return any(k in normalized for k in low_keywords)

    def _path_priority_bias(self, path: str) -> float:
        """
        路径级业务权重修正，压低 migration/seed/test，抬高 controller/service。
        """
        normalized = (path or "").replace("\\", "/").lower()
        if self._is_low_value_for_ai(normalized):
            return -2.4
        if any(k in normalized for k in ("/controller", "/service", "/router", "/handler", "/api/")):
            return 0.9
        if any(k in normalized for k in ("/model", "/entity", "/domain", "/repository", "/repo")):
            return 0.4
        return 0.0

    def _consume_llm_attempt(self, file_path: str) -> bool:
        """
        单文件 LLM 调用预算控制：避免网关抖动时调用次数失控。
        """
        key = (file_path or "").replace("\\", "/")
        used = int(self._llm_attempts_by_file.get(key, 0))
        if used >= self.max_llm_attempts_per_file:
            return False
        self._llm_attempts_by_file[key] = used + 1
        return True

    @staticmethod
    def _is_probably_network_error(err: Exception) -> bool:
        """
        识别常见中转网关网络错误。用于失败熔断统计，不做精确分类。
        """
        msg = str(err).lower()
        markers = (
            "connectionerror",
            "connection reset",
            "connection aborted",
            "remotedisconnected",
            "proxyerror",
            "max retries exceeded",
            "远程主机强迫关闭了一个现有的连接",
        )
        return any(m in msg for m in markers)

    def _consume_global_llm_attempt(self, file_path: str) -> bool:
        """
        项目级 LLM 调用预算控制：防止在不稳定网关下全项目反复重试。
        """
        if self._llm_disabled_reason:
            return False

        if self.max_total_llm_calls <= 0:
            self._llm_calls_total += 1
            return True

        if self._llm_calls_total >= self.max_total_llm_calls:
            if self.disable_llm_on_budget_exhausted and not self._llm_disabled_reason:
                self._llm_disabled_reason = f"global_budget_exhausted({self.max_total_llm_calls})"
                logger.warning(
                    "代码阶段触发全局LLM预算上限，后续文件降级为本地混淆: %s",
                    self._llm_disabled_reason,
                )
            return False

        self._llm_calls_total += 1
        return True

    def _record_llm_call_failure(self, err: Exception):
        """
        记录 LLM 调用失败并按阈值触发熔断降级。
        """
        self._llm_failures_total += 1
        if not self.disable_llm_on_failures:
            return
        if self.max_total_llm_failures <= 0:
            return
        if self._llm_disabled_reason:
            return
        # 优先用网络错误触发熔断；普通业务错误仍按全局失败计数兜底。
        if self._is_probably_network_error(err) and self._llm_failures_total >= self.max_total_llm_failures:
            self._llm_disabled_reason = f"network_failures_exhausted({self._llm_failures_total})"
            logger.warning(
                "代码阶段网络失败达到阈值，后续文件降级为本地混淆: %s",
                self._llm_disabled_reason,
            )
        elif self._llm_failures_total >= self.max_total_llm_failures:
            self._llm_disabled_reason = f"llm_failures_exhausted({self._llm_failures_total})"
            logger.warning(
                "代码阶段LLM失败达到阈值，后续文件降级为本地混淆: %s",
                self._llm_disabled_reason,
            )

    # 需要AI重写的核心文件关键词 (其他文件只做物理混淆)
    CORE_FILE_KEYWORDS = ['controller', 'service', 'router', 'handler', 'view', 'api']

    # 目标AI处理的原始代码行数
    # 策略：AI重写约800行原始代码 → 膨胀后约1600行
    #       物理混淆剩余文件 → 膨胀后约1500行
    #       总计约3000-3500行，刚好满足软著要求
    TARGET_AI_LINES = 800  # 降低AI处理量，节省tokens

    # AI膨胀系数（保守估计）
    AI_EXPANSION_RATIO = 2.0

    # 不同语言的 AI 重写策略（优先保证业务核心文件由 AI 改写）
    LANGUAGE_AI_POLICY = {
        "Python": {"target_ai_lines": 1200, "min_ai_files": 3, "max_ai_files": 8},
        "Java": {"target_ai_lines": 1400, "min_ai_files": 3, "max_ai_files": 8},
        "Go": {"target_ai_lines": 1200, "min_ai_files": 3, "max_ai_files": 8},
        "Node.js": {"target_ai_lines": 1600, "min_ai_files": 3, "max_ai_files": 9},
        "PHP": {"target_ai_lines": 2000, "min_ai_files": 4, "max_ai_files": 10},
    }
    MAX_AI_FILES = 8
    # 默认策略改为低消耗档，严格档由 plan.code_generation_config 显式开启。
    DEFAULT_NOVELTY_THRESHOLD = 0.35
    DEFAULT_MAX_REWRITE_ROUNDS = 1
    DEFAULT_REWRITE_CANDIDATES = 1
    DEFAULT_HEAVY_SEARCH_RATIO = 0.20
    DEFAULT_PROJECT_NOVELTY_THRESHOLD = 0.32
    DEFAULT_MAX_RISKY_FILES = 8
    DEFAULT_MAX_SYNTAX_FAIL_FILES = 4
    DEFAULT_MIN_AI_LINE_RATIO = 0.10
    DEFAULT_ENFORCE_FILE_GATE = False
    DEFAULT_MAX_FAILED_FILES = 8
    DEFAULT_MAX_LLM_ATTEMPTS_PER_FILE = 2
    DEFAULT_LLM_TEXT_RETRIES = 1
    DEFAULT_MAX_TOTAL_LLM_CALLS = 12
    DEFAULT_MAX_TOTAL_LLM_FAILURES = 4
    DEFAULT_DISABLE_LLM_ON_BUDGET_EXHAUSTED = True
    DEFAULT_DISABLE_LLM_ON_FAILURES = True

    def _get_ai_policy(self, core_count: int, total_count: int) -> Dict[str, int]:
        """计算当前语言的 AI 改写策略（带自适应下限）"""
        base = self.LANGUAGE_AI_POLICY.get(self.target_language, {})
        target_ai_lines = int(base.get("target_ai_lines", self.TARGET_AI_LINES))
        base_min_ai_files = int(base.get("min_ai_files", 2))
        base_max_ai_files = int(base.get("max_ai_files", self.MAX_AI_FILES))
        min_ai_files = base_min_ai_files
        max_ai_files = base_max_ai_files

        # PHP/Node.js 对核心逻辑可读性更依赖 AI 改写，提升最低覆盖率
        if self.target_language in {"PHP", "Node.js"} and core_count > 0:
            adaptive_min = max(3, (core_count * 2 + 4) // 5)  # 约 40%
            min_ai_files = max(min_ai_files, adaptive_min)
        elif core_count > 0:
            adaptive_min = max(2, (core_count + 2) // 4)  # 约 25%
            min_ai_files = max(min_ai_files, adaptive_min)

        max_ai_files = min(base_max_ai_files, total_count)
        min_ai_files = min(min_ai_files, max_ai_files, total_count)
        if min_ai_files > max_ai_files:
            min_ai_files = max_ai_files

        return {
            "target_ai_lines": target_ai_lines,
            "min_ai_files": min_ai_files,
            "max_ai_files": max_ai_files
        }

    def _pick_directory_style(self) -> str:
        """
        按架构族选择目录模板。
        目标：同业务在不同项目上呈现不同架构指纹，同时保证目录映射可被后续导入修复逻辑消费。
        """
        family = str(self.spec_builder.get_project_spec().get("architecture_family", "")).lower()
        mapping = {
            "layered": ["Layered", "Standard", "ServiceRepo"],
            "ddd-lite": ["DDD-lite", "DDD", "ServiceRepo"],
            "cqrs-lite": ["CQRS-lite", "DDD-lite", "Obscure"],
            "service+repository": ["ServiceRepo", "Layered", "Standard"],
        }
        candidates = mapping.get(family, list(self.DIRECTORY_STYLES.keys()))
        candidates = [x for x in candidates if x in self.DIRECTORY_STYLES]
        if not candidates:
            candidates = list(self.DIRECTORY_STYLES.keys())
        rng = random.Random(int(hashlib.md5(self.project_name.encode("utf-8")).hexdigest()[:8], 16))
        return rng.choice(candidates)

    def _prepare_seed_fingerprints(self, seed_files: Dict[str, str]) -> None:
        """初始化种子相似度分析器。"""
        if self.seed_fingerprints_ready and self.seed_files_cache:
            return
        self.seed_files_cache = dict(seed_files)
        history_corpus: List[str] = []
        if self.history_forbidden_enabled:
            history_roots: List[str] = []
            history_base = BASE_DIR / "output"
            if history_base.exists():
                for project_dir in history_base.iterdir():
                    if not project_dir.is_dir() or project_dir.name == self.project_name:
                        continue
                    aligned = project_dir / "aligned_code"
                    if aligned.exists():
                        history_roots.append(str(aligned))
            history_corpus = ForbiddenPatternIndex.collect_history_corpus(
                history_roots=history_roots,
                max_files=self.history_forbidden_max_files,
            )
            if history_corpus:
                logger.info(f"已加载历史负约束语料: {len(history_corpus)} 份片段")

        novelty_seed_files = dict(seed_files)
        if history_corpus:
            for idx, snippet in enumerate(history_corpus):
                novelty_seed_files[f"history_{idx}.txt"] = snippet

        self.novelty_analyzer = NoveltyAnalyzer(
            novelty_seed_files,
            self.target_language,
            enable_embedding=self.enable_embedding_similarity,
            embedding_weight=self.embedding_similarity_weight,
            embedding_model_name=self.embedding_model_name,
            embedding_max_chars=self.embedding_max_chars,
        )
        self.forbidden_index = ForbiddenPatternIndex(
            seed_files,
            extra_corpus=history_corpus,
            feedback_path=str(self.forbidden_feedback_path),
        )
        self.seed_fingerprints_ready = True

    def _extract_import_tokens(self, content: str, language: str) -> List[str]:
        """提取文件中的依赖引用 token，用于构建轻量依赖图。"""
        tokens: List[str] = []
        lang = language

        try:
            if lang == "Python":
                for match in re.finditer(r'^\s*from\s+([.\w]+)\s+import', content, flags=re.MULTILINE):
                    module = match.group(1).replace(".", " ")
                    tokens.extend(module.split())
                for match in re.finditer(r'^\s*import\s+([.\w,\s]+)', content, flags=re.MULTILINE):
                    chunks = re.split(r'[, ]+', match.group(1).strip())
                    for c in chunks:
                        c = c.strip()
                        if c:
                            tokens.extend(c.replace(".", " ").split())
            elif lang == "Java":
                for match in re.finditer(r'^\s*import\s+([A-Za-z0-9_.*]+)\s*;', content, flags=re.MULTILINE):
                    module = match.group(1).replace("*", "")
                    tokens.extend(module.replace(".", " ").split())
            elif lang == "Go":
                for match in re.finditer(r'"([^"]+)"', content):
                    module = match.group(1)
                    tokens.extend(module.replace("/", " ").split())
            elif lang == "PHP":
                for match in re.finditer(r'^\s*use\s+([A-Za-z0-9_\\]+)\s*;', content, flags=re.MULTILINE):
                    module = match.group(1).replace("\\", " ")
                    tokens.extend(module.split())
            elif lang == "Node.js":
                for match in re.finditer(r'require\(\s*[\'"]([^\'"]+)[\'"]\s*\)', content):
                    module = match.group(1).replace("/", " ")
                    tokens.extend(module.split())
                for match in re.finditer(r'from\s+[\'"]([^\'"]+)[\'"]', content):
                    module = match.group(1).replace("/", " ")
                    tokens.extend(module.split())
        except Exception as e:
            logger.debug(f"提取 import token 失败: {e}")

        return [x.lower().strip("._-/") for x in tokens if x.strip("._-/")]

    def _extract_symbols(self, content: str, language: str) -> List[str]:
        """提取可被其他文件调用的符号名。"""
        symbols: List[str] = []

        try:
            if language == "Python":
                symbols.extend(re.findall(r'^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)', content, flags=re.MULTILINE))
                symbols.extend(re.findall(r'^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', content, flags=re.MULTILINE))
            elif language == "Java":
                symbols.extend(re.findall(r'\bclass\s+([A-Za-z_][A-Za-z0-9_]*)', content))
                symbols.extend(re.findall(r'(?:public|private|protected)\s+[A-Za-z0-9_<>\[\]]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', content))
            elif language == "Go":
                symbols.extend(re.findall(r'^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+struct', content, flags=re.MULTILINE))
                symbols.extend(re.findall(r'^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(', content, flags=re.MULTILINE))
            elif language == "PHP":
                symbols.extend(re.findall(r'\bclass\s+([A-Za-z_][A-Za-z0-9_]*)', content))
                symbols.extend(re.findall(r'\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', content))
            elif language == "Node.js":
                symbols.extend(re.findall(r'\bclass\s+([A-Za-z_][A-Za-z0-9_]*)', content))
                symbols.extend(re.findall(r'\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', content))
        except Exception as e:
            logger.debug(f"提取符号失败: {e}")

        return [s for s in symbols if len(s) >= 3]

    def _build_priority_profiles(self, seed_files: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        构建文件优先级画像：
        - 路径角色权重
        - import 依赖入度
        - 调用关系入度
        - 代码行数权重

        设计目标不是“学术最优排序”，而是快速抓住最可能影响业务指纹的文件，
        让有限 AI 改写预算尽量命中 Controller/Service 等核心层。
        """
        profiles: List[Dict[str, Any]] = []
        alias_to_paths: Dict[str, set] = {}

        role_weight = {
            "controller": 2.9,
            "service": 2.7,
            "repository": 2.2,
            "model": 1.9,
            "config": 1.3,
            "utility": 1.1,
            "general": 0.9,
        }

        for relative_path, content in seed_files.items():
            normalized = relative_path.replace("\\", "/")
            stem = Path(normalized).stem.lower()
            parent = Path(normalized).parent.name.lower()
            role = self.spec_builder.infer_file_role(normalized)
            lines = max(1, len(content.splitlines()))
            symbols = [s.lower() for s in self._extract_symbols(content, self.target_language)]
            imports = self._extract_import_tokens(content, self.target_language)
            call_candidates = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', content)

            profile = {
                "path": normalized,
                "content": content,
                "lines": lines,
                "role": role,
                "role_score": role_weight.get(role, 0.9),
                "path_bias": self._path_priority_bias(normalized),
                "low_value_for_ai": self._is_low_value_for_ai(normalized),
                "symbols": symbols,
                "imports": imports,
                "calls": [c.lower() for c in call_candidates if len(c) >= 3],
                "inbound_import": 0,
                "outbound_import": 0,
                "inbound_call": 0,
                "outbound_call": 0,
                "priority_score": 0.0,
                "is_core": False,
            }
            profiles.append(profile)

            # 构建“模块别名 -> 文件路径”索引，后续用来粗粒度推断 import 指向。
            # 这里允许近似映射，优先保证速度和鲁棒性，而不是静态分析完美精确。
            aliases = {stem}
            if parent:
                aliases.add(parent)
                aliases.add(f"{parent}_{stem}")
                aliases.add(f"{parent}{stem}")
            for alias in aliases:
                alias_to_paths.setdefault(alias, set()).add(normalized)

        symbol_owner: Dict[str, str] = {}
        for item in profiles:
            for sym in item["symbols"]:
                # 多文件同名时不覆盖，避免错误归因
                symbol_owner.setdefault(sym, item["path"])

        path_to_profile = {p["path"]: p for p in profiles}

        for item in profiles:
            import_targets = set()
            for token in item["imports"]:
                for candidate_path in alias_to_paths.get(token, set()):
                    if candidate_path != item["path"]:
                        import_targets.add(candidate_path)
            item["outbound_import"] = len(import_targets)
            for target in import_targets:
                path_to_profile[target]["inbound_import"] += 1

            call_targets = set()
            for call_name in item["calls"]:
                owner = symbol_owner.get(call_name)
                if owner and owner != item["path"]:
                    call_targets.add(owner)
            item["outbound_call"] = len(call_targets)
            for target in call_targets:
                path_to_profile[target]["inbound_call"] += 1

        for item in profiles:
            line_score = min(item["lines"] / 180.0, 2.4)
            # priority_score 是“可解释打分”：角色 + 规模 + 被依赖程度。
            # 入度权重大于出度，目的是优先选“被大量引用”的中枢文件做改写。
            priority = (
                item["role_score"]
                + item.get("path_bias", 0.0)
                + line_score
                + item["inbound_import"] * 0.9
                + item["inbound_call"] * 1.1
                + item["outbound_import"] * 0.25
                + item["outbound_call"] * 0.2
            )
            item["priority_score"] = round(priority, 4)

        sorted_profiles = sorted(profiles, key=lambda x: x["priority_score"], reverse=True)
        score_values = [x["priority_score"] for x in sorted_profiles]
        # top 40% 作为“动态核心阈值”，可适配不同规模项目（避免固定阈值失灵）。
        pivot_index = max(0, int(len(score_values) * 0.4) - 1)
        core_threshold = score_values[pivot_index] if score_values else 0.0

        for item in sorted_profiles:
            explicit_core = any(k in item["path"].lower() for k in self.CORE_FILE_KEYWORDS)
            item["is_core"] = explicit_core or item["priority_score"] >= core_threshold
        total_files = max(1, len(sorted_profiles))
        for idx, item in enumerate(sorted_profiles, start=1):
            item["priority_rank"] = idx
            item["total_files"] = total_files

        top_samples = ", ".join(
            f"{Path(p['path']).name}:{p['priority_score']}"
            for p in sorted_profiles[:6]
        )
        logger.info(f"依赖优先级分析完成，Top文件: {top_samples}")
        return sorted_profiles

    def _select_ai_file_profiles(self, profiles: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, Dict[str, int]]:
        """根据优先级画像挑选 AI 改写文件。"""
        core_files = [p for p in profiles if p.get("is_core")]
        other_files = [p for p in profiles if not p.get("is_core")]
        logger.info(f"文件分类: 核心文件={len(core_files)}个, 其他文件={len(other_files)}个")

        ai_files: List[Dict[str, Any]] = []
        estimated_ai_lines = 0
        selected_paths = set()
        policy = self._get_ai_policy(len(core_files), len(profiles))
        target_ai_lines = policy["target_ai_lines"]
        min_ai_files = policy["min_ai_files"]
        max_ai_files = policy["max_ai_files"]

        core_business_files = [f for f in core_files if not bool(f.get("low_value_for_ai"))]
        core_low_value_files = [f for f in core_files if bool(f.get("low_value_for_ai"))]
        other_business_files = [f for f in other_files if not bool(f.get("low_value_for_ai"))]
        other_low_value_files = [f for f in other_files if bool(f.get("low_value_for_ai"))]
        low_value_total = len(core_low_value_files) + len(other_low_value_files)
        if low_value_total:
            logger.info(f"检测到低业务价值文件 {low_value_total} 个（migration/seed/test 等），将后置选择")

        for f in core_business_files:
            need_more_lines = estimated_ai_lines < target_ai_lines
            need_more_files = len(ai_files) < min_ai_files
            if (need_more_lines or need_more_files) and len(ai_files) < max_ai_files:
                ai_files.append(f)
                selected_paths.add(f["path"])
                estimated_ai_lines += int(f["lines"] * self.AI_EXPANSION_RATIO)

        if estimated_ai_lines < target_ai_lines and len(ai_files) < max_ai_files:
            for f in other_business_files:
                if f["path"] in selected_paths:
                    continue
                ai_files.append(f)
                selected_paths.add(f["path"])
                estimated_ai_lines += int(f["lines"] * self.AI_EXPANSION_RATIO)
                if estimated_ai_lines >= target_ai_lines or len(ai_files) >= max_ai_files:
                    break

        # 兜底：若仍未达到最低 AI 文件数，再从低价值文件补位，避免“文件数下限”失效。
        if len(ai_files) < min_ai_files and len(ai_files) < max_ai_files:
            for f in core_low_value_files + other_low_value_files:
                if f["path"] in selected_paths:
                    continue
                ai_files.append(f)
                selected_paths.add(f["path"])
                estimated_ai_lines += int(f["lines"] * self.AI_EXPANSION_RATIO)
                if len(ai_files) >= min_ai_files or len(ai_files) >= max_ai_files:
                    break

        no_ai_files = [f for f in profiles if f["path"] not in selected_paths]
        logger.info(
            f"AI策略: target_ai_lines={target_ai_lines}, min_ai_files={min_ai_files}, max_ai_files={max_ai_files}"
        )
        logger.info(
            f"AI处理决策: AI重写={len(ai_files)}个(预估{int(estimated_ai_lines)}行), 仅混淆={len(no_ai_files)}个"
        )
        return ai_files, no_ai_files, estimated_ai_lines, policy

    def _resolve_llm_parallel_policy(self, ai_file_count: int) -> Tuple[int, float]:
        """
        根据当前传输协议动态确定 AI 并发策略。

        经验规则：
        - 默认：小批量 3 并发，大批量 2 并发。
        - http + responses：降到 1 并发并加大间隔，避免中转站在长响应场景下出现 ProxyError/断流。
        - 其余 http：保持最多 2 并发，略增延迟平滑流量。
        """
        concurrency = 3 if ai_file_count <= 4 else 2
        delay = 0.25

        try:
            http_mode = bool(self.client._should_use_http_compatible())
            api_style = str(self.client._resolve_api_style())
        except Exception:
            http_mode = False
            api_style = "chat"

        if http_mode and api_style == "responses":
            concurrency = 1
            delay = max(delay, 0.7)
            logger.info("检测到 http/responses 模式，代码阶段启用稳态串行策略（concurrency=1）")
        elif http_mode:
            concurrency = min(concurrency, 2)
            delay = max(delay, 0.35)

        return max(1, int(concurrency)), float(delay)

    def transform_seed_to_project(self, output_dir: Path) -> List[str]:
        """
        执行完整的转换流程：种子 -> 智能分流 -> 输出
        (V3.1 动态版：根据行数动态决定AI处理文件数)

        策略：
        1. 优先处理核心文件 (Controller/Service) 用AI重写
        2. 检测AI代码行数，若不足2000行则追加更多文件
        3. 剩余文件仅做物理混淆

        Args:
            output_dir: 代码输出目录

        Returns:
            List[str]: 生成的文件路径列表
        """
        logger.info(f"开始代码转换流程 (Dynamic Mode): {self.target_language} -> {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        self._save_project_spec(output_dir)

        # 1. 加载种子文件
        seed_files = self._load_seed_files(self.target_language)
        if not seed_files:
            logger.error(f"未找到 {self.target_language} 的种子文件")
            return []
        self._prepare_seed_fingerprints(seed_files)
        profiles = self._build_priority_profiles(seed_files)
        ai_files, no_ai_files, _, _ = self._select_ai_file_profiles(profiles)

        # 4. 准备任务
        # 拆分 AI 与本地任务是为了隔离慢调用：AI 队列受并发控制，本地任务尽快吞吐。
        ai_task_list = []
        local_task_list = []

        # 4.1 AI处理文件
        for f in ai_files:
            def task_func(rp=f['path'], c=f['content'], fp=f):
                return self._process_single_file(
                    rp, c, use_llm=True, processing_mode="ai_rewrite", file_profile=fp
                )
            ai_task_list.append(task_func)

        # 4.2 仅混淆文件
        for f in no_ai_files:
            def task_func(rp=f['path'], c=f['content'], fp=f):
                return self._process_single_file(
                    rp, c, use_llm=False, processing_mode="obfuscation", file_profile=fp
                )
            local_task_list.append(task_func)

        logger.info(f"准备处理 {len(ai_task_list) + len(local_task_list)} 个文件 (AI调用: {len(ai_files)}次)...")
        llm_concurrency, llm_delay = self._resolve_llm_parallel_policy(len(ai_files))

        ai_results = []
        if ai_task_list:
            ai_results = self.executor.run_sync(
                self.executor.run_llm_tasks(
                    ai_task_list,
                    concurrency=llm_concurrency,
                    delay=llm_delay,
                    desc="Transpiling AI Files"
                )
            )
        local_results = []
        if local_task_list:
            local_results = self.executor.run_sync(
                self.executor.run_cpu_tasks(
                    local_task_list,
                    desc="Transpiling Local Files"
                )
            )
        results = ai_results + local_results

        # 4. 写入文件
        # 这里坚持串行写盘，避免并发写同目录时出现文件竞争和日志顺序混乱。
        generated_files = []
        collected_metadata = []
        failed_result_count = sum(1 for x in results if not x)
        write_failed_count = 0
        fallback_result_count = 0

        for res in results:
            if not res: # 任务失败返回 None
                continue

            new_filename, final_code, metadata = res # Unpack 3 values

            # 构建完整输出路径
            output_path = output_dir / new_filename
            output_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(final_code)

                generated_files.append(str(output_path))
                if metadata:
                    collected_metadata.append(metadata)
                    if metadata.get("process_mode") == "fallback_error":
                        fallback_result_count += 1
                logger.debug(f"✓ 写入文件: {output_path.name}")
            except Exception as e:
                logger.error(f"写入文件失败 {output_path}: {e}")
                write_failed_count += 1
                failed_result_count += 1

        if write_failed_count:
            logger.warning(f"写盘失败统计: {write_failed_count} 个文件写入失败，已计入 failed_files")
        if fallback_result_count:
            logger.warning(f"回退产物统计: {fallback_result_count} 个文件使用 fallback_error 兜底")

        # 保存元数据 (Task 3)
        self._save_metadata(output_dir, collected_metadata)
        quality_report = self._build_quality_report(
            collected_metadata,
            failed_files_count=failed_result_count
        )
        self._save_quality_report(output_dir, quality_report)
        if self.enable_project_novelty_gate and not quality_report.get("passed", True):
            raise RuntimeError(
                f"项目级新颖度质量闸门未通过: avg={quality_report.get('avg_novelty', 0):.3f}, "
                f"risky_files={quality_report.get('risky_file_count', 0)}, "
                f"syntax_fail={quality_report.get('syntax_fail_count', 0)}, "
                f"ai_ratio={quality_report.get('ai_line_ratio', 0):.3f}, "
                f"failed_files={quality_report.get('failed_files_count', 0)}"
            )

        logger.info(f"代码转换完成，成功生成 {len(generated_files)}/{len(seed_files)} 个文件")
        return generated_files

    def _evaluate_novelty(self, code: str, source_code: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        novelty_report = {
            "novelty_score": 0.0,
            "max_similarity": 1.0,
            "risk_level": "unknown",
            "business_consistency": 0.0,
            "seed_best_match": {"path": "", "blended_similarity": 1.0},
            "source_similarity": {"blended_similarity": 1.0},
        }
        forbidden_report = {
            "window_hits": 0,
            "line_hits": 0,
            "window_density": 0.0,
            "risk_score": 0.0,
            "samples": [],
        }

        if self.novelty_analyzer:
            try:
                novelty_report = self.novelty_analyzer.evaluate(code, source_code)
            except Exception as e:
                logger.debug(f"新颖度评估失败: {e}")
        if self.forbidden_index:
            try:
                forbidden_report = self.forbidden_index.inspect(code)
            except Exception as e:
                logger.debug(f"禁用片段检测失败: {e}")
        return novelty_report, forbidden_report

    def _rewrite_with_closed_loop(
        self,
        original_code: str,
        file_path: str,
        file_profile: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """
        AI闭环改写：
        1) 每轮多候选生成
        2) token/AST 新颖度评分 + 禁用片段检测
        3) 低于阈值自动再改写

        这是“防模板化”的核心环节：不直接使用第一版输出，而是经过评分筛选。
        """
        best_code = original_code
        best_novelty, best_forbidden = self._evaluate_novelty(best_code, original_code)
        best_score = -999.0

        novelty_feedback = None
        forbidden_feedback = None
        heavy_search = True
        if file_profile:
            rank = int(file_profile.get("priority_rank", 1))
            total = max(1, int(file_profile.get("total_files", 1)))
            ratio = rank / total
            heavy_search = ratio <= self.heavy_search_ratio

        for round_idx in range(1, self.max_rewrite_rounds + 1):
            # 仅首轮启用多候选，后续回合单候选迭代，减少 token 成本。
            round_candidates = self.rewrite_candidates if (round_idx == 1 and heavy_search) else 1
            round_best_changed = False
            budget_exhausted = False
            for variant in range(round_candidates):
                if not self._consume_llm_attempt(file_path):
                    budget_exhausted = True
                    logger.warning(
                        f"文件 {file_path} 达到单文件 LLM 调用上限({self.max_llm_attempts_per_file})，停止继续候选搜索"
                    )
                    break
                if not self._consume_global_llm_attempt(file_path):
                    budget_exhausted = True
                    logger.warning(
                        "文件 %s 触发项目级 LLM 预算限制，停止继续候选搜索",
                        file_path,
                    )
                    break
                directive = self.spec_builder.build_rewrite_directive(
                    file_path,
                    self.target_language,
                    attempt=round_idx,
                    novelty_feedback=novelty_feedback,
                    forbidden_feedback=forbidden_feedback,
                )
                directive += f"\n- 变体编号: {round_idx}.{variant + 1}"
                candidate = self._transform_file(
                    original_code,
                    file_path,
                    extra_requirements=directive,
                    file_profile=file_profile,
                )
                semantic_comments = self.spec_builder.semantic_comments(file_path, self.target_language, count=6)
                candidate = self.structure_transformer.apply_semantic_noise(
                    candidate,
                    self.target_language,
                    semantic_comments,
                    insert_ratio=0.24,
                )
                candidate = self.structure_transformer.rewrite_semantic_equivalent(
                    candidate,
                    self.target_language,
                    intensity=0.13,
                )

                syntax_ok = self._validate_syntax(candidate, self.target_language)
                novelty_report, forbidden_report = self._evaluate_novelty(candidate, original_code)
                biz_score = self.spec_builder.business_consistency_score(candidate, file_path, self.target_language)
                novelty_report["business_consistency"] = round(biz_score, 4)
                # 综合分：新颖度优先，禁用片段风险次之，语法是否可落地作为硬约束奖励/惩罚。
                candidate_score = (
                    novelty_report.get("novelty_score", 0.0)
                    - forbidden_report.get("risk_score", 0.0) * 0.5
                    + (0.06 if syntax_ok else -0.25)
                    + biz_score * 0.22
                )

                if candidate_score > best_score:
                    previous_best = best_code
                    best_score = candidate_score
                    best_code = candidate
                    best_novelty = novelty_report
                    best_forbidden = forbidden_report
                    if best_code != previous_best:
                        round_best_changed = True

            if budget_exhausted:
                break

            novelty_feedback = best_novelty
            forbidden_feedback = best_forbidden

            passed_novelty = best_novelty.get("novelty_score", 0.0) >= self.file_novelty_budget
            passed_forbidden = not ForbiddenPatternIndex.is_risky(best_forbidden)
            passed_syntax = self._validate_syntax(best_code, self.target_language)
            if passed_novelty and passed_forbidden and passed_syntax:
                break
            # 若连续一轮没有改进且仍高度相似，提前结束，避免“无效烧 token”。
            if (
                round_idx >= 1
                and not round_best_changed
                and best_code == original_code
                and best_novelty.get("max_similarity", 1.0) >= 0.95
            ):
                logger.warning(f"文件 {file_path} 闭环未取得有效改写，提前结束以节省调用")
                break

        if not self._validate_syntax(best_code, self.target_language):
            logger.warning(f"文件 {file_path} AI闭环结果语法失败，回退原始内容")
            return original_code, best_novelty, best_forbidden

        return best_code, best_novelty, best_forbidden

    def _second_pass_local_rewrite(
        self,
        code: str,
        source_code: str,
        file_path: str,
        novelty_report: Dict[str, Any],
        forbidden_report: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """
        对“仅混淆文件”做低成本二次本地改写，避免与种子过近。
        """
        if not self.low_novelty_local_retry:
            return code, novelty_report, forbidden_report

        need_retry = (
            novelty_report.get("novelty_score", 0.0) < self.file_novelty_budget
            or ForbiddenPatternIndex.is_risky(forbidden_report)
        )
        if not need_retry:
            return code, novelty_report, forbidden_report

        retry_code = self._simple_entity_replace(code, file_path)
        retry_code = self._apply_step_with_guard(
            retry_code,
            lambda c: self._obfuscate_variable_names(c, self.target_language),
            "二次变量混淆",
            file_path,
        )
        semantic_comments = self.spec_builder.semantic_comments(file_path, self.target_language, count=4)
        retry_code = self.structure_transformer.apply_semantic_noise(
            retry_code,
            self.target_language,
            semantic_comments,
            insert_ratio=0.16,
        )

        if not self._validate_syntax(retry_code, self.target_language):
            return code, novelty_report, forbidden_report

        retry_novelty, retry_forbidden = self._evaluate_novelty(retry_code, source_code)
        if self._risk_adjusted_score(retry_novelty, retry_forbidden) >= self._risk_adjusted_score(novelty_report, forbidden_report):
            return retry_code, retry_novelty, retry_forbidden
        return code, novelty_report, forbidden_report

    def _process_single_file(
        self,
        relative_path: str,
        content: str,
        use_llm: bool = True,
        processing_mode: str = "",
        file_profile: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str, Dict]]:
        """
        单个文件的处理逻辑 (在线程池中运行)

        Args:
            relative_path: 文件相对路径
            content: 文件内容
            use_llm: 是否调用LLM重写 (核心文件=True, 基础文件=False)

        Returns:
            (new_filename, processed_code, metadata)
            正常情况下总会返回三元组；异常路径会返回 fallback_error 产物以维持流水线连续性。

        流程分层：
        - A: 语义改写层（LLM 或本地替换）
        - B: 结构混淆层（多 pass + 每步保护）
        - C: 新颖度补偿层（仅本地文件触发轻量二次改写）
        - D: 重命名/导入修复 + 元数据落盘
        """
        try:
            novelty_report: Dict[str, Any] = {}
            forbidden_report: Dict[str, Any] = {}
            effective_use_llm = bool(use_llm and not self._llm_disabled_reason)
            effective_processing_mode = processing_mode or ("ai_rewrite" if effective_use_llm else "obfuscation")
            if use_llm and not effective_use_llm:
                effective_processing_mode = "obfuscation_degraded"
                logger.warning(
                    "文件 %s 跳过LLM改写，使用本地混淆（原因: %s）",
                    relative_path,
                    self._llm_disabled_reason or "llm_disabled",
                )

            if effective_use_llm:
                transformed_code, novelty_report, forbidden_report = self._rewrite_with_closed_loop(
                    content, relative_path, file_profile=file_profile
                )
            else:
                transformed_code = self._simple_entity_replace(content, relative_path)

            if not self._validate_syntax(transformed_code, self.target_language):
                logger.warning(f"文件 {relative_path} 初始变换结果语法失败，回退原始代码")
                transformed_code = content

            # B. 多阶段混淆（Python 采用“每步语法闸门”，失败即回滚该步）
            obfuscated_code = transformed_code
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self._obfuscate_variable_names(c, self.target_language),
                "变量名混淆",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self.control_flow_transformer.transform(c, self.target_language),
                "控制流变换",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self._obfuscate_constants(c, self.target_language),
                "常量混淆",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self._transform_expressions(c, self.target_language),
                "表达式混淆",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self.structure_transformer.rewrite_semantic_equivalent(
                    c,
                    self.target_language,
                    intensity=0.11 if effective_use_llm else 0.08,
                ),
                "语义等价重写",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self._inject_todo_markers(c, self.target_language, relative_path),
                "TODO注入",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self._inject_debug_scraps(c, self.target_language),
                "调试痕迹注入",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self.differentiator.remove_some_comments(c, self.target_language),
                "注释删减",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self.differentiator.apply_comment_irregularity(c, self.target_language),
                "注释不规则化",
                relative_path
            )
            obfuscated_code = self._apply_step_with_guard(
                obfuscated_code,
                lambda c: self._apply_physical_obfuscation(c, self.target_language),
                "物理层混淆",
                relative_path
            )

            candidate_code = obfuscated_code
            if not self._validate_syntax(obfuscated_code, self.target_language):
                logger.warning(f"文件 {relative_path} 语法校验失败，回退到变换前版本")
                candidate_code = transformed_code

            if not novelty_report:
                novelty_report, forbidden_report = self._evaluate_novelty(candidate_code, content)
            if not effective_use_llm:
                # 非 AI 文件也做一次低成本补偿，避免“全量仅混淆”时相似度过高。
                candidate_code, novelty_report, forbidden_report = self._second_pass_local_rewrite(
                    candidate_code,
                    content,
                    relative_path,
                    novelty_report,
                    forbidden_report,
                )

            # E. 目录重构与包名修正 (Task 2)
            new_filename = self._rename_file(relative_path, self.primary_entity)
            final_code = self._fix_package_and_imports(candidate_code, new_filename)
            final_syntax_ok = self._validate_syntax(final_code, self.target_language)
            syntax_recovered = False
            if not final_syntax_ok:
                # 包名/导入修正可能引入语法问题，优先回退到语法可用版本。
                logger.warning(f"文件 {relative_path} 在包名修正后语法失效，尝试回退可用版本")
                if self._validate_syntax(candidate_code, self.target_language):
                    final_code = candidate_code
                    final_syntax_ok = True
                    syntax_recovered = True
                elif self._validate_syntax(content, self.target_language):
                    final_code = content
                    final_syntax_ok = True
                    syntax_recovered = True

            final_novelty, final_forbidden = self._evaluate_novelty(final_code, content)
            final_novelty["business_consistency"] = self.spec_builder.business_consistency_score(
                final_code,
                new_filename,
                self.target_language,
            )
            if effective_use_llm and (
                final_novelty.get("novelty_score", 0.0) < self.file_novelty_budget
                or ForbiddenPatternIndex.is_risky(final_forbidden)
            ):
                retry_code, retry_novelty, retry_forbidden = self._second_pass_local_rewrite(
                    final_code,
                    content,
                    relative_path,
                    final_novelty,
                    final_forbidden,
                )
                retry_novelty["business_consistency"] = self.spec_builder.business_consistency_score(
                    retry_code,
                    new_filename,
                    self.target_language,
                )
                if self._risk_adjusted_score(retry_novelty, retry_forbidden) >= self._risk_adjusted_score(final_novelty, final_forbidden):
                    final_code = retry_code
                    final_novelty = retry_novelty
                    final_forbidden = retry_forbidden

            quality_passed = self._is_quality_passed(final_novelty, final_forbidden, final_syntax_ok)
            quality_gate_enforced = self._should_enforce_file_gate(effective_use_llm)
            if quality_gate_enforced and not quality_passed:
                raise RuntimeError(
                    f"文件级质量闸门未通过: path={relative_path}, "
                    f"novelty={float(final_novelty.get('novelty_score', 0.0)):.3f}, "
                    f"forbidden={float(final_forbidden.get('risk_score', 0.0)):.3f}, "
                    f"syntax_ok={bool(final_syntax_ok)}"
                )
            if self.enforce_file_gate and not quality_gate_enforced and not quality_passed:
                logger.warning(
                    f"非AI文件质量未达标但不执行硬拦截: path={relative_path}, "
                    f"novelty={float(final_novelty.get('novelty_score', 0.0)):.3f}, "
                    f"forbidden={float(final_forbidden.get('risk_score', 0.0)):.3f}"
                )

            # F. 元数据提取 (Task 3)
            metadata = self._extract_metadata(final_code, new_filename) or {}
            metadata["file_path"] = new_filename.replace("\\", "/")
            metadata["source_path"] = relative_path.replace("\\", "/")
            metadata["process_mode"] = effective_processing_mode
            metadata["line_count"] = len(final_code.splitlines())
            metadata["novelty_score"] = float(final_novelty.get("novelty_score", 0.0))
            metadata["max_similarity"] = float(final_novelty.get("max_similarity", 1.0))
            metadata["forbidden_risk"] = float(final_forbidden.get("risk_score", 0.0))
            metadata["forbidden_window_density"] = float(final_forbidden.get("window_density", 0.0))
            metadata["forbidden_line_hits"] = int(final_forbidden.get("line_hits", 0))
            metadata["novelty_risk_level"] = final_novelty.get("risk_level", "unknown")
            metadata["business_consistency"] = float(final_novelty.get("business_consistency", 0.0))
            metadata["spec_version"] = self.spec_builder.get_project_spec().get("version", "spec-v1")
            metadata["architecture_family"] = self.spec_builder.get_project_spec().get("architecture_family", "Layered")
            metadata["syntax_ok"] = bool(final_syntax_ok)
            metadata["syntax_recovered"] = bool(syntax_recovered)
            metadata["quality_passed"] = bool(quality_passed)
            metadata["quality_gate_enforced"] = bool(quality_gate_enforced)
            metadata["quality_scope"] = "ai_rewrite" if effective_use_llm else "obfuscation"

            # 在线学习闭环：将高相似样本回流到 forbidden feedback。
            if (
                float(metadata.get("novelty_score", 0.0)) < self.file_novelty_budget
                or ForbiddenPatternIndex.is_risky(final_forbidden)
            ):
                ForbiddenPatternIndex.append_feedback(
                    feedback_path=str(self.forbidden_feedback_path),
                    file_path=metadata["file_path"],
                    code=final_code,
                    report=final_forbidden,
                    novelty_score=float(metadata.get("novelty_score", 0.0)),
                )

            return new_filename, final_code, metadata

        except Exception as e:
            logger.error(f"处理文件 {relative_path} 时发生异常: {e}")
            # 兜底：尽量保留可用文件，避免单文件异常导致全项目 failed_files 激增。
            try:
                fallback_name = self._rename_file(relative_path, self.primary_entity)
            except Exception:
                fallback_name = relative_path

            fallback_code = content if isinstance(content, str) else ""
            fallback_syntax_ok = self._validate_syntax(fallback_code, self.target_language)
            fallback_metadata: Dict[str, Any] = self._extract_metadata(fallback_code, fallback_name) or {}
            fallback_metadata["file_path"] = fallback_name.replace("\\", "/")
            fallback_metadata["source_path"] = relative_path.replace("\\", "/")
            fallback_metadata["process_mode"] = "fallback_error"
            fallback_metadata["line_count"] = len(fallback_code.splitlines())
            fallback_metadata["novelty_score"] = 0.0
            fallback_metadata["max_similarity"] = 1.0
            fallback_metadata["forbidden_risk"] = 1.0
            fallback_metadata["forbidden_window_density"] = 1.0
            fallback_metadata["forbidden_line_hits"] = 999
            fallback_metadata["novelty_risk_level"] = "fallback"
            fallback_metadata["business_consistency"] = 0.0
            fallback_metadata["spec_version"] = self.spec_builder.get_project_spec().get("version", "spec-v1")
            fallback_metadata["architecture_family"] = self.spec_builder.get_project_spec().get("architecture_family", "Layered")
            fallback_metadata["syntax_ok"] = bool(fallback_syntax_ok)
            fallback_metadata["syntax_recovered"] = False
            fallback_metadata["quality_passed"] = False
            fallback_metadata["quality_gate_enforced"] = False
            fallback_metadata["quality_scope"] = "fallback_error"
            fallback_metadata["fallback_reason"] = str(e)
            logger.warning(f"文件 {relative_path} 已回退到安全产物，避免任务整体中断")
            return fallback_name, fallback_code, fallback_metadata

    def _apply_step_with_guard(
        self,
        current_code: str,
        transform_func,
        step_name: str,
        relative_path: str
    ) -> str:
        """
        对单个混淆步骤执行“异常保护 + 语法闸门”：
        - 步骤报错：回滚到当前版本
        - Python 语法不通过：回滚该步骤，继续后续步骤
        """
        try:
            next_code = transform_func(current_code)
        except Exception as e:
            logger.debug(f"文件 {relative_path} 在步骤[{step_name}]异常，回滚该步: {e}")
            return current_code

        if self.target_language == "Python" and not self._validate_syntax(next_code, "Python"):
            logger.debug(f"文件 {relative_path} 在步骤[{step_name}]后语法失效，回滚该步")
            return current_code
        return next_code

    def _load_seed_files(self, language: str) -> Dict[str, str]:
        """加载指定语言的种子代码"""
        seed_subdir = self.LANGUAGE_MAP.get(language)
        if not seed_subdir:
            logger.warning(f"不支持的语言: {language}，尝试使用 Python")
            seed_subdir = self.LANGUAGE_MAP["Python"]
            self.target_language = "Python" # 修正目标语言

        seed_base = Path("seeds") / seed_subdir
        if not seed_base.exists():
            # 尝试在当前目录查找 (兼容测试环境)
            seed_base = Path(os.getcwd()) / "seeds" / seed_subdir

        if not seed_base.exists():
            logger.error(f"种子目录不存在: {seed_base}")
            return {}

        files = {}
        # 递归遍历所有代码文件
        for ext in ['.java', '.py', '.go', '.js', '.php']:
            for file_path in seed_base.rglob(f"*{ext}"):
                if file_path.is_file():
                    # 计算相对路径
                    rel_path = file_path.relative_to(seed_base)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            files[str(rel_path)] = f.read()
                    except Exception as e:
                        logger.warning(f"无法读取种子文件 {file_path}: {e}")

        logger.info(f"加载了 {len(files)} 个种子文件")
        return files

    def _transform_file(
        self,
        original_code: str,
        file_path: str,
        extra_requirements: str = "",
        file_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """调用 LLM 转换单个文件"""

        # 策略分级：判断使用哪种 Prompt
        # 核心业务逻辑 -> Heavy Prompt (逻辑幻觉、过度设计)
        # 基础数据结构 -> Light Prompt (仅改名、保持简洁)
        is_core_logic = any(k in file_path.lower() for k in ['controller', 'service', 'impl', 'handler', 'router', 'view'])
        if file_profile:
            is_core_logic = is_core_logic or bool(file_profile.get("is_core"))

        if is_core_logic:
            template = self.HEAVY_TRANSFORM_PROMPT
            logger.info(f"Using HEAVY prompt for: {file_path}")
        else:
            template = self.LIGHT_TRANSFORM_PROMPT
            logger.info(f"Using LIGHT prompt for: {file_path}")

        # 构造 Prompt
        prompt = template.format(
            source_language=self.target_language,
            project_name=self.project_name,
            original_code=original_code,
            primary_entity=self.primary_entity,
            project_package=self.project_package,
            # Light Prompt 不需要 comment_style，但 format 多传参数不会报错
            comment_style=self.differentiator.comment_style[self.target_language.lower() if self.target_language in ['Python', 'Java'] else 'python']['header']
        )
        if extra_requirements:
            prompt = f"{prompt}\n\n## 追加约束\n{extra_requirements}"

        # 调用 API (复用 DeepSeekClient 的重试逻辑)
        # 注意：这里我们需要纯文本，不是 JSON。DeepSeekClient 主要针对 JSON 优化。
        # 我们直接使用 client.client.chat.completions.create

        try:
            messages = [
                {"role": "system", "content": "你是一个代码重构专家。请直接输出代码，不要包含 ``` 标记。"},
                {"role": "user", "content": prompt}
            ]
            failure_recorded = False
            try:
                content = self.client.generate_text(messages, max_retries=self.llm_text_retries)
            except Exception as first_error:
                self._record_llm_call_failure(first_error)
                failure_recorded = True
                # 代码阶段优先保证“有改写结果可落地”：
                # 若 responses 链路在中转站抖动，立即回退 chat 再试一次，避免整文件直接退回原始代码。
                try:
                    is_http = bool(self.client._should_use_http_compatible())
                    api_style = str(self.client._resolve_api_style())
                except Exception:
                    is_http = False
                    api_style = "chat"
                if is_http and api_style == "responses":
                    logger.warning(f"responses 文本调用失败，回退 chat 单次重试: {first_error}")
                    content = self.client.generate_text(
                        messages,
                        max_retries=1,
                        api_style_override="chat",
                    )
                else:
                    raise

            # 清洗 markdown 标记
            content = re.sub(r'^```\w*\s*', '', content, flags=re.MULTILINE)
            content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
            return content.strip()

        except Exception as e:
            if not locals().get("failure_recorded", False):
                self._record_llm_call_failure(e)
            logger.error(f"LLM 转换失败: {e}")
            # 降级：如果 LLM 失败，返回原始代码（至少保证有文件）
            return original_code

    def _simple_entity_replace(self, code: str, file_path: str = "") -> str:
        """
        基础文件深度混淆（不调用LLM，但足以应对查重）
        策略：实体替换 + 变量重命名 + 注释重写 + 结构微调
        """
        result = code

        # 1. 实体名替换
        entity_mappings = [
            ("User", self.primary_entity),
            ("user", self.primary_entity.lower()),
            ("USER", self.primary_entity.upper()),
        ]

        for old, new in entity_mappings:
            result = re.sub(r'\b' + old + r'\b', new, result)

        # 2. 通用变量名替换（查重核心）
        var_replacements = {
            "id": f"{self.primary_entity.lower()}_id",
            "name": f"{self.primary_entity.lower()}_name",
            "data": "record_data",
            "result": "query_result",
            "items": "data_items",
            "response": "api_response",
            "request": "api_request",
            "config": "sys_config",
            "options": "param_options",
            "status": "current_status",
            "message": "info_message",
            "error": "error_info",
            "value": "field_value",
            "key": "field_key",
            "index": "item_index",
            "count": "total_count",
            "list": "data_list",
            "info": "detail_info",
        }

        for old_var, new_var in var_replacements.items():
            # 随机决定是否替换（70%概率）
            if random.random() < 0.7:
                result = re.sub(r'\b' + old_var + r'\b', new_var, result)

        # 3. 添加项目信息注释
        if self.target_language == "Python":
            header = f'"""\n{self.project_name}\n模块: 基础数据结构\n"""\n'
        elif self.target_language == "Java":
            header = f'/**\n * {self.project_name}\n * 模块: 基础数据结构\n */\n'
        else:
            header = ""

        if header and not result.startswith('"""') and not result.startswith('/**'):
            result = header + result

        # 4. 随机插入业务注释（语义驱动，降低跨项目重复句式）
        lines = result.split('\n')
        new_lines = []
        semantic_comments = self.spec_builder.semantic_comments(file_path or "generic", self.target_language, count=7)
        comment_prefix = "#" if self.target_language == "Python" else "//"
        business_comments = [f"{comment_prefix} {txt}" for txt in semantic_comments]

        for i, line in enumerate(lines):
            new_lines.append(line)
            # 每20行左右随机插入一条注释
            if i > 0 and i % 20 == 0 and random.random() < 0.5:
                indent = len(line) - len(line.lstrip())
                comment = random.choice(business_comments)
                new_lines.append(" " * indent + comment)

        return '\n'.join(new_lines)

    def _generate_project_package(self) -> str:
        """生成项目唯一包名"""
        try:
            hash_str = hashlib.md5(self.project_name.encode('utf-8')).hexdigest()[:6]
        except:
            hash_str = "gen"

        # 净化实体名，只保留字母
        clean_entity = "".join(filter(str.isalpha, self.primary_entity.lower()))
        if not clean_entity:
            clean_entity = "app"

        # 生成格式: com.{hash}.{业务域}
        return f"com.{hash_str}.{clean_entity}"

    def _obfuscate_variable_names(self, code: str, language: str) -> str:
        """
        对变量名进行混淆：后缀增强 + 命名膨胀 + 人类噪音 (Phase 2)
        """
        if language not in ["Java", "Python"]:
            return code

        # 1. 扩展的基础变量库
        common_vars = [
            "result", "data", "list", "map", "temp", "tmp", "item", "obj",
            "info", "config", "params", "args", "ctx", "context", "service",
            "repo", "repository", "controller", "handler", "util", "helper",
            "user", "account", "record", "log", "file", "image", "msg", "message",
            "req", "request", "res", "response", "dto", "vo", "entity",
            "status", "state", "type", "kind", "mode", "flag", "count", "total",
            "check", "valid", "value", "key", "token", "auth", "session"
        ]

        # 2. 命名膨胀映射 (Inflation)
        inflation_map = {
            "data": ["processedDataBuffer", "businessDataRecord", "transferredDataPacket", "rawByteData"],
            "list": ["collectionRegistry", "dataElementList", "recordSetBuffer", "iterableItems"],
            "info": ["detailedInformationStruct", "metaDataInfo", "contextualInfo", "systemStateInfo"],
            "config": ["systemConfigurationMap", "runtimeSettingsConfig", "preferenceSet", "globalEnvConfig"],
            "user": ["primaryUserEntity", "authenticatedUserSubject", "clientUserRecord", "sessionHolder"],
            "id": ["uniqueIdentifierKey", "primaryResourceID", "referenceIndexID", "databasePrimaryKey"],
            "result": ["operationResultStatus", "computationFinalResult", "executionOutcome", "returnPayload"]
        }

        # 3. 拼音库 (Pinyin - Phase 2) - 模拟国内开发者习惯
        pinyin_map = {
            "user": ["yonghu", "yh", "user_info", "yonghu_xinxi"],
            "data": ["shuju", "data_list", "shuju_list"],
            "list": ["lb", "list_data", "liebiao"],
            "count": ["shuliang", "num", "cnt"],
            "msg": ["xiaoxi", "xinxi"],
            "temp": ["lingshi", "tmp_val"]
        }

        # 4. 常见拼写错误 (Typos - Phase 2)
        typo_map = {
            "receiver": "reciever",
            "length": "lenth",
            "height": "heigth",
            "width": "weight",
            "index": "indx",
            "parameter": "parmeter",
            "function": "funtion",
            "config": "confg"
        }

        obfuscated_code = code

        # 生成一个较长的随机后缀 (8位)
        suffix = "".join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))

        for var in common_vars:
            # 随机跳过 (30% 概率不混淆 -> 70% 混淆)
            if random.random() > 0.7:
                continue

            # 决定策略
            rand_val = random.random()

            # 策略A: 拼音混杂 (5%)
            if var in pinyin_map and rand_val < 0.05:
                new_var = random.choice(pinyin_map[var])

            # 策略B: 拼写错误 (2%) - 仅针对长单词
            elif var in typo_map and rand_val < 0.07:
                 new_var = typo_map[var]

            # 策略C: 无意义命名 (5%)
            elif rand_val < 0.12:
                new_var = random.choice(["a", "b", "c", "x", "y", "z", "temp1", "obj2", "var3"])

            # 策略D: 命名膨胀 (30%)
            elif var in inflation_map and rand_val < 0.42:
                new_var = random.choice(inflation_map[var])

            # 策略E: 加长后缀 (剩余)
            else:
                # 随机插入一个中间词
                middle = random.choice(["_internal_", "_cached_", "_local_", "_temp_", "_sys_", "_"])
                new_var = f"{var}{middle}{suffix}"

            # 格式统一化处理
            if language == "Java" or (language == "Python" and "List" in code):
                # 简单转驼峰
                if "_" in new_var:
                    parts = new_var.split('_')
                    parts = [p for p in parts if p]
                    if parts:
                         new_var = parts[0] + ''.join(x.title() for x in parts[1:])

            # 执行替换 (正则 Word Boundary)
            # 排除前面有 . 的情况 (属性访问)
            pattern = r'(?<!\.)\b' + re.escape(var) + r'\b'
            obfuscated_code = re.sub(pattern, new_var, obfuscated_code)

        return obfuscated_code

    def _inject_debug_scraps(self, code: str, language: str) -> str:
        """
        注入调试痕迹与废弃代码 (Code Realism - Phase 2)
        模拟开发过程中的残留物：注释掉的Print、旧逻辑、TODO炸弹
        """
        if random.random() > 0.4: # 60% 概率不做太明显的修改
            return code

        lines = code.split('\n')
        new_lines = []

        # 调试语句模板
        debug_stmts = {
            "python": [
                "# print(f'DEBUG: data={data}')",
                "# import pdb; pdb.set_trace()",
                "# logger.info('step 1 passed')",
                "# print('-----------------')",
                "# print(type(res))",
                "# FIXME: why is this None?"
            ],
            "java": [
                "// System.out.println(\"debug point 1\");",
                "// logger.info(\"value: \" + value);",
                "// e.printStackTrace();",
                "// TODO: remove this later",
                "// System.out.println(JSON.toJSONString(obj));"
            ]
        }

        # 废弃逻辑模板 (Old Logic)
        old_logic_templates = {
            "python": [
                '''
        # OLD LOGIC:
        # if not valid:
        #     return False
        # else:
        #     process(data)
                ''',
                '''
        # temp fix for bug #1024
        # res = [x for x in res if x.id > 0]
                '''
            ],
            "java": [
                '''
        /*
        if (user.getStatus() == 0) {
            return null;
        }
        */
                ''',
                '''
        // Deprecated: use new service instead
        // oldService.process(req);
                '''
            ]
        }

        lang_key = "python" if language == "Python" else "java"
        stmts = debug_stmts.get(lang_key, [])
        old_logics = old_logic_templates.get(lang_key, [])

        for line in lines:
            new_lines.append(line)

            # 随机在非空行后注入调试残留
            if line.strip() and random.random() < 0.05:
                indent = len(line) - len(line.lstrip())
                scrap = random.choice(stmts)
                new_lines.append(" " * indent + scrap)

            # 随机在方法体中注入"旧逻辑"块 (仅一次)
            if line.strip().endswith(":") or line.strip().endswith("{"):
                if random.random() < 0.02:
                     indent = len(line) - len(line.lstrip()) + (4 if language == "Python" else 4)
                     scrap = random.choice(old_logics)
                     # 调整缩进
                     scrap_lines = [(" " * indent + l.strip()) for l in scrap.split('\n') if l.strip()]
                     new_lines.extend(scrap_lines)

        return "\n".join(new_lines)

    def _apply_physical_obfuscation(self, code: str, language: str) -> str:
        """
        应用强力物理层混淆 (Code Inflation + Obfuscation)
        目标：每个文件增加 100-200 行以上的"业务噪音"
        Phase 2 增强: 物理格式微扰 (Format Jitter)
        """
        lines = code.split('\n')
        new_lines = []

        # 1. 强力文件头 (20-30行)
        # 必须保持单行，避免在注释框模板里出现未注释的换行内容
        file_desc = (
            f"Core Business Logic for {self.project_name} | "
            f"Module: {self.primary_entity} Management Subsystem | "
            "Security Level: High (Class A) | "
            "Audit Status: Pending Review"
        )
        comment_lang = "java" if language == "Java" else "python"
        header = self.differentiator.generate_file_header("generated_file", file_desc,
                 comment_lang)
        new_lines.append(header)
        new_lines.append("")

        # 2. 注入大量 Import (看起来很真实)
        if language == "Java":
            new_lines.extend([
                "import java.util.*;",
                "import java.io.*;",
                "import java.math.*;",
                "import java.time.*;",
                "import java.util.concurrent.*;",
                "import java.util.stream.*;",
                ""
            ])
        elif language == "Python":
            new_lines.extend([
                "import sys", "import os", "import time", "import json",
                "import logging", "import hashlib", "import random",
                "from datetime import datetime, timedelta",
                "from typing import List, Dict, Any, Optional, Union",
                ""
            ])

        # 3. 遍历并注入 (代码膨胀核心)
        in_class = False
        method_count = 0

        for line in lines:
            stripped = line.strip()

            # Format Jitter 1: 随机空行
            if random.random() < 0.02:
                new_lines.append("") # 额外的空行

            # Format Jitter 2: 行尾空格 (不可见字符)
            if random.random() < 0.1:
                line += " " * random.randint(1, 4)

            # 检测类定义，准备注入内部类
            if ("class " in line) and (not in_class):
                in_class = True
                new_lines.append(line)
                # 在类开始处注入 1-2 个复杂的内部辅助类
                new_lines.append(self._generate_inner_class_noise(language))
                continue

            # 检测方法定义，注入日志和校验
            is_method = False
            if language == "Java" and ("public " in line or "private " in line) and "{" in line:
                is_method = True
            elif language == "Python" and re.match(r'^\s*def\s+\w+\s*\(', line):
                is_method = True
            elif language == "PHP" and re.match(r'^\s*(public|private|protected)?\s*function\s+\w+\s*\(', line):
                is_method = True

            # Format Jitter 3: 缩进瑕疵 (极低概率 0.5%)
            # 仅在 Java 注释行使用，避免破坏 Python/PHP 缩进结构
            if language == "Java" and (stripped.startswith("#") or stripped.startswith("//")):
                if random.random() < 0.05:
                     line = " " + line # 错位

            new_lines.append(line)

            if is_method:
                method_count += 1
                method_indent = len(line) - len(line.lstrip())
                body_indent = method_indent + (8 if language == "Java" else 4)

                # 注入方法入口日志 (极长)
                verbose_log = self._generate_verbose_log(language, "ENTRY")
                if verbose_log:
                    for sub in verbose_log.splitlines():
                        if sub.strip():
                            new_lines.append(" " * body_indent + sub.strip())

                # 注入参数校验噪音
                param_noise = self._generate_param_noise(language)
                if param_noise:
                    for sub in param_noise.splitlines():
                        if sub.strip():
                            new_lines.append(" " * body_indent + sub.strip())

        # 4. 文件末尾注入大量死代码 (5-8个方法，约100行)
        dead_code_count = random.randint(5, 8)
        for _ in range(dead_code_count):
            dead_code = self._generate_dead_code(language)
            if not dead_code.strip():
                continue

            # Python/PHP 在模块级不能保留类内缩进，否则会触发 unexpected indent
            if language in {"Python", "PHP"} and not in_class:
                dead_code = textwrap.dedent(dead_code).strip("\n")
            else:
                dead_code = dead_code.strip("\n")

            new_lines.append("")
            new_lines.append(dead_code)

        return "\n".join(new_lines)

    def _generate_inner_class_noise(self, language: str) -> str:
        """生成内部类噪音 (Inner Class Noise)"""
        name = "Internal" + "".join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=4)) + "Helper"

        if language == "Java":
            return f"""
    /**
     * 内部辅助数据结构 (Auto-Generated)
     * 用于处理复杂的中间状态转换
     */
    private static class {name} {{
        private String traceId;
        private long timestamp;
        private Map<String, Object> contextBuffer;

        public {name}() {{
            this.traceId = UUID.randomUUID().toString();
            this.timestamp = System.currentTimeMillis();
            this.contextBuffer = new ConcurrentHashMap<>();
        }}

        public void pushContext(String key, Object val) {{
            if (key != null && val != null) {{
                this.contextBuffer.put(key, val);
            }}
        }}

        public boolean validateState() {{
            return this.timestamp > 0 && !this.traceId.isEmpty();
        }}
    }}
"""
        elif language == "Python":
            return f"""
    class _{name}:
        \"\"\"
        内部辅助类，用于封装临时业务状态
        \"\"\"
        def __init__(self):
            self._trace_id = "{random.randint(1000,9999)}"
            self._buffer = {{}}
            self._init_ts = time.time()

        def _update_buffer(self, k, v):
            if k and v:
                self._buffer[k] = v

        def _check_ttl(self):
            return (time.time() - self._init_ts) < 3600
"""
        elif language == "PHP":
            buf_name = name.lower()
            return f"""
    private function _{buf_name}InitBuffer() {{
        $this->{buf_name}TraceId = uniqid('', true);
        $this->{buf_name}Buffer = [];
    }}

    private function _{buf_name}PushBuffer($key, $value) {{
        if (!empty($key)) {{
            $this->{buf_name}Buffer[$key] = $value;
        }}
    }}
"""
        return ""

    def _generate_verbose_log(self, language: str, phase: str) -> str:
        """生成冗长的日志代码"""
        msg = f"Executing business logic phase [{phase}] - Timestamp: "

        if language == "Java":
            return f'// System.out.println("{msg}" + System.currentTimeMillis());'
        elif language == "Python":
            return f'# logger.debug("{msg}" + str(time.time()))'
        elif language == "PHP":
            return f'// error_log("{msg}" . microtime(true));'
        return ""

    def _generate_param_noise(self, language: str) -> str:
        """生成参数校验噪音"""
        if language == "Java":
            return """if (Thread.currentThread().isInterrupted()) {
    throw new RuntimeException("Thread interrupted during business processing");
}"""
        elif language == "Python":
            return "__integrity_flag = True"
        elif language == "PHP":
            return """$__integrity_flag = true;
if (!$__integrity_flag) {
    throw new \\RuntimeException("Runtime integrity check failed");
}"""
        return ""

    def _generate_dead_code(self, language: str) -> str:
        """生成无用的私有辅助方法 (Phase 2: 模板扩充)"""
        rand_num = random.randint(1000000, 9999999)
        rand_var = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=6))

        # 扩充到15个模板 (这里展示部分，实际运行会随机组合)
        if language == "Python":
            templates = [
                # 1. Validator
                f'''
    def _{rand_var}_validator(self, data):
        """内部保留校验逻辑"""
        _ts = {rand_num}
        if not data:
            return False
        return True
''',
                # 2. Check
                f'''
    def _check_{rand_var}(self, value):
        """数据完整性校验"""
        _flag = {rand_num} % 7
        return value is not None and _flag >= 0
''',
                # 3. Cache Init
                f'''
    def _init_{rand_var}_cache(self):
        """初始化缓存配置"""
        self._{rand_var}_buffer = []
        self._max_size = {rand_num}
''',
                # 4. Logger wrapper
                f'''
    def _log_{rand_var}_event(self, event_id):
        """记录内部事件"""
        # 调试模式下记录
        pass
''',
                # 5. Permission check
                f'''
    def _verify_{rand_var}_permission(self, token):
        """权限预校验"""
        if not token:
            return False
        return len(token) > {random.randint(5, 15)}
''',
                # 6. Data cleaner
                f'''
    def _clean_{rand_var}_data(self, raw):
        """清理临时数据"""
        if isinstance(raw, list):
            return [x for x in raw if x]
        return raw
''',
                # 7. Config loader
                f'''
    def _load_{rand_var}_config(self):
        """加载默认配置"""
        return {{ "timeout": {random.randint(1000, 5000)}, "retry": 3 }}
''',
                # 8. Hash computation
                f'''
    def _compute_{rand_var}_hash(self, key):
        """计算哈希指纹"""
        return hash(str(key) + "{rand_var}")
''',
                # 9. Time checker
                f'''
    def _check_{rand_var}_timestamp(self, ts):
        """时间戳有效性检查"""
        import time
        return ts < time.time()
''',
                # 10. Memory monitor
                f'''
    def _monitor_{rand_var}_memory(self):
        """内存使用监控"""
        # 仅在Debug模式启用
        pass
'''
            ]
            return random.choice(templates)

        elif language == "Java":
            templates = [
                # 1. Validator
                f'''
    /**
     * 内部数据校验方法
     */
    private boolean validate{rand_var.capitalize()}State(Object data) {{
        long timestamp = {rand_num}L;
        return data != null && timestamp > 0;
    }}
''',
                # 2. Cache
                f'''
    /**
     * 缓存预热辅助方法
     */
    private void init{rand_var.capitalize()}Cache() {{
        int bufferSize = {rand_num};
        // 预留扩展
    }}
''',
                # 3. Hash
                f'''
    /**
     * 哈希计算辅助
     */
    private int compute{rand_var.capitalize()}Hash(String input) {{
        if (input == null) return 0;
        return input.hashCode() ^ {rand_num};
    }}
''',
                # 4. Logger
                f'''
    /**
     * 系统日志记录器
     */
    private void log{rand_var.capitalize()}Event(String msg) {{
        // 异步写入日志
    }}
''',
                # 5. Config
                f'''
    /**
     * 加载默认配置项
     */
    private Map<String, Object> load{rand_var.capitalize()}Config() {{
        return new HashMap<>();
    }}
''',
                # 6. Check
                f'''
    /**
     * 状态位检查
     */
    private boolean check{rand_var.capitalize()}Status(int code) {{
        return (code & {random.randint(1, 255)}) != 0;
    }}
'''
            ]
            return random.choice(templates)
        elif language == "PHP":
            templates = [
                f"""
    function _{rand_var}_validator($data) {{
        if ($data === null) {{
            return false;
        }}
        return true;
    }}
""",
                f"""
    function _{rand_var}_checksum($input) {{
        $raw = (string)$input . "{rand_var}";
        return sha1($raw);
    }}
""",
                f"""
    function _{rand_var}_normalize($items) {{
        if (!is_array($items)) {{
            return [];
        }}
        return array_values(array_filter($items, fn($x) => !empty($x)));
    }}
""",
                f"""
    function _{rand_var}_loadConfig() {{
        return [
            "timeout" => {random.randint(1000, 5000)},
            "retry" => 3,
            "trace" => "{rand_var}"
        ];
    }}
""",
                f"""
    function _{rand_var}_auditTrail($eventId) {{
        // 审计记录占位逻辑
        return "AUDIT-" . $eventId . "-{rand_num}";
    }}
""",
            ]
            return random.choice(templates)
        return ""

    def _obfuscate_constants(self, code: str, language: str) -> str:
        """
        常量混淆 (Phase 4)
        将数字常量替换为计算表达式
        """
        if random.random() > 0.8: # 20% 概率不开启
            return code

        def replace_number(match):
            val = match.group(0)
            try:
                num = int(val)
                # 只混淆较小的整数，避免破坏 timestamps 或 port numbers
                if 0 <= num <= 1000:
                    strategy = random.choice([1, 2, 3])
                    if strategy == 1: # 加法
                        a = random.randint(1, num) if num > 0 else 0
                        b = num - a
                        return f"({a} + {b})"
                    elif strategy == 2: # 乘法 (如果是偶数)
                        if num % 2 == 0 and num > 0:
                            return f"({num // 2} * 2)"
                        else:
                            return f"({num - 1} + 1)"
                    elif strategy == 3: # 浮点转整
                         return f"int({float(num)})" if language == "Python" else f"(int){float(num)}"
            except:
                pass
            return val

        # 匹配独立的数字
        # Python/Java 通用
        code = re.sub(r'\b\d+\b', replace_number, code)
        return code

    def _transform_expressions(self, code: str, language: str) -> str:
        """
        表达式等价替换 (Phase 5)
        """
        if random.random() > 0.8:
            return code

        lines = code.split('\n')
        new_lines = []

        for line in lines:
            # 简单替换逻辑
            if " == " in line and random.random() < 0.3:
                # a == b -> not (a != b)
                # 需要小心括号，这里仅做简单文本替换，不涉及 AST
                # 仅对 Python 示例
                if language == "Python":
                    # 避免替换 if a == b: 这种结构太复杂，只替换简单的
                    pass

            # 算术替换
            # + 1 -> - (-1)
            if " + 1" in line and random.random() < 0.3:
                 line = line.replace(" + 1", " - (-1)")

            # == None -> is None (Python)
            if language == "Python" and " == None" in line:
                line = line.replace(" == None", " is None")

            # != None -> is not None (Python)
            if language == "Python" and " != None" in line:
                line = line.replace(" != None", " is not None")

            new_lines.append(line)

        return "\n".join(new_lines)

    def _inject_todo_markers(self, code: str, language: str, file_path: str = "") -> str:
        """
        注入 TODO/FIXME 标记，增强代码真实感
        真实项目通常有 10% 左右的方法包含技术债标记
        """
        # TODO 标记库
        TODO_MARKERS = {
            "python": [
                "# TODO: 后续版本优化此处性能",
                "# FIXME: 边界条件需要完善",
                "# XXX: 临时方案，待重构",
                "# TODO: 考虑添加缓存机制",
                "# FIXME: 异常处理需要细化",
                "# TODO: 添加参数校验逻辑",
                "# NOTE: 此处逻辑较复杂，需要review",
                "# HACK: 临时绕过，等待上游修复",
                "# TODO: 抽取为公共方法",
                "# FIXME: 并发场景下可能有问题",
                "# TODO: 添加单元测试覆盖",
                "# XXX: 魔法数字，后续提取为常量",
            ],
            "java": [
                "// TODO: 性能优化 - 考虑使用缓存",
                "// FIXME: 异常处理需要细化",
                "// XXX: 临时方案，后续重构",
                "// TODO: 添加参数非空校验",
                "// FIXME: 边界条件待完善",
                "// TODO: 考虑使用 Builder 模式",
                "// NOTE: 此处业务逻辑较复杂",
                "// HACK: 临时绕过框架限制",
                "// TODO: 抽取为工具类",
                "// FIXME: 线程安全问题待处理",
                "// TODO: 补充 JavaDoc 文档",
                "// XXX: 硬编码值，待提取配置",
            ],
            "php": [
                "// TODO: 后续抽取为独立服务",
                "// FIXME: 事务边界还需要细化",
                "// NOTE: 兼容历史接口，暂不删除",
                "// TODO: 增加参数白名单校验",
                "// XXX: 临时兼容逻辑，后续重构",
            ],
        }

        if language == "Python":
            lang_key = "python"
        elif language == "Java":
            lang_key = "java"
        elif language == "PHP":
            lang_key = "php"
        else:
            lang_key = "python"
        markers = TODO_MARKERS.get(lang_key, TODO_MARKERS["python"])
        semantic_comments = self.spec_builder.semantic_comments(file_path or "generic", language, count=4)
        if semantic_comments:
            if lang_key == "python":
                markers.extend([f"# TODO: {x}" for x in semantic_comments])
            else:
                markers.extend([f"// TODO: {x}" for x in semantic_comments])

        lines = code.split('\n')
        new_lines = []

        # 检测方法定义的模式
        method_pattern_py = r'^\s*def\s+\w+\s*\('
        method_pattern_java = r'^\s*(public|private|protected)\s+.*\s+\w+\s*\('
        method_pattern_php = r'^\s*(public|private|protected)?\s*function\s+\w+\s*\('

        for i, line in enumerate(lines):
            new_lines.append(line)

            # 检测是否是方法定义
            is_method = False
            if language == "Python" and re.match(method_pattern_py, line):
                is_method = True
            elif language == "Java" and re.match(method_pattern_java, line):
                is_method = True
            elif language == "PHP" and re.match(method_pattern_php, line):
                is_method = True

            # 10% 概率在方法定义后注入 TODO 标记
            if is_method and random.random() < 0.10:
                # 获取缩进
                indent = len(line) - len(line.lstrip())
                if language == "Python":
                    indent += 4
                elif language == "PHP":
                    indent += 4
                else:
                    indent += 8

                marker = random.choice(markers)
                new_lines.append(" " * indent + marker)

        return "\n".join(new_lines)

    def _validate_syntax(self, code: str, language: str) -> bool:
        """
        语法完整性检查（轻量版，多语言）。

        设计取舍：
        - Python 使用 ast.parse 做强校验，确保不会产出明显坏代码。
        - 其他语言用启发式检查，不依赖本地编译器，避免额外环境依赖导致批量任务失败。
        """
        if not code.strip():
            return False

        if language == "Python":
            try:
                ast.parse(code)
                return True
            except SyntaxError:
                return False

        def _balanced_symbols(text: str, open_s: str, close_s: str) -> bool:
            count = 0
            for ch in text:
                if ch == open_s:
                    count += 1
                elif ch == close_s:
                    count -= 1
                    if count < 0:
                        return False
            return count == 0

        # 通用平衡检查
        if not _balanced_symbols(code, "(", ")"):
            return False
        if not _balanced_symbols(code, "{", "}"):
            return False
        if not _balanced_symbols(code, "[", "]"):
            return False

        # 语言级启发式检查
        if language == "Java":
            has_top_type = any(k in code for k in ("class ", "interface ", "enum ", "@interface "))
            has_pkg_or_import = ("package " in code) or ("import " in code)
            has_statement = ";" in code
            # 允许工具/常量文件没有 class，但应至少有包/导入或语句
            return (has_top_type or has_statement) and (has_pkg_or_import or has_top_type)
        if language == "Go":
            has_package = "package " in code
            has_go_item = any(k in code for k in ("func ", "type ", "var ", "const ", "import "))
            return has_package and has_go_item
        if language == "PHP":
            return ("<?php" in code) or ("function " in code) or ("class " in code)
        if language == "Node.js":
            return (
                ("function " in code)
                or ("=>" in code)
                or ("class " in code)
                or ("module.exports" in code)
                or ("exports." in code)
                or ("require(" in code)
            )

        return True

    def _determine_primary_entity(self) -> str:
        """
        从 blueprint 中提取实体，或根据项目名推断
        """
        # 1. 尝试从 plan.code_blueprint 获取
        blueprint = self.plan.get("code_blueprint", {})
        entities = blueprint.get("entities", [])
        if entities:
            # 过滤掉非核心实体
            candidates = [e for e in entities if "Log" not in e and "Record" not in e]
            if candidates:
                return candidates[0]
            return entities[0]

        # 2. 智能推断 (Fallback)
        # 简单映射：项目名 -> 实体名
        name = self.project_name
        if "林" in name: return "ForestGuard"
        if "医" in name: return "Patient"
        if "教" in name: return "Student"
        if "车" in name: return "Vehicle"
        if "书" in name: return "Book"

        return "BusinessItem" # 最终保底

    def _rename_file(self, original_path: str, entity_name: str) -> str:
        """
        重命名文件并应用目录映射
        Example: controller/UserController.java -> interfaces/web/ForestGuardController.java
        """
        path_str = str(original_path).replace("\\", "/") # 统一使用 /

        # 1. 实体名替换
        if "user" in path_str.lower():
             if "User" in path_str:
                path_str = path_str.replace("User", entity_name)
             elif "user" in path_str:
                path_str = path_str.replace("user", entity_name.lower())

        # 2. 目录映射 (Phase 2)
        # 解析路径 parts
        parts = path_str.split('/')
        new_parts = []

        # 检查每一层目录是否在映射表中
        for part in parts:
            # 如果是文件名，保持原样(但已做过实体替换)
            if part == parts[-1]:
                new_parts.append(part)
                continue

            # 如果是目录，查表
            # 注意: dir_mapping key 是 'controller', 'service' 等
            mapped = False
            for key, val in self.dir_mapping.items():
                if part == key:
                    new_parts.append(val)
                    mapped = True
                    break

            if not mapped:
                new_parts.append(part)

        return "/".join(new_parts)

    def _fix_package_and_imports(self, code: str, new_rel_path: str) -> str:
        """
        根据新的文件路径，修正 package 声明和 import 语句
        """
        # 仅针对 Java/Go/PHP 等有包管理机制的语言
        if self.target_language not in ["Java", "Go", "PHP"]:
            return code

        # 1. 计算当前文件的包名
        # new_rel_path e.g. "interfaces/web/ForestGuardController.java"
        # project_package e.g. "com.gen.forest"

        parent_dir = str(Path(new_rel_path).parent).replace("\\", "/")
        if parent_dir == ".":
            sub_package = ""
        else:
            # 将路径分隔符转换为点号
            sub_package = parent_dir.replace("/", ".")

        full_package = f"{self.project_package}.{sub_package}" if sub_package else self.project_package

        # 移除连续的点 (e.g. com.gen..web)
        full_package = re.sub(r'\.{2,}', '.', full_package)

        lines = code.split('\n')
        new_lines = []

        for line in lines:
            stripped = line.strip()

            # A. 修正 package 声明
            if stripped.startswith("package "):
                if self.target_language == "Java":
                    new_lines.append(f"package {full_package};")
                elif self.target_language == "Go":
                    # Go 的 package 通常是目录名最后一段
                    pkg_name = parent_dir.split("/")[-1]
                    if not pkg_name or pkg_name == ".": pkg_name = "main"
                    new_lines.append(f"package {pkg_name}")
                elif self.target_language == "PHP":
                    namespace_str = full_package.replace('.', '\\')
                    new_lines.append("namespace {};".format(namespace_str))
                else:
                    new_lines.append(line)
                continue

            # B. 修正 import 语句
            # 需要把 import com.gen.forest.controller.xxx
            # 改为 import com.gen.forest.interfaces.web.xxx
            if stripped.startswith("import "):
                # 遍历映射表，替换包路径中间的部分
                modified_line = line
                for key, val in self.dir_mapping.items():
                    # key="controller", val="interfaces/web"
                    # 转换 val 为包格式: interfaces.web
                    val_pkg = val.replace("/", ".")

                    # 替换模式: .controller. -> .interfaces.web.
                    # 或者 .controller; -> .interfaces.web;

                    # 简单字符串替换 (需小心误伤)
                    # 假设原来的包结构是 flat 的 (e.g. .controller.)
                    if f".{key}." in modified_line:
                        modified_line = modified_line.replace(f".{key}.", f".{val_pkg}.")
                    elif f".{key};" in modified_line: # import ... .controller; (rare but possible)
                        modified_line = modified_line.replace(f".{key};", f".{val_pkg};")

                new_lines.append(modified_line)
                continue

            new_lines.append(line)

        return "\n".join(new_lines)

    def _extract_metadata(self, code: str, file_path: str) -> Dict[str, Any]:
        """
        从生成的代码中提取元数据 (Table名, API路径等)
        """
        metadata = {}

        # 仅针对 Controller 和 Entity 提取
        is_controller = "ontroller" in file_path
        is_entity = "ntity" in file_path or "model" in file_path.lower()

        if not (is_controller or is_entity):
            return {}

        try:
            # 提取类名
            class_match = re.search(r'class\s+(\w+)', code)
            if class_match:
                metadata['class_name'] = class_match.group(1)

            if is_entity:
                metadata['type'] = 'entity'
                # 提取表名 @TableName("xxx") or @Table(name="xxx")
                table_match = re.search(r'@Table(?:Name)?\s*\(\s*(?:name\s*=\s*)?["\']([^"\']+)["\']', code)
                if table_match:
                    metadata['table_name'] = table_match.group(1)

            if is_controller:
                metadata['type'] = 'controller'
                # 提取路由 @RequestMapping("/api/xxx")
                route_match = re.search(r'@RequestMapping\s*\(\s*["\']([^"\']+)["\']', code)
                if route_match:
                    metadata['base_route'] = route_match.group(1)

        except Exception as e:
            logger.warning(f"元数据提取失败: {e}")

        return metadata

    def _save_project_spec(self, output_dir: Path) -> None:
        """保存 Spec-first DSL，供后续文档/审计环节复用。"""
        import json

        spec = self.spec_builder.get_project_spec()
        spec["project_name"] = self.project_name
        spec["target_language"] = self.target_language
        spec["directory_style"] = self.dir_style_name
        spec_path = output_dir / "project_spec.json"
        try:
            with open(spec_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, indent=2, ensure_ascii=False)
            logger.info(f"Spec-first DSL 已保存: {spec_path}")
        except Exception as e:
            logger.warning(f"保存 project_spec.json 失败: {e}")

    def _build_quality_report(self, metadata_list: List[Dict[str, Any]], failed_files_count: int = 0) -> Dict[str, Any]:
        def _meta_forbidden_risky(item: Dict[str, Any]) -> bool:
            report = {
                "risk_score": float(item.get("forbidden_risk", 0.0)),
                "window_density": float(item.get("forbidden_window_density", 0.0)),
                "line_hits": int(item.get("forbidden_line_hits", 0)),
            }
            return ForbiddenPatternIndex.is_risky(report)

        if not metadata_list:
            effective_failed = int(failed_files_count)
            return {
                "passed": bool(effective_failed <= self.max_failed_files),
                "reason": "no_metadata",
                "avg_novelty": 0.0,
                "risky_file_count": 0,
                "syntax_fail_count": 0,
                "ai_line_ratio": 0.0,
                "failed_files_count": effective_failed,
                "raw_failed_files_count": int(failed_files_count),
                "fallback_file_count": 0,
                "max_failed_files": int(self.max_failed_files),
                "total_files": 0,
                "quality_scope": "all",
                "scope_files": 0,
                "llm_calls_total": int(getattr(self, "_llm_calls_total", 0)),
                "llm_failures_total": int(getattr(self, "_llm_failures_total", 0)),
                "llm_disabled_reason": str(getattr(self, "_llm_disabled_reason", "")),
            }
        # 项目级质量门默认聚焦 AI 重写文件（高价值改写区域），
        # 避免低价值本地混淆文件的高 forbidden 误伤整项目中断。
        scope_metadata = [x for x in metadata_list if x.get("process_mode") == "ai_rewrite"]
        quality_scope = "ai_rewrite"
        if not scope_metadata:
            scope_metadata = list(metadata_list)
            quality_scope = "all"

        novelty_scores = [float(x.get("novelty_score", 0.0)) for x in scope_metadata]
        overall_novelty_scores = [float(x.get("novelty_score", 0.0)) for x in metadata_list]
        total_lines = sum(max(0, int(x.get("line_count", 0))) for x in metadata_list)
        ai_lines = sum(
            max(0, int(x.get("line_count", 0)))
            for x in metadata_list
            if x.get("process_mode") == "ai_rewrite"
        )
        ai_line_ratio = (ai_lines / total_lines) if total_lines > 0 else 0.0
        risky_files = [
            x for x in scope_metadata
            if _meta_forbidden_risky(x) or float(x.get("novelty_score", 0.0)) < self.file_novelty_budget
        ]
        local_risky_files = [
            x for x in metadata_list
            if x.get("process_mode") != "ai_rewrite"
            and (_meta_forbidden_risky(x) or float(x.get("novelty_score", 0.0)) < self.file_novelty_budget)
        ]
        fallback_files = [x for x in metadata_list if x.get("process_mode") == "fallback_error"]
        syntax_fail_files = [x for x in metadata_list if not bool(x.get("syntax_ok", True))]
        avg_novelty = sum(novelty_scores) / max(1, len(novelty_scores))
        overall_avg_novelty = sum(overall_novelty_scores) / max(1, len(overall_novelty_scores))
        pass_avg = avg_novelty >= self.project_novelty_threshold
        pass_risky = len(risky_files) <= self.max_risky_files
        pass_syntax = len(syntax_fail_files) <= self.max_syntax_fail_files
        pass_ai_ratio = ai_line_ratio >= self.min_ai_line_ratio
        effective_failed_count = int(failed_files_count) + len(fallback_files)
        pass_failed = effective_failed_count <= self.max_failed_files

        return {
            "passed": bool(pass_avg and pass_risky and pass_syntax and pass_ai_ratio and pass_failed),
            "avg_novelty": round(avg_novelty, 4),
            "overall_avg_novelty": round(overall_avg_novelty, 4),
            "project_threshold": round(self.project_novelty_threshold, 4),
            "file_budget": round(self.file_novelty_budget, 4),
            "ai_line_ratio": round(ai_line_ratio, 4),
            "min_ai_line_ratio": round(self.min_ai_line_ratio, 4),
            "risky_file_count": len(risky_files),
            "max_risky_files": int(self.max_risky_files),
            "local_risky_file_count": len(local_risky_files),
            "syntax_fail_count": len(syntax_fail_files),
            "max_syntax_fail_files": int(self.max_syntax_fail_files),
            "failed_files_count": int(effective_failed_count),
            "raw_failed_files_count": int(failed_files_count),
            "fallback_file_count": len(fallback_files),
            "max_failed_files": int(self.max_failed_files),
            "total_files": len(metadata_list),
            "quality_scope": quality_scope,
            "scope_files": len(scope_metadata),
            "total_lines": int(total_lines),
            "ai_lines": int(ai_lines),
            "risky_files": [
                {
                    "file_path": x.get("file_path"),
                    "novelty_score": x.get("novelty_score"),
                    "forbidden_risk": x.get("forbidden_risk"),
                    "forbidden_window_density": x.get("forbidden_window_density"),
                    "forbidden_line_hits": x.get("forbidden_line_hits"),
                }
                for x in risky_files[:20]
            ],
            "local_risky_files": [
                {
                    "file_path": x.get("file_path"),
                    "novelty_score": x.get("novelty_score"),
                    "forbidden_risk": x.get("forbidden_risk"),
                    "forbidden_window_density": x.get("forbidden_window_density"),
                    "forbidden_line_hits": x.get("forbidden_line_hits"),
                }
                for x in local_risky_files[:20]
            ],
            "syntax_fail_files": [x.get("file_path") for x in syntax_fail_files[:20]],
            "llm_calls_total": int(getattr(self, "_llm_calls_total", 0)),
            "llm_failures_total": int(getattr(self, "_llm_failures_total", 0)),
            "llm_disabled_reason": str(getattr(self, "_llm_disabled_reason", "")),
            "max_total_llm_calls": int(getattr(self, "max_total_llm_calls", 0)),
            "max_total_llm_failures": int(getattr(self, "max_total_llm_failures", 0)),
        }

    def _save_quality_report(self, output_dir: Path, report: Dict[str, Any]) -> None:
        import json

        report_path = output_dir / "novelty_quality_report.json"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"新颖度质量报告已保存: {report_path}")
        except Exception as e:
            logger.warning(f"保存新颖度质量报告失败: {e}")

    def _save_metadata(self, output_dir: Path, metadata_list: List[Dict]):
        """
        保存项目元数据供后续流程使用。

        `project_metadata.json` 是代码阶段与文档/PDF 阶段的共享事实源：
        - 标注每个文件是 AI 改写还是仅混淆
        - 记录行数与新颖度结果，便于后续排序和审计
        """
        import json

        project_meta = {
            "project_name": self.project_name,
            "primary_entity": self.primary_entity,
            "architecture_family": self.spec_builder.get_project_spec().get("architecture_family", "Layered"),
            "project_spec_path": "project_spec.json",
            "llm_budget": {
                "max_total_llm_calls": int(getattr(self, "max_total_llm_calls", 0)),
                "max_total_llm_failures": int(getattr(self, "max_total_llm_failures", 0)),
                "llm_calls_total": int(getattr(self, "_llm_calls_total", 0)),
                "llm_failures_total": int(getattr(self, "_llm_failures_total", 0)),
                "llm_disabled_reason": str(getattr(self, "_llm_disabled_reason", "")),
            },
            "entities": [],
            "controllers": [],
            "file_process": []
        }

        for item in metadata_list:
            if item.get("file_path"):
                # file_process 用于源码 PDF 排序策略：AI 重写优先进入首尾区域。
                project_meta["file_process"].append({
                    "file_path": item.get("file_path"),
                    "source_path": item.get("source_path", ""),
                    "process_mode": item.get("process_mode", "obfuscation"),
                    "line_count": int(item.get("line_count", 0)),
                    "novelty_score": float(item.get("novelty_score", 0.0)),
                    "max_similarity": float(item.get("max_similarity", 1.0)),
                    "forbidden_risk": float(item.get("forbidden_risk", 0.0)),
                    "forbidden_window_density": float(item.get("forbidden_window_density", 0.0)),
                    "forbidden_line_hits": int(item.get("forbidden_line_hits", 0)),
                    "novelty_risk_level": item.get("novelty_risk_level", "unknown"),
                    "business_consistency": float(item.get("business_consistency", 0.0)),
                    "spec_version": item.get("spec_version", "spec-v1"),
                    "architecture_family": item.get("architecture_family", self.spec_builder.get_project_spec().get("architecture_family", "Layered")),
                    "syntax_ok": bool(item.get("syntax_ok", True)),
                    "syntax_recovered": bool(item.get("syntax_recovered", False)),
                    "quality_passed": bool(item.get("quality_passed", True)),
                    "quality_gate_enforced": bool(item.get("quality_gate_enforced", False)),
                    "quality_scope": item.get("quality_scope", "obfuscation"),
                })

            if item.get('type') == 'entity' and 'table_name' in item:
                project_meta['entities'].append({
                    "class": item.get('class_name'),
                    "table": item.get('table_name')
                })
            elif item.get('type') == 'controller' and 'base_route' in item:
                project_meta['controllers'].append({
                    "class": item.get('class_name'),
                    "route": item.get('base_route')
                })

        meta_path = output_dir / "project_metadata.json"
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(project_meta, f, indent=2, ensure_ascii=False)
            ai_count = sum(1 for x in project_meta["file_process"] if x.get("process_mode") == "ai_rewrite")
            obf_count = sum(1 for x in project_meta["file_process"] if x.get("process_mode") != "ai_rewrite")
            novelty_scores = [float(x.get("novelty_score", 0.0)) for x in project_meta["file_process"]]
            avg_novelty = sum(novelty_scores) / len(novelty_scores) if novelty_scores else 0.0
            syntax_fail_count = sum(1 for x in project_meta["file_process"] if not bool(x.get("syntax_ok", True)))
            total_lines = sum(int(x.get("line_count", 0)) for x in project_meta["file_process"])
            ai_lines = sum(int(x.get("line_count", 0)) for x in project_meta["file_process"] if x.get("process_mode") == "ai_rewrite")
            ai_ratio = (ai_lines / total_lines) if total_lines > 0 else 0.0
            logger.info(f"项目元数据已保存: {meta_path}")
            logger.info(f"文件处理统计: AI重写={ai_count}个, 仅混淆={obf_count}个")
            logger.info(f"新颖度统计: avg={avg_novelty:.3f}")
            logger.info(f"语法统计: fail={syntax_fail_count}, AI行占比={ai_ratio:.3f}")
            if project_meta["llm_budget"].get("llm_disabled_reason"):
                logger.warning(
                    "代码阶段已触发降级: reason=%s, llm_calls=%s, llm_failures=%s",
                    project_meta["llm_budget"].get("llm_disabled_reason"),
                    project_meta["llm_budget"].get("llm_calls_total"),
                    project_meta["llm_budget"].get("llm_failures_total"),
                )
        except Exception as e:
            logger.error(f"保存元数据失败: {e}")

