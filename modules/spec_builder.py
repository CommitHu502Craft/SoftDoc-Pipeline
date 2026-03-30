import hashlib
import random
import re
from typing import Any, Dict, List, Optional


class SpecBuilder:
    """
    Build rewrite constraints and semantic comment material.

    设计目的（给后续维护/AI）：
    1) 把“项目语义”集中到一个地方，避免在多个模块重复拼接提示词。
    2) 产出稳定但不完全一致的注释/约束文本，降低模板化痕迹。
    3) 对 plan 结构做容错，保证不同入口生成的 plan 都能被消费。
    """

    ROLE_KEYWORDS = {
        "controller": ("controller", "router", "handler", "endpoint", "api"),
        "service": ("service", "biz", "logic"),
        "model": ("model", "entity", "schema", "domain", "dto", "vo"),
        "repository": ("repo", "repository", "dao", "persistence"),
        "config": ("config", "setting", "env"),
        "utility": ("util", "helper", "tool", "common"),
    }

    ARCHITECTURE_FAMILY_MAP = {
        "mvc": "Layered",
        "layered": "Layered",
        "microservices": "DDD-lite",
        "event-driven": "CQRS-lite",
    }

    API_CONTRACT_VARIANTS = [
        {
            "name": "resource-page",
            "endpoint_style": "resource",
            "pagination": "page+size",
            "filter_style": "query_map",
            "error_model": "code+message",
            "idempotency": "header:Idempotency-Key",
        },
        {
            "name": "noun-verb-offset",
            "endpoint_style": "noun-verb",
            "pagination": "offset+limit",
            "filter_style": "explicit_fields",
            "error_model": "error+detail",
            "idempotency": "body:request_id",
        },
        {
            "name": "resource-cursor",
            "endpoint_style": "resource",
            "pagination": "cursor+limit",
            "filter_style": "query_map",
            "error_model": "status+code+message",
            "idempotency": "auto_upsert_key",
        },
    ]

    DATA_MODEL_VARIANTS = [
        {
            "name": "audit-heavy",
            "entity_split": "aggregate+snapshot",
            "relation_direction": "parent_to_children",
            "index_strategy": "composite(time,status)",
            "audit_policy": "created_by+updated_by+version",
        },
        {
            "name": "query-optimized",
            "entity_split": "read_write_split",
            "relation_direction": "bidirectional",
            "index_strategy": "covering_indexes",
            "audit_policy": "created_at+updated_at",
        },
        {
            "name": "compact",
            "entity_split": "single_entity_with_extensions",
            "relation_direction": "child_to_parent",
            "index_strategy": "minimal_hot_indexes",
            "audit_policy": "created_at_only",
        },
    ]

    def __init__(self, plan: Dict[str, Any]) -> None:
        self.plan = plan or {}
        self.project_name = self.plan.get("project_name", "")
        self.genome = self.plan.get("genome", {}) or {}
        self.primary_entity = self._pick_primary_entity(self.plan)
        self.lexicon = self._build_lexicon(self.plan)
        self.project_spec = self._build_project_spec(self.plan)

    @staticmethod
    def _pick_primary_entity(plan: Dict[str, Any]) -> str:
        blueprint = (plan or {}).get("code_blueprint", {})
        entities = blueprint.get("entities") or []
        if entities:
            return str(entities[0])
        return "BusinessItem"

    def _build_lexicon(self, plan: Dict[str, Any]) -> List[str]:
        seeds: List[str] = []

        project_name = str(plan.get("project_name", ""))
        seeds.extend(self._extract_terms(project_name))

        blueprint = plan.get("code_blueprint", {}) or {}
        for entity in blueprint.get("entities", []) or []:
            seeds.extend(self._extract_terms(str(entity)))

        # 注意：pages 在不同流水线入口可能是 dict 或 list。
        # - dict: {"page_1": {...}, "page_2": {...}}（当前主流）
        # - list: [{...}, {...}]（历史格式/测试数据）
        # 统一迭代可以避免初始化阶段因 page.get 报错而中断代码生成。
        for page in self._iter_pages(plan):
            seeds.extend(self._extract_terms(str(page.get("title", ""))))
            seeds.extend(self._extract_terms(str(page.get("name", ""))))

        # Keep unique while preserving order.
        result: List[str] = []
        seen = set()
        for token in seeds:
            low = token.lower()
            if low in seen:
                continue
            seen.add(low)
            result.append(token)

        if not result:
            result = ["workflow", "record", "audit", "snapshot", "pipeline"]

        return result[:20]

    def _build_project_spec(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建“可执行 DSL 规格”。

        目标不是替代完整建模工具，而是把后续代码生成必须遵守的约束收敛成一份稳定结构：
        - 实体集合
        - 状态机
        - 权限矩阵
        - API 合约变体
        - 数据模型变体
        """
        blueprint = (plan or {}).get("code_blueprint", {}) or {}
        entities = [str(x).strip() for x in (blueprint.get("entities") or []) if str(x).strip()]
        if not entities:
            entities = [self.primary_entity]

        menu_titles: List[str] = []
        for page in self._iter_pages(plan):
            title = str(page.get("title", "") or page.get("page_title", "")).strip()
            if title:
                menu_titles.append(title)
        if not menu_titles:
            menu_titles = ["数据录入", "流程审批", "统计分析"]

        spec = {
            "version": "spec-v1",
            "architecture_family": self._pick_architecture_family(),
            "entities": entities,
            "workflow_steps": menu_titles[:8],
            "state_machine": self._build_state_machine(entities),
            "permission_matrix": self._build_permission_matrix(entities),
            "api_contract": self._pick_api_contract_variant(),
            "data_model": self._pick_data_model_variant(),
            "controllers": blueprint.get("controllers", []) or [],
        }
        return spec

    def _pick_architecture_family(self) -> str:
        declared = str(self.genome.get("architecture_pattern", "")).lower().strip()
        if declared in self.ARCHITECTURE_FAMILY_MAP:
            return self.ARCHITECTURE_FAMILY_MAP[declared]
        rng = self._rng_for("arch-family")
        return rng.choice(["Layered", "DDD-lite", "CQRS-lite", "Service+Repository"])

    def _pick_api_contract_variant(self) -> Dict[str, str]:
        rng = self._rng_for("api-contract")
        picked = dict(rng.choice(self.API_CONTRACT_VARIANTS))
        return picked

    def _pick_data_model_variant(self) -> Dict[str, str]:
        rng = self._rng_for("data-model")
        picked = dict(rng.choice(self.DATA_MODEL_VARIANTS))
        return picked

    def _build_state_machine(self, entities: List[str]) -> Dict[str, List[str]]:
        rng = self._rng_for("state-machine")
        templates = [
            ["draft", "pending", "approved", "archived"],
            ["created", "validated", "processing", "done"],
            ["new", "reviewing", "published", "closed"],
        ]
        state_map: Dict[str, List[str]] = {}
        for entity in entities:
            states = list(rng.choice(templates))
            # 保证主实体状态机包含“审核/发布”语义，方便文档和代码一致。
            if entity == self.primary_entity and "approved" not in states:
                states[-2] = "approved"
            state_map[entity] = states
        return state_map

    def _build_permission_matrix(self, entities: List[str]) -> Dict[str, Dict[str, List[str]]]:
        matrix: Dict[str, Dict[str, List[str]]] = {}
        roles = ["owner", "admin", "operator", "auditor", "viewer"]
        for entity in entities:
            matrix[entity] = {
                "owner": ["create", "read", "update", "delete", "approve", "export"],
                "admin": ["create", "read", "update", "approve", "export"],
                "operator": ["create", "read", "update", "submit"],
                "auditor": ["read", "approve", "export"],
                "viewer": ["read"],
            }
            # 让权限矩阵在实体维度有轻微变化，降低跨项目固定模板痕迹。
            if len(entity) % 2 == 1:
                matrix[entity]["operator"] = ["create", "read", "update", "submit", "export"]
        for role in roles:
            _ = role  # 保留 roles 的显式语义，便于后续扩展。
        return matrix

    def get_project_spec(self) -> Dict[str, Any]:
        return dict(self.project_spec)

    def build_spec_first_directive(self, file_path: str, language: str) -> str:
        role = self.infer_file_role(file_path)
        spec = self.project_spec
        contract = spec.get("api_contract", {})
        model_variant = spec.get("data_model", {})
        states = spec.get("state_machine", {}).get(self.primary_entity, [])
        workflow_steps = spec.get("workflow_steps", [])[:4]

        lines = [
            "Spec-first 约束:",
            f"- 目标语言: {language}",
            f"- 架构族: {spec.get('architecture_family', 'Layered')}",
            f"- 文件职责: {role}",
            f"- 核心实体: {', '.join(spec.get('entities', [])[:4])}",
            f"- 主流程节点: {' -> '.join(workflow_steps) if workflow_steps else 'ingest -> review -> publish'}",
            f"- 主实体状态机: {' -> '.join(states) if states else 'draft -> pending -> approved'}",
            f"- API 合约: endpoint={contract.get('endpoint_style', 'resource')}, page={contract.get('pagination', 'page+size')}, error={contract.get('error_model', 'code+message')}, idem={contract.get('idempotency', 'header:Idempotency-Key')}",
            f"- 数据模型变体: split={model_variant.get('entity_split', 'aggregate')}, relation={model_variant.get('relation_direction', 'parent_to_children')}, index={model_variant.get('index_strategy', 'composite')}, audit={model_variant.get('audit_policy', 'created_at+updated_at')}",
            "- 代码必须体现流程、状态、权限，不要只做字段改名。",
        ]
        return "\n".join(lines)

    @staticmethod
    def _iter_pages(plan: Dict[str, Any]):
        """
        统一返回页面对象迭代器，屏蔽 plan 数据结构差异。

        返回值只包含 dict 页面节点；非 dict 数据会被忽略，
        目的是保证后续 page.get(...) 调用稳定。
        """
        pages = (plan or {}).get("pages", {})
        if isinstance(pages, dict):
            for page in pages.values():
                if isinstance(page, dict):
                    yield page
            return
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, dict):
                    yield page

    @staticmethod
    def _extract_terms(text: str) -> List[str]:
        if not text:
            return []
        # English-ish terms.
        ascii_terms = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text)
        # Chinese terms (2+ chars) to keep domain semantics.
        zh_terms = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        terms = [t.strip("_-") for t in ascii_terms + zh_terms]
        return [t for t in terms if t]

    def infer_file_role(self, file_path: str) -> str:
        path_lower = (file_path or "").replace("\\", "/").lower()
        for role, keywords in self.ROLE_KEYWORDS.items():
            if any(k in path_lower for k in keywords):
                return role
        return "general"

    def _rng_for(self, key: str) -> random.Random:
        digest = hashlib.md5(f"{self.project_name}:{key}".encode("utf-8")).hexdigest()
        return random.Random(int(digest[:8], 16))

    def semantic_comments(self, file_path: str, language: str, count: int = 6) -> List[str]:
        role = self.infer_file_role(file_path)
        rng = self._rng_for(f"comment:{file_path}:{language}")

        picked_terms = list(self.lexicon)
        rng.shuffle(picked_terms)
        picked_terms = picked_terms[: max(3, min(8, len(picked_terms)))]

        spec = self.project_spec
        states = spec.get("state_machine", {}).get(self.primary_entity, [])
        api_variant = spec.get("api_contract", {}).get("name", "resource-page")
        model_variant = spec.get("data_model", {}).get("name", "audit-heavy")
        workflow_steps = spec.get("workflow_steps", [])

        templates = [
            f"{self.project_name} - {role} workflow branch",
            f"{self.primary_entity} domain validation checkpoint",
            f"semantic guard for {picked_terms[0] if picked_terms else 'core process'}",
            f"incremental state sync around {picked_terms[-1] if picked_terms else 'pipeline'}",
            "cross-stage payload normalization hook",
            "deferred consistency reconciliation marker",
            "risk isolation for asynchronous operation",
            "post-action index refresh checkpoint",
            f"api contract variant: {api_variant}",
            f"data model variant: {model_variant}",
            f"state machine guard: {' -> '.join(states[:3]) if states else 'draft -> pending -> approved'}",
            f"workflow checkpoint: {' -> '.join(workflow_steps[:3]) if workflow_steps else 'ingest -> review -> publish'}",
        ]

        rng.shuffle(templates)
        result: List[str] = []
        seen = set()
        for line in templates:
            key = line.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            result.append(line)
            if len(result) >= max(2, count):
                break
        return result

    def business_consistency_score(self, code: str, file_path: str, language: str) -> float:
        """
        粗粒度业务一致性评分（0~1）。
        用于多候选筛选时避免“新颖但跑偏业务语义”的候选被选中。
        """
        if not code.strip():
            return 0.0
        tokens = set(t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code))
        role = self.infer_file_role(file_path)
        spec = self.project_spec

        required_terms: List[str] = []
        for entity in spec.get("entities", [])[:4]:
            required_terms.extend(self._extract_terms(entity))
        required_terms.extend(self.lexicon[:6])
        required_terms.extend(self._extract_terms(spec.get("architecture_family", "")))

        contract = spec.get("api_contract", {})
        required_terms.extend(self._extract_terms(contract.get("endpoint_style", "")))
        required_terms.extend(self._extract_terms(contract.get("pagination", "")))
        required_terms.extend(self._extract_terms(contract.get("error_model", "")))

        if role == "controller":
            required_terms.extend(["api", "request", "response", "status"])
        elif role == "service":
            required_terms.extend(["service", "workflow", "validate", "state"])
        elif role in {"model", "repository"}:
            required_terms.extend(["entity", "schema", "created", "updated", "version"])

        norm_terms = [x.lower() for x in required_terms if x]
        if not norm_terms:
            return 0.5

        hits = 0
        for term in norm_terms:
            if term in tokens:
                hits += 1
        ratio = hits / len(set(norm_terms))
        return max(0.0, min(1.0, round(ratio, 4)))

    def build_rewrite_directive(
        self,
        file_path: str,
        language: str,
        attempt: int = 1,
        novelty_feedback: Optional[Dict[str, Any]] = None,
        forbidden_feedback: Optional[Dict[str, Any]] = None,
    ) -> str:
        role = self.infer_file_role(file_path)
        terms = ", ".join(self.lexicon[:6])

        lines = [
            "额外重写约束:",
            self.build_spec_first_directive(file_path, language),
            f"- 文件职责: {role}",
            f"- 语义词汇优先使用: {terms}",
            f"- 改写轮次: {attempt}",
            "- 避免沿用原始代码中的连续长片段和固定注释句式",
            "- 优先调整函数拆分方式、参数命名和异常处理路径",
            "- 业务注释要围绕本项目语义，不要使用模板化雷同表达",
        ]

        if novelty_feedback:
            lines.append(
                f"- 上轮新颖度: {novelty_feedback.get('novelty_score', 0)} / 相似度: {novelty_feedback.get('max_similarity', 0)}"
            )
        if forbidden_feedback and forbidden_feedback.get("samples"):
            sample = forbidden_feedback["samples"][0]
            lines.append(f"- 避免再次出现相似片段: {sample[:120]}")

        return "\n".join(lines)

