"""
项目规划器模块 (Refactored)
采用主从式 (Master-Detail) 分步生成策略，以解决长文本截断和超时问题。
1. Master Phase: 生成项目全局大纲 (Project Name, Theme, Menu List)
2. Detail Phase: 逐页生成具体的图表和组件数据
3. Merge Phase: 合并并追加系统管理页面
"""
import time
import json
import hashlib
import logging
import random
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from threading import Lock
from typing import Dict, Any, List
from core.deepseek_client import DeepSeekClient
from core.llm_budget import llm_budget
from core.pipeline_config import PIPELINE_PROTOCOL_VERSION
from core.random_engine import get_random_engine
from modules.industry_adapter import get_adapter
from modules.project_charter import (
    build_charter_prompt_context,
    normalize_project_charter,
    validate_project_charter,
)
from modules.executable_spec_builder import build_executable_spec
from modules.ui_skill_orchestrator import build_ui_skill_artifacts
from config import BASE_DIR

# Task 2: 从配置文件加载管理员名称池
DATA_CONFIG_PATH = BASE_DIR / "config" / "data_config.json"

def _load_data_config() -> Dict[str, Any]:
    """加载数据配置"""
    if DATA_CONFIG_PATH.exists():
        try:
            with open(DATA_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    # 返回默认配置
    return {
        "admin_names": ["王主管", "张管理员", "李运维", "赵审计员", "刘总监", "陈经理"]
    }

_data_config = _load_data_config()
ADMIN_NAMES = _data_config.get("admin_names", ["王主管", "张管理员", "李运维"])

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ProjectPlanner:
    CODE_GENERATION_PROFILES = {
        "economy": {
            "novelty_threshold": 0.35,
            "file_novelty_budget": 0.35,
            "project_novelty_threshold": 0.32,
            "rewrite_candidates": 1,
            "max_rewrite_rounds": 1,
            "heavy_search_ratio": 0.20,
            "enable_project_novelty_gate": False,
            "max_risky_files": 8,
            "max_syntax_fail_files": 4,
            "min_ai_line_ratio": 0.10,
            "enforce_file_gate": False,
            "enforce_file_gate_on_obfuscation": False,
            "max_failed_files": 8,
            "max_llm_attempts_per_file": 2,
            "llm_text_retries": 1,
            "max_total_llm_calls": 12,
            "max_total_llm_failures": 4,
            "disable_llm_on_budget_exhausted": True,
            "disable_llm_on_failures": True,
            "enable_embedding_similarity": False,
            "embedding_similarity_weight": 0.15,
            "embedding_model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "embedding_max_chars": 2400,
            "history_forbidden_enabled": True,
            "history_forbidden_max_files": 120,
            "forbidden_feedback_path": "data/forbidden_feedback.jsonl",
            "llm_provider_override": "",
            "llm_model_override": "",
        },
        "high_constraint": {
            "novelty_threshold": 0.46,
            "file_novelty_budget": 0.46,
            "project_novelty_threshold": 0.42,
            "rewrite_candidates": 2,
            "max_rewrite_rounds": 2,
            "heavy_search_ratio": 0.30,
            "enable_project_novelty_gate": True,
            "max_risky_files": 2,
            "max_syntax_fail_files": 0,
            "min_ai_line_ratio": 0.20,
            "enforce_file_gate": True,
            "enforce_file_gate_on_obfuscation": False,
            "max_failed_files": 0,
            "max_llm_attempts_per_file": 4,
            "llm_text_retries": 2,
            "max_total_llm_calls": 32,
            "max_total_llm_failures": 10,
            "disable_llm_on_budget_exhausted": True,
            "disable_llm_on_failures": True,
            "enable_embedding_similarity": False,
            "embedding_similarity_weight": 0.15,
            "embedding_model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "embedding_max_chars": 2400,
            "history_forbidden_enabled": True,
            "history_forbidden_max_files": 120,
            "forbidden_feedback_path": "data/forbidden_feedback.jsonl",
            "llm_provider_override": "",
            "llm_model_override": "",
        },
    }
    DEFAULT_CODE_QUALITY_PROFILE = "economy"
    DEFAULT_CODE_GENERATION_CONFIG = {
        "quality_profile": DEFAULT_CODE_QUALITY_PROFILE,
        "novelty_threshold": 0.35,
        "file_novelty_budget": 0.35,
        "project_novelty_threshold": 0.32,
        "rewrite_candidates": 1,
        "max_rewrite_rounds": 1,
        "heavy_search_ratio": 0.20,
        "enable_project_novelty_gate": False,
        "max_risky_files": 8,
        "max_syntax_fail_files": 4,
        "min_ai_line_ratio": 0.10,
        "enforce_file_gate": False,
        "enforce_file_gate_on_obfuscation": False,
        "max_failed_files": 8,
        "max_llm_attempts_per_file": 2,
        "llm_text_retries": 1,
        "max_total_llm_calls": 12,
        "max_total_llm_failures": 4,
        "disable_llm_on_budget_exhausted": True,
        "disable_llm_on_failures": True,
        "enable_embedding_similarity": False,
        "embedding_similarity_weight": 0.15,
        "embedding_model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_max_chars": 2400,
        "history_forbidden_enabled": True,
        "history_forbidden_max_files": 120,
        "forbidden_feedback_path": "data/forbidden_feedback.jsonl",
        "llm_provider_override": "",
        "llm_model_override": "",
    }

    @classmethod
    def _normalize_quality_profile(cls, value: Any) -> str:
        raw = str(value or "").strip().lower()
        alias = {
            "economy": "economy",
            "low": "economy",
            "lite": "economy",
            "balanced": "economy",
            "default": "economy",
            "high_constraint": "high_constraint",
            "strict": "high_constraint",
            "high": "high_constraint",
        }
        profile = alias.get(raw, cls.DEFAULT_CODE_QUALITY_PROFILE)
        if profile not in cls.CODE_GENERATION_PROFILES:
            return cls.DEFAULT_CODE_QUALITY_PROFILE
        return profile

    def __init__(self, api_key: str = None):
        """
        初始化规划器
        """
        self.client = DeepSeekClient(api_key=api_key)
        self._save_lock = Lock()
        self.max_page_workers = self._resolve_page_worker_count(default_workers=2)
        self.max_page_failure_ratio = 0.35

        # 初始化 RandomEngine 单例
        self.random_engine = get_random_engine()

        # 确保输出目录存在
        (BASE_DIR / "output").mkdir(parents=True, exist_ok=True)

    def _resolve_page_worker_count(self, default_workers: int = 2) -> int:
        """
        根据当前网关协议动态决定页面详情并发，减少中转站限流触发概率。
        """
        try:
            http_mode = bool(self.client._should_use_http_compatible())
            api_style = str(self.client._resolve_api_style())
        except Exception:
            return max(1, int(default_workers))

        if http_mode and api_style == "responses":
            logger.info("检测到 http/responses 模式，规划阶段启用稳态串行策略（max_page_workers=1）")
            return 1
        if http_mode:
            return min(max(1, int(default_workers)), 2)
        return max(1, int(default_workers))

    @staticmethod
    def _extract_name_tokens(text: str) -> List[str]:
        """
        从项目名中抽取粗粒度词元，用于历史项目相似度匹配。
        同时兼容中文短语和英文单词。
        """
        raw = str(text or "").strip().lower()
        if not raw:
            return []

        tokens: List[str] = []

        # 英文/数字 token
        for t in re.findall(r"[a-z0-9_]{2,}", raw):
            tokens.append(t)

        # 中文连续片段
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", raw):
            tokens.append(chunk)
            # 再补充 2-4 字短片段，提高召回
            max_n = min(4, len(chunk))
            for n in range(2, max_n + 1):
                for i in range(0, len(chunk) - n + 1):
                    tokens.append(chunk[i:i + n])

        # 去重保序
        deduped: List[str] = []
        seen = set()
        for t in tokens:
            if t in seen:
                continue
            seen.add(t)
            deduped.append(t)
        return deduped

    def _build_uniqueness_constraints(self, project_name: str, sample_limit: int = 80) -> Dict[str, Any]:
        """
        基于历史 project_plan 生成“负约束”，降低项目间同质化风险。
        仅用于 prompt 约束，不会阻塞流程。
        """
        output_root = BASE_DIR / "output"
        if not output_root.exists():
            return {
                "similar_projects": [],
                "forbidden_menu_titles": [],
                "forbidden_feature_phrases": [],
            }

        current_tokens = set(self._extract_name_tokens(project_name))
        scored: List[Dict[str, Any]] = []

        for plan_path in list(output_root.glob("*/project_plan.json"))[:sample_limit]:
            candidate_name = plan_path.parent.name
            if candidate_name == project_name:
                continue
            try:
                with open(plan_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            cand_tokens = set(self._extract_name_tokens(candidate_name))
            if current_tokens and cand_tokens:
                jaccard = len(current_tokens & cand_tokens) / max(1, len(current_tokens | cand_tokens))
            else:
                jaccard = 0.0
            ratio = SequenceMatcher(None, project_name.lower(), candidate_name.lower()).ratio()
            score = max(jaccard, ratio * 0.65)

            scored.append(
                {
                    "name": candidate_name,
                    "score": score,
                    "plan": data,
                }
            )

        if not scored:
            return {
                "similar_projects": [],
                "forbidden_menu_titles": [],
                "forbidden_feature_phrases": [],
            }

        scored.sort(key=lambda x: x["score"], reverse=True)
        top = [x for x in scored[:12] if x["score"] >= 0.20]

        menu_counter: Counter = Counter()
        feature_counter: Counter = Counter()

        for item in top:
            plan = item.get("plan", {})
            for menu in plan.get("menu_list", []) or []:
                title = str(menu.get("title", "")).strip()
                if title:
                    menu_counter[title] += 1

            intro = plan.get("project_intro", {}) or {}
            features = intro.get("main_features", []) or []
            for feat in features:
                text = str(feat).strip()
                if text:
                    feature_counter[text] += 1

        # 常见“模板化标题”优先作为禁用项
        hard_generic_titles = {
            "数据概览", "系统首页", "首页", "统计分析", "综合看板", "仪表盘",
            "总览", "信息中心", "管理中心",
        }

        forbidden_menu_titles = []
        for title, _ in menu_counter.most_common(10):
            if title in hard_generic_titles or menu_counter[title] >= 2:
                forbidden_menu_titles.append(title)
        for title in hard_generic_titles:
            if title not in forbidden_menu_titles:
                forbidden_menu_titles.append(title)

        forbidden_feature_phrases = [x for x, _ in feature_counter.most_common(8) if feature_counter[x] >= 2]

        similar_projects = [
            {"name": item["name"], "score": round(float(item["score"]), 3)}
            for item in top[:5]
        ]

        return {
            "similar_projects": similar_projects,
            "forbidden_menu_titles": forbidden_menu_titles[:12],
            "forbidden_feature_phrases": forbidden_feature_phrases[:8],
        }

    @staticmethod
    def _format_uniqueness_constraints_prompt(constraints: Dict[str, Any]) -> str:
        similar = constraints.get("similar_projects", []) or []
        forbidden_titles = constraints.get("forbidden_menu_titles", []) or []
        forbidden_features = constraints.get("forbidden_feature_phrases", []) or []

        if not similar and not forbidden_titles and not forbidden_features:
            return "### 同质化约束\n- 当前未检索到高相似历史项目，请仍保持业务术语具体化与页面语义差异化。"

        lines = ["### 同质化约束（来自历史项目）"]
        if similar:
            lines.append("- 历史相似项目（仅供规避参考）:")
            for item in similar:
                lines.append(f"  * {item.get('name')} (sim={item.get('score')})")

        if forbidden_titles:
            lines.append(f"- 菜单标题禁用词：{', '.join(forbidden_titles)}")
        if forbidden_features:
            lines.append(f"- 功能短语高频项：{', '.join(forbidden_features)}")

        lines.append("- 生成要求：必须使用“行业对象 + 业务动作”命名页面，例如“样本任务分配”“版本冲突比对”“审批节点追踪”。")
        return "\n".join(lines)

    def _build_operation_flow_profile(self, final_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成“端到端操作流程画像”，供说明书/审计使用。
        目标：让文档不只列功能，而是强调真实业务流转。
        """
        project_name = str(final_plan.get("project_name", ""))
        project_seed = int(hashlib.md5(project_name.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(project_seed)

        intro = final_plan.get("project_intro", {}) or {}
        roles = intro.get("target_users", []) or []
        if not roles:
            roles = ["系统管理员", "业务操作员", "审核负责人"]
        roles = [str(r).strip() for r in roles if str(r).strip()]
        if not roles:
            roles = ["系统管理员", "业务操作员", "审核负责人"]

        menu = final_plan.get("menu_list", []) or []
        business_menu = [m for m in menu if str(m.get("page_id", "")).startswith("page_")]
        if not business_menu:
            business_menu = menu[:]

        flow_count = min(3, max(1, len(business_menu)))
        flows = []
        for idx in range(flow_count):
            actor = roles[idx % len(roles)]
            selected = business_menu[idx: idx + 3] or business_menu[:3]
            if not selected:
                selected = [{"title": "业务处理", "page_id": "page_1"}]

            steps = []
            for step_i, page in enumerate(selected, start=1):
                page_title = str(page.get("title", f"步骤{step_i}")).strip()
                page_id = str(page.get("page_id", "page_1")).strip()
                action = rng.choice(["检索并过滤", "录入并提交", "校验并处理", "审批并发布", "追踪并归档"])
                steps.append(
                    {
                        "step": step_i,
                        "page_id": page_id,
                        "page_title": page_title,
                        "action": f"{action}{page_title}相关数据",
                    }
                )

            flows.append(
                {
                    "flow_name": f"流程{idx + 1}：{selected[0].get('title', '业务流程')}",
                    "actor": actor,
                    "trigger": rng.choice(["收到新任务", "定时巡检触发", "人工发起申请"]),
                    "steps": steps,
                    "output": rng.choice(["生成业务记录", "形成审批结果", "输出归档报告"]),
                }
            )

        return {
            "roles": roles,
            "flows": flows,
        }

    def _build_code_generation_config(self, overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        构建代码生成配置（默认值 + 覆盖项 + 边界收敛）。
        目的：统一三入口（GUI/API/CLI）使用同一套参数定义，避免漂移。
        """
        raw_overrides = dict(overrides or {})
        requested_profile = raw_overrides.get(
            "quality_profile",
            raw_overrides.get("code_quality_profile", self.DEFAULT_CODE_QUALITY_PROFILE),
        )
        profile = self._normalize_quality_profile(requested_profile)
        cfg = dict(self.CODE_GENERATION_PROFILES.get(profile, self.CODE_GENERATION_PROFILES[self.DEFAULT_CODE_QUALITY_PROFILE]))
        cfg["quality_profile"] = profile

        # 兼容历史代码中可能读取 DEFAULT_CODE_GENERATION_CONFIG 的场景。
        for key, value in self.DEFAULT_CODE_GENERATION_CONFIG.items():
            if key not in cfg:
                cfg[key] = value
        if raw_overrides:
            for key, value in raw_overrides.items():
                if key in cfg and value is not None:
                    cfg[key] = value

        cfg["quality_profile"] = self._normalize_quality_profile(cfg.get("quality_profile"))

        # 边界收敛，避免无效配置导致超长任务或全部拦截
        cfg["novelty_threshold"] = max(0.0, min(float(cfg["novelty_threshold"]), 1.0))
        cfg["file_novelty_budget"] = max(0.0, min(float(cfg["file_novelty_budget"]), 1.0))
        cfg["project_novelty_threshold"] = max(0.0, min(float(cfg["project_novelty_threshold"]), 1.0))
        cfg["rewrite_candidates"] = max(1, min(int(cfg["rewrite_candidates"]), 3))
        cfg["max_rewrite_rounds"] = max(1, min(int(cfg["max_rewrite_rounds"]), 4))
        cfg["heavy_search_ratio"] = max(0.15, min(float(cfg["heavy_search_ratio"]), 0.5))
        cfg["max_risky_files"] = max(0, int(cfg["max_risky_files"]))
        cfg["max_syntax_fail_files"] = max(0, int(cfg["max_syntax_fail_files"]))
        cfg["min_ai_line_ratio"] = max(0.0, min(float(cfg["min_ai_line_ratio"]), 1.0))
        cfg["enforce_file_gate"] = bool(cfg["enforce_file_gate"])
        cfg["enforce_file_gate_on_obfuscation"] = bool(cfg.get("enforce_file_gate_on_obfuscation", False))
        cfg["max_failed_files"] = max(0, int(cfg["max_failed_files"]))
        cfg["max_llm_attempts_per_file"] = max(1, min(int(cfg["max_llm_attempts_per_file"]), 8))
        cfg["llm_text_retries"] = max(1, min(int(cfg["llm_text_retries"]), 3))
        cfg["max_total_llm_calls"] = max(0, min(int(cfg.get("max_total_llm_calls", 12)), 300))
        cfg["max_total_llm_failures"] = max(0, min(int(cfg.get("max_total_llm_failures", 4)), 100))
        cfg["disable_llm_on_budget_exhausted"] = bool(cfg.get("disable_llm_on_budget_exhausted", True))
        cfg["disable_llm_on_failures"] = bool(cfg.get("disable_llm_on_failures", True))
        cfg["enable_embedding_similarity"] = bool(cfg["enable_embedding_similarity"])
        cfg["embedding_similarity_weight"] = max(0.0, min(float(cfg["embedding_similarity_weight"]), 0.4))
        cfg["embedding_max_chars"] = max(400, min(int(cfg["embedding_max_chars"]), 8000))
        cfg["history_forbidden_enabled"] = bool(cfg["history_forbidden_enabled"])
        cfg["history_forbidden_max_files"] = max(0, int(cfg["history_forbidden_max_files"]))
        cfg["llm_provider_override"] = str(cfg.get("llm_provider_override", "") or "").strip()
        cfg["llm_model_override"] = str(cfg.get("llm_model_override", "") or "").strip()
        return cfg

    def plan_total_project(
        self,
        project_name: str,
        genome_overrides: Dict[str, str] = None,
        project_charter: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        第一阶段：生成全局大纲
        """
        logger.info(f"Step 1/3: 生成项目大纲 - {project_name}")

        # 设置项目种子（为 RandomEngine 初始化）
        self.random_engine.set_project_seed(project_name)

        # 应用覆盖
        if genome_overrides:
            self.random_engine.apply_overrides(genome_overrides)

        # 行业适配
        adapter = get_adapter()
        industry_key = adapter.detect_industry(project_name)
        industry_context_prompt = adapter.get_industry_prompt(industry_key)
        logger.info(f"Detected Industry: {industry_key}")

        # 风格随机化：打破LLM生成的固定模式
        style_prompts = [
            "你是一位资深软件架构师。请为",
            "作为企业级系统设计专家，请为",
            "你是经验丰富的技术架构师。请为",
            "作为软件系统规划师，请为",
            "你是精通业务建模的架构师。请为"
        ]
        seed_int = int(hashlib.md5(project_name.encode()).hexdigest()[:8], 16)
        style_rng = random.Random(seed_int)
        selected_style = style_rng.choice(style_prompts)
        charter_prompt_context = build_charter_prompt_context(project_charter or {})

        # 随机化页面数量 (3-7页，打破固定模式)
        page_count = style_rng.randint(3, 7)
        uniqueness_constraints = self._build_uniqueness_constraints(project_name)
        uniqueness_prompt = self._format_uniqueness_constraints_prompt(uniqueness_constraints)
        similar_cnt = len(uniqueness_constraints.get("similar_projects", []) or [])
        forbidden_cnt = len(uniqueness_constraints.get("forbidden_menu_titles", []) or [])
        logger.info(f"同质化约束已加载: 相似项目={similar_cnt}, 菜单禁用词={forbidden_cnt}")

        prompt = f"""# 任务
{selected_style}"{ project_name }"设计一个管理系统的**全局大纲**。

{industry_context_prompt}
{uniqueness_prompt}
{charter_prompt_context}

# 要求
1. **仅生成大纲**：包含项目名称、主题色、菜单列表。
2. **菜单规划**：
   - 生成 {page_count} 个与行业紧密相关的业务页面。
   - **不要**包含"系统管理"（将在代码中自动追加）。
   - 每个菜单包含：title (标题), icon (MDI图标), page_id (如 page_1)。
   - 菜单标题必须体现具体业务对象和动作，不得使用“数据概览/首页/统计分析/综合看板”等泛化词。
3. **系统简介 (project_intro)**：
   - background: 20-50字，说明行业痛点或需求背景
   - overview: 50-100字，系统定位与核心价值
   - target_users: 数组，列出 3-4 个主要用户群体（如：["企业HR部门", "职业健康医生", "安全生产管理员", "第三方检测机构"]）
   - main_features: 数组，列出 3-4 个核心功能点，每点不超过15字
   - advantages: 100字左右，说明技术创新点或核心优势
4. **软著平台字段 (copyright_fields)**：
   - development_purpose: 开发目的（50字内）
   - industry: 数组，列出 3 个面向的领域/行业（如：["医疗健康", "企业管理", "数据分析"]）
   - main_functions: 主要功能详述（**严格限制字数在100-200字之间**。必须使用**连贯的自然语言段落**描述软件的核心业务流程。**严禁**使用"功能1、功能2"或"四字短语、四字短语"的罗列形式。必须包含完整的主谓宾句式，例如"系统通过...实现了...，用户可以..."。）
   - technical_features: 技术特点（100字内，如：微服务架构、AI预警等）
   - tech_category: 技术特点分类，从以下14个选项中选择最匹配的1个（注意：不要选择医疗软件）：
     * APP游戏软件、教育软件、金融软件、地理信息软件、云计算软件、
       信息安全软件、大数据软件、人工智能软件、VR软件、5G软件、小程序、
       物联网软件、智慧城市软件、其他
   - tech_detail: 该分类下的具体技术特点描述（100字内）
5. **代码蓝图 (code_blueprint)**：
   - entities: 核心业务实体名列表（3-5个，如：["HealthRecord", "AlertLog", "UserProfile"]）
   - controllers: 每个页面对应的控制器（包含控制器名、对应page_id、方法列表）
     * 每个方法包含：name（方法名）, desc（功能描述）, http（HTTP方法和路径）
   - services: 业务逻辑服务列表（包含服务名和核心方法）
6. **输出格式**：纯 JSON。
7. **章程一致性（强制）**：
   - 菜单与页面命名必须覆盖“核心流程”中的关键业务动作。
   - 角色命名、接口语义必须与“角色与职责”一致。
   - 不得超出“业务边界”，不得引入无关行业场景。

# JSON 示例
{{
  "project_name": "{ project_name }",
  "theme_color": "#4CAF50",
  "project_intro": {{
    "background": "随着企业员工健康管理需求增加，传统纸质记录效率低下，亟需数字化解决方案。",
    "overview": "本系统通过智能化监测手段，实时采集员工健康数据，结合AI算法进行职业病风险预警，为企业提供科学的健康管理决策支持。",
    "target_users": ["企业HR部门", "职业健康医生", "安全生产管理员", "第三方检测机构"],
    "main_features": ["每日健康数据采集", "职业病风险智能预警", "健康档案管理", "统计分析报表"],
    "advantages": "采用微服务架构实现模块化部署,集成深度学习算法进行疾病趋势预测,支持多维度数据可视化分析,提供移动端与PC端无缝协同体验。"
  }},
  "copyright_fields": {{
    "development_purpose": "为企业提供员工健康监测与职业病风险预警的一体化解决方案",
    "industry": ["企业管理", "职业安全", "数据分析"],
    "main_functions": "本系统集成了员工健康档案管理与职业病风险预警功能，能够通过智能硬件实时采集员工体温、心率等健康数据。系统利用深度学习算法对采集的数据进行实时分析，自动识别潜在的职业病风险并向管理层发送预警通知。此外，系统还提供了多维度数据可视化大屏，帮助企业管理者直观掌握全员健康趋势，实现了从数据采集、风险研判到决策支持的全流程数字化管理。",
    "technical_features": "采用B/S架构,基于Spring Boot微服务框架,集成机器学习算法进行风险预测,使用ECharts实现数据可视化,支持移动端响应式设计。",
    "tech_category": "人工智能软件",
    "tech_detail": "集成机器学习算法进行风险预测，使用ECharts实现多维数据可视化，支持移动端响应式设计，采用密码学技术保障数据安全"
  }},
  "code_blueprint": {{
    "entities": ["HealthRecord", "AlertLog", "UserProfile", "DailyReport"],
    "controllers": [
      {{
        "name": "HealthController",
        "page_id": "page_1",
        "methods": [
          {{"name": "get_daily_report", "desc": "获取每日健康报告", "http": "GET /api/health/daily"}},
          {{"name": "submit_health_data", "desc": "提交健康数据", "http": "POST /api/health/submit"}}
        ]
      }},
      {{
        "name": "AlertController",
        "page_id": "page_2",
        "methods": [
          {{"name": "get_alert_list", "desc": "获取预警列表", "http": "GET /api/alert/list"}},
          {{"name": "trigger_alert", "desc": "触发预警", "http": "POST /api/alert/trigger"}}
        ]
      }}
    ],
    "services": [
      {{
        "name": "HealthService",
        "methods": [
          {{"name": "analyze_risk", "desc": "风险因子分析"}},
          {{"name": "calculate_score", "desc": "健康评分计算"}}
        ]
      }}
    ]
  }},
  "menu_list": [
    {{ "title": "数据概览", "icon": "mdi mdi-view-dashboard", "page_id": "page_1" }},
    {{ "title": "林区监测", "icon": "mdi mdi-tree", "page_id": "page_2" }}
  ]
}}
"""
        # 1. 生成初稿
        plan_data = self.client.generate_json(prompt)
        plan_data["novelty_constraints"] = uniqueness_constraints

        # 2. [关键修复] 强制校验并修正字段字数
        self._validate_and_fix_copyright_fields(plan_data)

        # 3. [新增] 注入项目基因图谱
        genome = self.random_engine.get_genome()
        # 注入行业特征
        genome["name"] = project_name # Ensure name is in genome for adapter
        genome = adapter.enhance_genome(genome)
        plan_data["genome"] = genome

        logger.info(f"已注入项目基因图谱: {plan_data['genome'].get('target_language', 'N/A')} / {plan_data['genome'].get('ui_framework', 'N/A')} / Industry={genome.get('industry_context', {}).get('key', 'N/A')}")

        return plan_data

    def _validate_and_fix_copyright_fields(self, data: Dict[str, Any]):
        """
        校验软著字段字数，如果不满足要求则单独调用 LLM 进行重写
        保证 main_functions 严格在 100-200 字之间
        """
        if "copyright_fields" not in data:
            return

        cf = data["copyright_fields"]

        # 规则配置: (字段名, 最小字数, 最大字数, 字段描述)
        constraints = [
            ("main_functions", 100, 200, "软件的主要功能"),
            ("technical_features", 50, 120, "软件的技术特点"),
            ("tech_detail", 10, 100, "技术特点详细描述")
        ]

        for field, min_len, max_len, desc in constraints:
            text = cf.get(field, "")
            current_len = len(text)

            # 如果字数不达标（太短或太长）
            if current_len < min_len or current_len > max_len:
                logger.warning(f"字段 '{field}' 字数({current_len})不符合要求[{min_len}-{max_len}]，正在重写...")

                new_text = self._refine_text_length(text, min_len, max_len, desc)

                # 更新字段
                cf[field] = new_text
                logger.info(f"字段 '{field}' 已修正: {len(text)} -> {len(new_text)} 字")

    def _refine_text_length(self, text: str, min_len: int, max_len: int, context: str) -> str:
        """使用 LLM 专门重写文本以符合字数要求"""
        prompt = f"""# 任务
请重写以下这段关于"{context}"的描述，使其字数**严格控制在 {min_len} 到 {max_len} 字之间**。

# 原文
{text}

# 要求
1. 保持原意，保留核心信息。
2. 语言精练、专业，符合软件著作权申请规范。
3. **必须生成连贯的段落**，不要使用列表或序号。
4. **字数必须在 {min_len} 到 {max_len} 之间**（当前字数：{len(text)}）。
5. 直接输出重写后的内容，不要包含任何解释。

# 输出格式 (JSON)
{{
  "refined_text": "重写后的文本..."
}}
"""
        try:
            # 使用 generate_json 确保拿到干净的文本
            res = self.client.generate_json(prompt)
            new_text = res.get("refined_text", text)

            # 双重检查：如果重写后还是不满足，做简单的截断处理作为保底（针对过长情况）
            if len(new_text) > max_len:
                 new_text = new_text[:max_len-1] + "。"

            return new_text
        except Exception as e:
            logger.error(f"重写文本失败: {e}")
            return text

    def plan_single_page(self, project_name: str, page_info: Dict[str, str]) -> Dict[str, Any]:
        """
        第二阶段：为单个页面生成详细组件
        """
        page_title = page_info.get('title', '未命名')
        logger.info(f"Step 2/3: 生成页面详情 - {page_title}")

        # 页面级别风格随机化
        page_style_prompts = [
            "为",
            "请为",
            "针对",
            "请针对",
            "请设计"
        ]
        import hashlib
        page_seed = int(hashlib.md5((project_name + page_title).encode()).hexdigest()[:8], 16)
        page_rng = random.Random(page_seed)
        page_style = page_rng.choice(page_style_prompts)

        # 获取行业上下文
        adapter = get_adapter()
        industry_key = adapter.detect_industry(project_name)
        industry_context_prompt = adapter.get_industry_prompt(industry_key)

        prompt = f"""# 任务
{page_style}"{ project_name }"的子页面"{ page_title }"生成详细组件数据。

{industry_context_prompt}

# 核心要求 (Result must look REAL & PROFESSIONAL)
1. **数据真实感 (至关重要)**：
   - **绝对禁止**使用 [10, 20, 30, 40, 50] 这种规律数据。
   - 数据必须具有**真实业务特征**：
     * 如果是用户数，使用如 12,584, 8,932 等不规则大数。
     * 如果是百分比，使用如 87.5%, 12.3% 等带小数的值。
     * 时间轴必须包含 **分:秒** (如 09:30, 10:00) 或具体日期 (如 11-01, 11-02)。
   - 此页面是为了**申请软件著作权**，必须看起来像一个已经投入使用的成熟商业系统。

2. **组件丰富度**：
   - 必须包含 **8-12 个混合组件**（数量随机，打破固定模式）。
   - 必须包含：**3-4个统计卡片 (Stats Card)** (放在最前)。
   - 必须包含：**3-6个复杂图表**（从以下类型中随机选择：Line, Bar, Pie, Radar, Scatter, Gauge, Heatmap, Funnel, Sankey, Treemap）。
     * 折线图必须平滑 (`smooth: true`)。
     * 必须有 `tooltip`, `legend`, `grid` 配置。
     * **禁止出现两个相同类型的图表！**
   - 可选包含：**0-2个详细表格** (Table)。
     * 如有表格，必须至少 **8-10 行** 数据。
     * 包含"状态"列 (如: 正常, 审核中) 和 "操作"列 (如: 查看 | 编辑)。

3. **【强制】ID 命名规范 (CRITICAL)**：
   **必须严格遵守，否则系统无法截图：**
   | 组件类型 | ID格式 | 示例 |
   |---------|--------|------|
   | 统计卡片 | `widget_card_N` | widget_card_1, widget_card_2 |
   | 图表容器 | `widget_chart_N` | widget_chart_1, widget_chart_2 |
   | 表格容器 | `widget_table_N` | widget_table_1, widget_table_2 |

   **禁止使用**: chart_1, card_1, table_1 等格式。

4. **数据格式规范**：
   - 图表: ECharts `option` 结构完整。
   - 表格: `{{ "type": "table", "title": "...", "columns": ["ID", "名称", "...", "状态", "操作"], "rows": [["1001", "...", "...", "正常", "查看"], ...] }}`
   - 卡片: `{{ "type": "stats_card", "title": "...", "value": "12,345", "icon": "mdi mdi-...", "color": "primary|success|warning|danger|info" }}`

4. **描述生成（重要：必须包含操作步骤）**：
   - Page Description: 120-180字，分为两部分：
     * 第一部分（约60-80字）：说明页面的业务价值、数据来源和核心功能。
     * 第二部分（约60-80字）：描述用户的**具体操作流程**，使用"用户可通过..."、"点击..."、"选择..."等操作性语言。
     * 示例格式："本页面集成XXX功能，实时展示XXX数据...用户可通过顶部筛选栏选择时间范围和数据类型，点击图表区域可查看详细数据，支持一键导出Excel报表进行离线分析。"
   - Component Description: 50-80字，包含两部分：
     * 第一部分：说明组件的业务含义和数据分析价值。
     * 第二部分：说明用户如何操作该组件（如：点击查看详情、筛选条件、悬停显示数值等）。
     * 示例："展示近7日碳汇通量变化趋势，用于分析光合作用效率。用户可点击图例切换显示不同指标，鼠标悬停可查看具体数值。"

# JSON 输出结构（示例仅供参考，实际组件数量需随机生成）
{{
  "page_title": "{ page_title }",
  "page_description": "本页面集成多维数据监测与智能分析功能，实时展示核心业务指标动态变化趋势，为管理决策提供数据支撑。用户可通过顶部时间筛选器选择查询周期，点击各图表区域可下钻查看明细数据，支持一键导出PDF报表供离线分析使用。",
  "charts": [
    {{ "id": "widget_card_1", "type": "stats_card", "title": "今日访问量", "value": "14,502", "icon": "mdi mdi-eye", "color": "primary", "description": "统计当日平台独立访客数量，实时更新。点击卡片可跳转至访问详情页查看访客来源分布。" }},
    {{ "id": "widget_card_2", "type": "stats_card", "title": "总用户数", "value": "8,923", "icon": "mdi mdi-account-group", "color": "success", "description": "展示平台累计注册用户总量。用户可点击查看用户增长趋势图及画像分析。" }},
    {{ "id": "widget_card_3", "type": "stats_card", "title": "本月增长", "value": "23.5%", "icon": "mdi mdi-trending-up", "color": "info", "description": "对比上月同期的业务增长率指标。鼠标悬停可显示具体增长数值及环比详情。" }},
    {{ "id": "widget_card_4", "type": "stats_card", "title": "待处理任务", "value": "47", "icon": "mdi mdi-clipboard-check", "color": "warning", "description": "汇总当前待审核的工单任务数。点击可直接跳转至任务列表进行批量处理。" }},
    {{ "id": "widget_chart_1", "title": "数据趋势分析", "description": "展示近6个月核心指标变化趋势，支持多维度对比。用户可点击图例切换系列，鼠标悬停显示具体数值。", "option": {{ "tooltip": {{ "trigger": "axis" }}, "legend": {{ "data": ["系列1", "系列2"] }}, "grid": {{ "left": "3%", "right": "4%", "bottom": "15%", "containLabel": true }}, "xAxis": {{ "type": "category", "data": ["1月", "2月", "3月", "4月", "5月", "6月"] }}, "yAxis": {{ "type": "value" }}, "series": [{{ "name": "系列1", "type": "line", "smooth": true, "data": [120, 132, 101, 134, 90, 230] }}, {{ "name": "系列2", "type": "line", "smooth": true, "data": [220, 182, 191, 234, 290, 330] }}] }} }},
    {{ "id": "widget_chart_2", "title": "分类占比统计", "description": "直观呈现各业务分类的数据占比分布，辅助资源配置决策。点击扇区可高亮显示该分类详情。", "option": {{ "tooltip": {{ "trigger": "item" }}, "legend": {{ "top": "5%", "left": "center" }}, "series": [{{ "name": "分类", "type": "pie", "radius": ["40%", "70%"], "data": [{{ "value": 1048, "name": "类别A" }}, {{ "value": 735, "name": "类别B" }}, {{ "value": 580, "name": "类别C" }}] }}] }} }},
    {{ "id": "widget_chart_3", "title": "月度对比柱状图", "description": "横向对比各月份业务数据表现，识别业务高峰周期。用户可点击柱体查看该月详细报表。", "option": {{ "tooltip": {{ "trigger": "axis", "axisPointer": {{ "type": "shadow" }} }}, "grid": {{ "left": "3%", "right": "4%", "bottom": "3%", "containLabel": true }}, "xAxis": {{ "type": "category", "data": ["一月", "二月", "三月", "四月", "五月"] }}, "yAxis": {{ "type": "value" }}, "series": [{{ "name": "销量", "type": "bar", "data": [320, 332, 301, 334, 390] }}] }} }},
    {{ "id": "widget_chart_4", "title": "综合评分雷达图", "description": "基于多维指标体系进行综合能力评估。鼠标悬停可查看各指标具体分值，点击可对比历史结果。", "option": {{ "tooltip": {{}}, "radar": {{ "indicator": [{{ "name": "指标1", "max": 100 }}, {{ "name": "指标2", "max": 100 }}, {{ "name": "指标3", "max": 100 }}, {{ "name": "指标4", "max": 100 }}] }}, "series": [{{ "name": "评分", "type": "radar", "data": [{{ "value": [80, 90, 70, 85], "name": "综合评分" }}] }}] }} }},
    {{ "id": "widget_chart_5", "title": "区域分布散点图", "description": "通过散点分布揭示数据聚集特征与异常离群点。支持框选放大查看局部区域，双击重置视图。", "option": {{ "tooltip": {{ "trigger": "item" }}, "xAxis": {{ "type": "value" }}, "yAxis": {{ "type": "value" }}, "series": [{{ "type": "scatter", "symbolSize": 20, "data": [[10.0, 8.04], [8.07, 6.95], [13.0, 7.58], [9.05, 8.81], [11.0, 8.33]] }}] }} }},
    {{ "id": "widget_table_1", "type": "table", "title": "详细数据列表", "description": "展示业务明细数据，支持多条件筛选与排序。点击表头可升降序排列，点击操作列按钮查看详情或编辑，支持导出Excel。", "columns": ["ID", "名称", "类型", "数值", "状态", "操作"], "rows": [["001", "项目A", "类型1", "1,234", "\u003cspan class='badge badge-success'\u003e正常\u003c/span\u003e", "查看 | 编辑"], ["002", "项目B", "类型2", "2,345", "\u003cspan class='badge badge-success'\u003e正常\u003c/span\u003e", "查看 | 编辑"], ["003", "项目C", "类型1", "3,456", "\u003cspan class='badge badge-warning'\u003e待审核\u003c/span\u003e", "查看 | 编辑"]] }}
  ]
}}
"""
        return self.client.generate_json(prompt)

    def _get_admin_pages(self, project_name: str = "") -> List[Dict[str, Any]]:
        """获取后台管理页面数据（已启用差异化生成）"""
        # 使用项目名作为种子，确保同一项目可复现、不同项目有差异
        seed_source = project_name or "system_admin_pages"
        project_seed = int(hashlib.md5(seed_source.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(project_seed)

        # 引入差异化增强器
        from modules.document_differentiator import DocumentDifferentiator
        diff = DocumentDifferentiator({"project_name": project_name or "系统管理"})

        # === 页面1: 系统监控（差异化数据生成）===
        cpu_value = rng.randint(25, 75)
        memory_gb = round(rng.uniform(8.0, 20.0), 1)
        api_calls = rng.randint(800000, 2000000)
        error_count = rng.choice([0, 0, 0, 1, 2, 3])  # 大概率为0

        monitor_page = {
            "page_id": "system_monitor",
            "title": "系统监控",
            "icon": "mdi mdi-monitor-dashboard",
            "data": {
                "page_title": "系统运维监控中心",
                "page_description": diff.enrich_page_description(
                    "实时监控服务器集群运行状态、API接口调用频率及系统资源负载情况，保障平台高可用运行。",
                    "系统监控"
                ),
                "charts": [
                    {
                        "id": "sys_card_1", "type": "stats_card", "title": "CPU均值",
                        "value": f"{cpu_value}%", "icon": "mdi mdi-cpu-64-bit", "color": "info",
                        "description": "集群CPU平均使用率，支持自动弹性伸缩。点击可查看各节点CPU详细负载曲线图。"
                    },
                    {
                        "id": "sys_card_2", "type": "stats_card", "title": "内存占用",
                        "value": f"{memory_gb} GB", "icon": "mdi mdi-memory", "color": "warning",
                        "description": "核心数据库内存缓冲池占用情况。鼠标悬停显示各进程内存分配详情。"
                    },
                    {
                        "id": "sys_card_3", "type": "stats_card", "title": "今日API调用",
                        "value": f"{api_calls:,}", "icon": "mdi mdi-api", "color": "success",
                        "description": "全平台接口日调用总量，QPS峰值监控。点击可查看各接口调用排行榜及响应时间统计。"
                    },
                    {
                        "id": "sys_card_4", "type": "stats_card", "title": "异常日志",
                        "value": str(error_count), "icon": "mdi mdi-alert-circle",
                        "color": "success" if error_count == 0 else "warning",
                        "description": "今日产生的Error级别系统日志数量。点击可跳转至日志检索页面按条件筛选查看。"
                    },
                    {
                        "id": "sys_chart_line", "title": "流量负载趋势",
                        "description": "监控最近24小时流量波峰波谷，智能预测扩容需求。用户可拖动时间轴缩放查看区间，点击图例切换显示不同指标。",
                        "option": {
                            "title": { "text": "24小时QPS趋势" },
                            "tooltip": { "trigger": "axis" },
                            "legend": { "data": ["API请求", "数据库IO"] },
                            "grid": { "left": "3%", "right": "4%", "bottom": "3%", "containLabel": True },
                            "xAxis": { "type": "category", "data": [f"{i}:00" for i in range(24)] },
                            "yAxis": { "type": "value" },
                            "series": [
                                { "name": "API请求", "type": "line", "smooth": True, "areaStyle": {}, "data": [rng.randint(500, 1500) for _ in range(24)] },
                                { "name": "数据库IO", "type": "line", "smooth": True, "data": [rng.randint(200, 800) for _ in range(24)] }
                            ]
                        }
                    },
                    {
                        "id": "sys_chart_pie", "title": "资源使用分布",
                        "description": "展示系统各模块资源占用比例，辅助容量规划决策。点击扇区可高亮显示该模块详情，支持切换为柱状图视图。",
                        "option": {
                            "tooltip": { "trigger": "item" },
                            "legend": { "top": "5%", "left": "center" },
                            "series": [
                                {
                                    "name": "资源占用",
                                    "type": "pie",
                                    "radius": ["40%", "70%"],
                                    "avoidLabelOverlap": False,
                                    "itemStyle": { "borderRadius": 10, "borderColor": "#fff", "borderWidth": 2 },
                                    "label": { "show": True, "position": "outside" },
                                    "emphasis": { "label": { "show": True, "fontSize": 16, "fontWeight": "bold" } },
                                    "labelLine": { "show": True },
                                    "data": [
                                        { "value": 35, "name": "数据库" },
                                        { "value": 28, "name": "应用服务" },
                                        { "value": 18, "name": "缓存层" },
                                        { "value": 12, "name": "消息队列" },
                                        { "value": 7, "name": "其他服务" }
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "id": "sys_chart_bar", "title": "本周错误率统计",
                        "description": "追踪最近7天系统错误率变化趋势，及时发现异常波动。点击柱体可查看该日错误详情列表，支持导出错误报告。",
                        "option": {
                            "tooltip": { "trigger": "axis", "axisPointer": { "type": "shadow" } },
                            "grid": { "left": "3%", "right": "4%", "bottom": "3%", "containLabel": True },
                            "xAxis": { "type": "category", "data": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"] },
                            "yAxis": { "type": "value", "name": "错误率 (%)" },
                            "series": [{
                                "name": "错误率",
                                "type": "bar",
                                "barWidth": "60%",
                                "itemStyle": { "color": "#f56c6c" },
                                "data": [0.12, 0.08, 0.15, 0.09, 0.11, 0.06, 0.07]
                            }]
                        }
                    },
                    {
                        "id": "sys_chart_radar", "title": "系统健康度评估",
                        "description": "多维度综合评估系统运行状态，包括性能、稳定性、安全性等关键指标。鼠标悬停显示各维度评分，点击可查看历史趋势对比。",
                        "option": {
                            "tooltip": {},
                            "radar": {
                                "indicator": [
                                    { "name": "性能", "max": 100 },
                                    { "name": "稳定性", "max": 100 },
                                    { "name": "安全性", "max": 100 },
                                    { "name": "可用性", "max": 100 },
                                    { "name": "响应速度", "max": 100 }
                                ]
                            },
                            "series": [{
                                "name": "健康度",
                                "type": "radar",
                                "areaStyle": { "opacity": 0.3 },
                                "data": [
                                    {
                                        "value": [92, 88, 95, 99, 87],
                                        "name": "综合评分"
                                    }
                                ]
                            }]
                        }
                    },
                    {
                        "id": "sys_table_log", "type": "table", "title": "关键操作日志",
                        "description": "记录管理员关键操作行为，保障系统安全合规。支持按时间、操作人、模块筛选，点击行可查看操作详情，支持导出审计报告。",
                        "columns": ["LogID", "操作人", "IP地址", "模块", "操作内容", "状态", "时间"],
                        "rows": [
                            ["LOG-9281", "admin", "192.168.1.10", "用户管理", "重置用户密码", "<span class='badge badge-success'>成功</span>", "2023-11-02 10:23:11"],
                            ["LOG-9282", "security", "10.0.0.5", "防火墙", "更新规则库", "<span class='badge badge-success'>成功</span>", "2023-11-02 10:25:44"],
                            ["LOG-9283", "admin", "192.168.1.10", "配置中心", "修改超时参数", "<span class='badge badge-warning'>回滚</span>", "2023-11-02 10:30:12"],
                            ["LOG-9284", "system", "127.0.0.1", "定时任务", "数据归档", "<span class='badge badge-success'>成功</span>", "2023-11-02 11:00:00"],
                            ["LOG-9285", "audit", "192.168.1.20", "审计报表", "导出月度报表", "<span class='badge badge-success'>成功</span>", "2023-11-02 11:15:33"],
                            ["LOG-9286", "monitor", "10.0.0.8", "告警中心", "ACK 确认告警", "<span class='badge badge-primary'>已处理</span>", "2023-11-02 11:20:05"],
                            ["LOG-9287", "admin", "192.168.1.10", "用户管理", "新增角色", "<span class='badge badge-success'>成功</span>", "2023-11-02 13:45:12"],
                            ["LOG-9288", "admin", "192.168.1.10", "系统设置", "更新Logo", "<span class='badge badge-success'>成功</span>", "2023-11-02 14:10:00"]
                        ]
                    }
                ]
            }
        }
        
        # === 页面2: 用户管理（差异化数据生成）===
        total_users = rng.randint(8000, 20000)
        active_users = rng.randint(500, 1500)
        pending_audit = rng.randint(10, 50)
        banned_users = rng.randint(2, 15)

        user_page = {
            "page_id": "user_management",
            "title": "用户管理",
            "icon": "mdi mdi-account-multiple-outline",
            "data": {
                "page_title": "用户与权限管理中心",
                "page_description": diff.enrich_page_description(
                    "集中管理企业组织架构、用户账号生命周期及角色权限分配，支持多维度的用户行为审计与安全管控。",
                    "用户管理"
                ),
                "charts": [
                    {
                        "id": "usr_card_1", "type": "stats_card", "title": "总用户数",
                        "value": f"{total_users:,}", "icon": "mdi mdi-account-group", "color": "primary",
                        "description": "平台已注册并激活的有效账户总量。点击可跳转至用户列表查看完整用户档案。"
                    },
                    {
                        "id": "usr_card_2", "type": "stats_card", "title": "今日活跃",
                        "value": f"{active_users:,}", "icon": "mdi mdi-account-clock", "color": "success",
                        "description": "24小时内有登录或操作记录的活跃用户ID数。点击可查看活跃用户实时在线列表。"
                    },
                    {
                        "id": "usr_card_3", "type": "stats_card", "title": "待审核认证",
                        "value": str(pending_audit), "icon": "mdi mdi-account-alert", "color": "warning",
                        "description": "等待人工复核的企业或实名认证申请。点击可直接进入审核工作台进行批量审批操作。"
                    },
                    {
                        "id": "usr_card_4", "type": "stats_card", "title": "封禁账户",
                        "value": str(banned_users), "icon": "mdi mdi-account-off", "color": "danger",
                        "description": "因违规操作被系统自动冻结或人工封禁的账户。点击可查看封禁原因并进行解封操作。"
                    },
                    {
                        "id": "usr_chart_pie", "title": "用户角色分布",
                        "description": "直观展示系统中各权限角色的占比情况，评估权限分配健康度。点击扇区可筛选显示该角色用户列表。",
                        "option": {
                            "tooltip": { "trigger": "item" },
                            "legend": { "top": "5%", "left": "center" },
                            "series": [
                                {
                                    "name": "角色架构",
                                    "type": "pie",
                                    "radius": ["40%", "70%"],
                                    "avoidLabelOverlap": False,
                                    "itemStyle": { "borderRadius": 10, "borderColor": "#fff", "borderWidth": 2 },
                                    "label": { "show": False, "position": "center" },
                                    "emphasis": { "label": { "show": True, "fontSize": 40, "fontWeight": "bold" } },
                                    "labelLine": { "show": False },
                                    "data": [
                                        { "value": 1048, "name": "普通用户" },
                                        { "value": 735, "name": "部门经理" },
                                        { "value": 580, "name": "财务专员" },
                                        { "value": 484, "name": "系统管理员" },
                                        { "value": 300, "name": "审计人员" }
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "id": "usr_chart_bar", "title": "本周新用户注册趋势",
                        "description": "跟踪最近7天新用户注册量的波动情况。点击柱体可查看该日注册用户明细，支持按渠道来源筛选。",
                        "option": {
                            "tooltip": { "trigger": "axis", "axisPointer": { "type": "shadow" } },
                            "grid": { "left": "3%", "right": "4%", "bottom": "3%", "containLabel": True },
                            "xAxis": { "type": "category", "data": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] },
                            "yAxis": { "type": "value" },
                            "series": [{
                                "name": "注册量",
                                "type": "bar",
                                "barWidth": "60%",
                                "data": [120, 132, 101, 134, 90, 230, 210]
                            }]
                        }
                    },
                    {
                        "id": "usr_chart_line", "title": "用户活跃度趋势",
                        "description": "分析近30天用户登录活跃度变化，识别用户留存模式。可点击图例切换日活与周活指标，拖动查看历史数据。",
                        "option": {
                            "tooltip": { "trigger": "axis" },
                            "legend": { "data": ["日活跃", "周活跃"] },
                            "grid": { "left": "3%", "right": "4%", "bottom": "15%", "containLabel": True },
                            "xAxis": {
                                "type": "category",
                                "data": [f"{i+1}日" for i in range(30)]
                            },
                            "yAxis": { "type": "value" },
                            "series": [
                                {
                                    "name": "日活跃",
                                    "type": "line",
                                    "smooth": True,
                                    "data": [rng.randint(600, 1000) for _ in range(30)]
                                },
                                {
                                    "name": "周活跃",
                                    "type": "line",
                                    "smooth": True,
                                    "data": [rng.randint(2000, 3500) for _ in range(30)]
                                }
                            ]
                        }
                    },
                    {
                        "id": "usr_chart_scatter", "title": "用户行为分析散点图",
                        "description": "基于用户登录频次与活跃时长进行聚类分析，识别核心用户群体。支持框选区域查看用户详情，双击重置视图。",
                        "option": {
                            "tooltip": { "trigger": "item" },
                            "xAxis": { "type": "value", "name": "登录次数/月" },
                            "yAxis": { "type": "value", "name": "平均在线时长(小时)" },
                            "series": [{
                                "type": "scatter",
                                "symbolSize": 12,
                                "data": [
                                    [25, 8.5], [18, 6.2], [32, 12.3], [45, 15.8], [12, 4.5],
                                    [28, 9.7], [38, 13.2], [22, 7.8], [50, 18.5], [15, 5.3],
                                    [35, 11.2], [42, 14.6], [20, 7.1], [48, 16.9], [30, 10.4]
                                ]
                            }]
                        }
                    },
                    {
                        "id": "usr_table_list", "type": "table", "title": "用户详细列表",
                        "description": "支持对用户数据进行多维度筛选、状态变更及详情查看。点击表头可排序，点击操作列按钮可编辑用户信息或调整权限，支持批量导出。",
                        "columns": ["UID", "用户名", "部门", "角色", "积分", "状态", "最后登录", "操作"],
                        "rows": [
                            ["1001", "WangDali", "研发部", "高级工程师", "5,200", "<span class='badge badge-success'>正常</span>", "2023-11-01 09:30", "查看 | 编辑"],
                            ["1002", "LiSisi", "市场部", "市场经理", "3,450", "<span class='badge badge-success'>正常</span>", "2023-11-01 09:35", "查看 | 编辑"],
                            ["1003", "ZhangSan", "运营部", "内容专员", "1,200", "<span class='badge badge-warning'>休假</span>", "2023-10-30 18:00", "查看 | 编辑"],
                            ["1004", "ZhaoLiu", "财务部", "会计", "8,900", "<span class='badge badge-success'>正常</span>", "2023-11-01 08:50", "查看 | 编辑"],
                            ["1005", "Admin", "系统部", "超级管理员", "99,999", "<span class='badge badge-info'>核心</span>", "2023-11-01 10:00", "日志 | 权限"],
                            ["1006", "Guest01", "外部", "访客", "0", "<span class='badge badge-secondary'>临时</span>", "2023-11-01 11:20", "查看 | 封禁"],
                            ["1007", "DevTest", "研发部", "测试员", "150", "<span class='badge badge-danger'>锁定</span>", "2023-10-25 14:30", "解锁 | 删除"],
                            ["1008", "HR_Manager", "人事部", "HRBP", "4,100", "<span class='badge badge-success'>正常</span>", "2023-11-01 09:05", "查看 | 编辑"]
                        ]
                    }
                ]
            }
        }
        
        return [monitor_page, user_page]

    def generate_full_plan(
        self,
        project_name: str,
        genome_overrides: Dict[str, str] = None,
        code_generation_overrides: Dict[str, Any] = None,
        project_charter: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        执行完整的主从式生成流
        """
        project_output_dir = BASE_DIR / "output" / project_name
        project_output_dir.mkdir(parents=True, exist_ok=True)
        intermediate_file = project_output_dir / "intermediate_plan.json"

        print(f"\n{'='*60}")
        print(f"启动 Master-Detail 生成流程: {project_name}")
        print(f"{'='*60}\n")

        normalized_charter = normalize_project_charter(project_charter or {}, project_name=project_name)
        charter_errors = validate_project_charter(normalized_charter)
        if charter_errors:
            raise ValueError(
                "项目章程校验失败，未满足立项门禁: " + "；".join(charter_errors)
            )

        # 1. Master Phase
        master_plan = self.plan_total_project(
            project_name,
            genome_overrides=genome_overrides,
            project_charter=normalized_charter,
        )

        # 初始化最终结构
        final_plan = {
            "project_name": master_plan.get("project_name", project_name),
            "pipeline_protocol_version": PIPELINE_PROTOCOL_VERSION,
            "theme_color": master_plan.get("theme_color", "#1976D2"),
            "admin_name": random.choice(ADMIN_NAMES),
            "project_charter": normalized_charter,
            "project_intro": master_plan.get("project_intro", {}),       # Task 4: 传递简介
            "copyright_fields": master_plan.get("copyright_fields", {}), # Task 4: 传递软著字段
            "code_blueprint": master_plan.get("code_blueprint", {}) if isinstance(master_plan.get("code_blueprint", {}), dict) else {},
            "genome": master_plan.get("genome", {}),                     # [新增] 传递项目基因图谱
            "novelty_constraints": master_plan.get("novelty_constraints", {}),
            "code_generation_config": self._build_code_generation_config(code_generation_overrides),
            "menu_list": master_plan.get("menu_list", []),
            "pages": {}
        }

        # 记录项目基因图谱到日志
        genome = final_plan.get("genome", {})
        logger.info(f"项目基因图谱: 语言={genome.get('target_language', 'N/A')}, "
                   f"UI框架={genome.get('ui_framework', 'N/A')}, "
                   f"布局={genome.get('layout_mode', 'N/A')}, "
                   f"配色={genome.get('color_scheme', {}).get('name', 'N/A')}, "
                   f"风格={genome.get('narrative_style', 'N/A')}")

        # 立即存盘 (Checkpoint 1)
        self._save_intermediate(final_plan, intermediate_file)
        
        # 2. Detail Phase
        total_pages = len(final_plan["menu_list"])
        
        worker_count = min(self.max_page_workers, max(1, total_pages))
        page_tasks = []
        for idx, menu_item in enumerate(final_plan["menu_list"]):
            page_id = menu_item.get("page_id", f"page_{idx+1}")
            menu_item["url"] = f"{page_id}.html"  # 补全 URL
            page_tasks.append((idx, page_id, menu_item))

        failed_pages = 0
        current_run_id = llm_budget.current_run_id()
        current_stage = llm_budget.current_stage()

        def plan_single_page_with_budget(project: str, menu: Dict[str, Any]) -> Dict[str, Any]:
            # ThreadPoolExecutor 线程不会继承 thread-local，显式透传预算上下文
            with llm_budget.run_scope(current_run_id):
                with llm_budget.stage_scope(current_stage):
                    return self.plan_single_page(project, menu)

        if worker_count == 1:
            for idx, page_id, menu_item in page_tasks:
                print(f"Processing Page {idx+1}/{total_pages}: {menu_item.get('title')}...")
                try:
                    page_detail = plan_single_page_with_budget(project_name, menu_item)
                    final_plan["pages"][page_id] = page_detail
                    self._save_intermediate(final_plan, intermediate_file)
                    # 增加轻量抖动，降低网关节律性限流
                    time.sleep(0.15 + random.random() * 0.35)
                except Exception as e:
                    failed_pages += 1
                    logger.error(f"Error generating page {page_id}: {e}")
                    final_plan["pages"][page_id] = {
                        "page_title": menu_item.get("title", "Error Page"),
                        "charts": []
                    }
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {
                    executor.submit(plan_single_page_with_budget, project_name, menu_item): (idx, page_id, menu_item)
                    for idx, page_id, menu_item in page_tasks
                }

                for future in as_completed(future_map):
                    idx, page_id, menu_item = future_map[future]
                    print(f"Processing Page {idx+1}/{total_pages}: {menu_item.get('title')}...")
                    try:
                        page_detail = future.result()
                        final_plan["pages"][page_id] = page_detail
                        self._save_intermediate(final_plan, intermediate_file)
                    except Exception as e:
                        failed_pages += 1
                        logger.error(f"Error generating page {page_id}: {e}")
                        final_plan["pages"][page_id] = {
                            "page_title": menu_item.get("title", "Error Page"),
                            "charts": []
                        }

        # 质量闸门：失败比例过高直接中断，避免“看似成功实际不可用”
        if total_pages > 0:
            failure_ratio = failed_pages / total_pages
            if failure_ratio > self.max_page_failure_ratio:
                raise RuntimeError(
                    f"页面详情生成失败率过高: {failed_pages}/{total_pages} ({failure_ratio:.0%})，已触发质量闸门中止流程"
                )

        # 3. Append Admin Pages (System Monitor + User Management)
        print("Finalizing: 追加后台管理页面 (监控+用户管理)...")
        admin_pages = self._get_admin_pages(project_name)
        
        for page in admin_pages:
            # 添加菜单
            final_plan["menu_list"].append({
                "title": page["title"],
                "icon": page["icon"],
                "url": f"{page['page_id']}.html",
                "page_id": page["page_id"]
            })
            # 添加页面数据
            final_plan["pages"][page["page_id"]] = page["data"]

        # 4. 构建操作流程画像（供说明书与审计侧使用）
        final_plan["operation_flow_profile"] = self._build_operation_flow_profile(final_plan)

        # 5. 规格先行：生成可执行规格，供 code/document 统一消费
        final_plan["executable_spec"] = build_executable_spec(final_plan, normalized_charter)

        # 6. 生成 UI 技能蓝图与截图契约（供 html/screenshot/claim-evidence 复用）
        try:
            ui_artifacts = build_ui_skill_artifacts(
                project_name=project_name,
                plan=final_plan,
                project_dir=project_output_dir,
                force=True,
            )
            final_plan["ui_skill_profile"] = ui_artifacts.get("profile") or {}
            final_plan["ui_blueprint"] = ui_artifacts.get("blueprint") or {}
            final_plan["screenshot_contract"] = ui_artifacts.get("contract") or {}
            logger.info(
                "UI 技能编排完成: profile=%s, blueprint=%s, contract=%s",
                ui_artifacts.get("profile_path"),
                ui_artifacts.get("blueprint_path"),
                ui_artifacts.get("contract_path"),
            )
        except Exception as e:
            logger.warning(f"UI 技能编排失败，继续执行默认链路: {e}")
        
        # 7. Final Save
        self._save_intermediate(final_plan, intermediate_file) # 更新中间文件为最终态
        
        print(f"\n{'='*60}")
        print(f"项目规划生成完成!")
        print(f"Total Pages: {len(final_plan['pages'])}")
        print(f"{'='*60}\n")
        
        return final_plan

    def _save_intermediate(self, data: Dict, target_file: Path):
        """保存中间状态"""
        with self._save_lock:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def _save_copyright_helper_txt(self, data: Dict, output_path: Path):
        """
        保存软著填写辅助文件（中文字段名的txt）
        方便非技术人员直接复制到软著平台填写
        """
        try:
            copyright_fields = data.get('copyright_fields', {})
            project_intro = data.get('project_intro', {})

            # 构建txt内容
            txt_content = f"""{'='*60}
软件著作权登记申请 - 填写辅助文档
{'='*60}

项目名称: {data.get('project_name', '未设置')}

{'='*60}
一、基本信息
{'='*60}

软件全称:
{data.get('project_name', '')}

软件简称:
（留空或根据需要填写）

版本号:
V1.0

{'='*60}
二、开发信息
{'='*60}

软件分类:
应用软件

开发完成日期:
（填写当前日期，格式：2026-01-12）

{'='*60}
三、运行环境与技术信息
{'='*60}

开发的硬件环境:
Windows系统的笔记本电脑

运行的硬件环境:
服务器配置： 4核CPU、8GB内存、500GB存储空间以上 终端设备：PC端和移动设备

开发该软件的操作系统:
Windows 11

软件开发环境/开发工具:
PyCharm，Visual Studio Code

该软件的运行平台/操作系统:
Windows Server 2016及以上，Linux各发行版

软件运行支撑环境/支持软件:
数据库：MySQL 5.7或以上。 编程环境：Java、Python、JavaScript

编程语言:
☑ Python  ☑ HTML  ☑ Java  ☑ PL/SQL

源程序量（行）:
{random.randint(3000, 5000)}

{'='*60}
四、软件功能与特点
{'='*60}

开发目的:
{copyright_fields.get('development_purpose', '未填写')}

软件面向的领域/行业:
{self._format_industry_list(copyright_fields.get('industry', '未填写'))}

软件的主要功能（100字以上）:
{copyright_fields.get('main_functions', '未填写')}

软件的技术特点（100字左右）:
{copyright_fields.get('technical_features', '未填写')}

软件的技术特点分类（从15个选项中选择1个）:
{copyright_fields.get('tech_category', '未填写')}

该分类下的具体技术特点描述:
{copyright_fields.get('tech_detail', '未填写')}

{'='*60}
五、系统简介（用于说明书）
{'='*60}

行业背景:
{project_intro.get('background', '未填写')}

系统概述:
{project_intro.get('overview', '未填写')}

目标用户群体:
{self._format_list(project_intro.get('target_users', []))}

主要功能点:
{self._format_list(project_intro.get('main_features', []))}

技术优势:
{project_intro.get('advantages', '未填写')}

{'='*60}
六、文件上传
{'='*60}

需要上传的文件:
1. 程序鉴别材料（源代码PDF）: {data.get('project_name', '')}_源代码.pdf
2. 文档鉴别材料（操作说明书PDF）: {data.get('project_name', '')}_操作说明书.pdf

{'='*60}
注意事项
{'='*60}

1. 请按照软著平台的实际字段名称，将上述内容复制粘贴到对应位置
2. 日期字段请填写实际的开发完成日期
3. 技术特点分类必须从以下14个选项中选择1个：
   - APP游戏软件、教育软件、金融软件、地理信息软件
   - 云计算软件、信息安全软件、大数据软件、人工智能软件、VR软件
   - 5G软件、小程序、物联网软件、智慧城市软件、其他

{'='*60}
文档生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*60}
"""

            # 保存txt文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(txt_content)

            logger.info(f"✓ 已生成软著填写辅助文档: {output_path}")

        except Exception as e:
            logger.error(f"生成软著辅助文档失败: {e}")

    def _format_list(self, items: list) -> str:
        """将数组格式化为带序号的列表"""
        if not items:
            return "（未设置）"
        # 修复：确保 items 是列表，如果不仅是一个长字符串
        if isinstance(items, str):
            return items

        # 过滤掉单字符的脏数据 (例如 ['H', 'e', 'l', 'l', 'o'] 这种情况)
        if len(items) > 10 and all(len(str(x)) == 1 for x in items):
            # 这是一个被错误拆分的字符串，尝试合并
            return "".join(items)

        # 正常列表格式化
        return '\n'.join([f"{i+1}. {item}" for i, item in enumerate(items)])

    def _format_industry_list(self, industry: str) -> str:
        """将行业字段格式化为带序号的列表（如果是字符串则保持原样）"""
        if isinstance(industry, list):
            return self._format_list(industry)
        elif isinstance(industry, str) and industry != '未填写':
            return industry
        else:
            return "（未设置）"


# 兼容旧代码的顶层函数
def generate_project_plan(
    project_name: str,
    api_key: str = None,
    genome_overrides: Dict[str, str] = None,
    code_generation_overrides: Dict[str, Any] = None,
    project_charter: Dict[str, Any] = None,
) -> Dict[str, Any]:
    planner = ProjectPlanner(api_key)
    return planner.generate_full_plan(
        project_name,
        genome_overrides,
        code_generation_overrides,
        project_charter,
    )
