"""
页面内容生成器 (Page Content Generator)
V2.1 核心组件 (Phase 2)：生成具体的业务内容片段、图表配置和模拟数据
"""
import json
import logging
import random
import hashlib
from typing import Dict, Any, List, Tuple
from core.deepseek_client import DeepSeekClient
from core.llm_budget import llm_budget
from modules.industry_adapter import get_adapter

logger = logging.getLogger(__name__)

class PageContentGenerator:
    """
    负责生成 {{ main_content_area }} 的具体内容
    特点：
    1. 基于 JSON 输出，不生成完整 HTML 页面
    2. 强业务上下文注入 (Business Context Injection)
    3. 风格化布局映射 (Style Mapping)
    """
    # 系统原型库：让页面更接近“真实业务系统页面”而非通用展示页。
    SYSTEM_ARCHETYPES: Dict[str, Dict[str, Any]] = {
        "relationship": {
            "label": "关系管理系统",
            "keywords": ["关系", "客户", "线索", "联系人", "伙伴", "跟进", "档案", "协同", "crm"],
            "chart_range": (1, 2),
            "table_range": (2, 3),
            "preferred_chart_types": ["funnel", "bar", "line", "pie", "sankey", "treemap"],
            "layout_variants": [
                "filters-top + list-left + detail-right + relation-chart-bottom",
                "kpi-top + customer-list-main + followup-timeline-side + trend-chart-bottom",
                "search-toolbar + relation-overview + conversion-funnel + interaction-table",
            ],
            "must_sections": [
                "对象检索与筛选区（关键词/负责人/状态/时间范围）",
                "主档列表区（支持状态标签与优先级）",
                "详情面板或侧边抽屉（联系人、最近跟进、关联记录）",
                "关系演进或转化分析区（图表）",
            ],
            "table_fields": ["编号", "名称", "负责人", "状态", "最近跟进时间", "优先级"],
            "business_data_keys": ["summary", "filters", "records", "relations", "followups"],
        },
        "workflow": {
            "label": "工单/流程系统",
            "keywords": ["工单", "流程", "审批", "发布", "派单", "任务", "待办", "归档"],
            "chart_range": (1, 3),
            "table_range": (2, 3),
            "preferred_chart_types": ["bar", "line", "pie", "heatmap", "gauge"],
            "layout_variants": [
                "filters-top + queue-table-main + processing-metrics-side",
                "kpi-top + sla-chart + backlog-table + approval-timeline",
                "toolbar + task-kanban-like-block + detail-table + trend-chart",
            ],
            "must_sections": [
                "工单筛选区（单号/状态/优先级/处理人）",
                "待处理列表与SLA字段",
                "节点状态或审批流状态展示",
                "异常/超时统计图表",
            ],
            "table_fields": ["工单号", "主题", "优先级", "当前节点", "处理人", "SLA剩余"],
            "business_data_keys": ["summary", "filters", "tickets", "sla", "workflow_nodes"],
        },
        "knowledge": {
            "label": "检索与知识库系统",
            "keywords": ["文献", "知识库", "检索", "资料", "标签", "索引", "语料", "论文"],
            "chart_range": (1, 2),
            "table_range": (2, 3),
            "preferred_chart_types": ["bar", "line", "treemap", "pie", "scatter"],
            "layout_variants": [
                "search-top + result-list-main + doc-preview-side + index-chart-bottom",
                "filters-top + retrieval-metrics + citation-table + tag-distribution-chart",
                "query-panel + result-table + version-compare + quality-metrics",
            ],
            "must_sections": [
                "检索输入区（关键词/标签/时间/来源）",
                "结果列表区（相关度、版本、来源）",
                "文档预览或详情区",
                "索引质量/命中率图表",
            ],
            "table_fields": ["文档ID", "标题", "相关度", "来源", "版本", "更新时间"],
            "business_data_keys": ["summary", "filters", "documents", "index_stats", "query_log"],
        },
        "operations": {
            "label": "运行监控系统",
            "keywords": ["监控", "运行", "告警", "设备", "吞吐", "性能", "容量", "巡检"],
            "chart_range": (3, 4),
            "table_range": (1, 2),
            "preferred_chart_types": ["line", "bar", "heatmap", "gauge", "scatter"],
            "layout_variants": [
                "kpi-top + multi-chart-grid + alert-table-bottom",
                "compact-header + realtime-metrics + anomaly-heatmap + alarm-list",
                "status-cards + trend-charts + capacity-chart + alert-stream",
            ],
            "must_sections": [
                "运行指标卡（可用率/延迟/告警数）",
                "多维趋势图与异常热力图",
                "告警明细表与处理状态",
            ],
            "table_fields": ["告警ID", "资源", "级别", "状态", "触发时间", "负责人"],
            "business_data_keys": ["summary", "metrics", "alerts", "capacity", "anomalies"],
        },
        "reporting": {
            "label": "分析报表系统",
            "keywords": ["报告", "分析", "报表", "统计", "版本管理", "比对"],
            "chart_range": (2, 4),
            "table_range": (1, 2),
            "preferred_chart_types": ["bar", "line", "pie", "scatter", "heatmap"],
            "layout_variants": [
                "filters-top + metrics-summary + chart-grid + report-table",
                "kpi-strip + trend-and-distribution + version-compare-table",
                "query-panel + insight-cards + chart-area + detail-list",
            ],
            "must_sections": [
                "分析条件筛选区（周期/维度/口径）",
                "核心指标总览区",
                "趋势/对比/分布图表区",
                "报表列表与版本信息区",
            ],
            "table_fields": ["报告ID", "主题", "版本", "负责人", "更新时间", "状态"],
            "business_data_keys": ["summary", "filters", "reports", "versions", "insights"],
        },
        "generic": {
            "label": "通用管理系统",
            "keywords": [],
            "chart_range": (2, 4),
            "table_range": (1, 2),
            "preferred_chart_types": ["bar", "line", "pie", "scatter", "heatmap"],
            "layout_variants": [
                "metrics-top + charts-middle + table-bottom",
                "filters-top + 2-column-chart + full-width-table",
                "left-kpi-right-kpi + mixed charts + operation table",
                "compact header + 2x2 chart grid + detail table",
            ],
            "must_sections": [
                "筛选区",
                "指标卡区",
                "图表区",
                "明细表区",
            ],
            "table_fields": ["编号", "名称", "负责人", "状态", "更新时间"],
            "business_data_keys": ["summary", "filters", "records"],
        },
    }

    def __init__(self, api_key: str = None):
        self.client = DeepSeekClient(api_key=api_key)
        # 会话级随机盐：保证同一轮任务的“随机增强”可控且不完全重复。
        self.session_nonce = random.getrandbits(31)
        self._used_layout_signatures = set()

    def generate_content(
        self,
        genome: Dict[str, Any],
        page_info: Dict[str, Any],
        page_blueprint: Dict[str, Any] = None,
        style_context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        生成页面内容片段

        Args:
            genome: 项目基因 (包含 visual_style, business_context, ui_framework)
            page_info: 页面信息 (title, description)

        Returns:
            Dict: {
                "html_fragment": str,
                "charts_config": list,
                "business_data": dict
            }
        """
        # 1. 提取上下文
        visual_style = genome.get("visual_style", "Enterprise")
        ui_framework = genome.get("ui_framework", "Bootstrap")
        business_context = genome.get("business_context", [])
        page_title = page_info.get("title", "未命名页面")
        project_name = genome.get("name") or genome.get("project_name", "")

        # 获取行业 Context Prompt
        adapter = get_adapter()
        industry_key = adapter.detect_industry(project_name)
        industry_prompt = adapter.get_industry_prompt(industry_key)

        page_rng = self._build_page_rng(project_name, industry_key, page_info)
        budget_ok, budget_reason = self._consume_blueprint_block_budget(page_blueprint or {})
        if not budget_ok:
            logger.warning("页面 %s 触发 block 预算门禁，改用蓝图回退: %s", page_title, budget_reason)
            fallback = self._get_fallback_content(genome, page_info, page_blueprint=page_blueprint or {})
            business_data = fallback.setdefault("business_data", {})
            if isinstance(business_data, dict):
                business_data["llm_budget_block_blocked"] = True
                business_data["llm_budget_block_reason"] = budget_reason
            return fallback

        # 2. 构造 Prompt
        prompt = self._construct_prompt(
            visual_style,
            ui_framework,
            business_context,
            page_title,
            industry_prompt,
            project_name=project_name,
            page_id=str(page_info.get("page_id", page_info.get("id", ""))),
            industry_key=industry_key,
            rng=page_rng,
            page_blueprint=page_blueprint or {},
            style_context=style_context or {},
        )

        # 3. 调用 LLM (使用 generate_json 模式)
        try:
            # 复用 DeepSeekClient 的 generate_json 方法，它已经处理了重试和清洗
            result = self.client.generate_json(prompt)

            # 4. 后处理校验
            if self._validate_content(result, page_blueprint=page_blueprint or {}):
                return result
            else:
                logger.warning(f"页面内容生成校验失败: {page_title}")
                return self._get_fallback_content(genome, page_info, page_blueprint=page_blueprint or {})

        except Exception as e:
            logger.error(f"页面内容生成出错: {e}")
            return self._get_fallback_content(genome, page_info, page_blueprint=page_blueprint or {})

    def _consume_blueprint_block_budget(self, page_blueprint: Dict[str, Any]) -> Tuple[bool, str]:
        if not isinstance(page_blueprint, dict):
            return True, ""
        blocks = page_blueprint.get("functional_blocks") or []
        if not isinstance(blocks, list) or not blocks:
            return True, ""

        stage_name = llm_budget.current_stage()
        for idx, block in enumerate(blocks, start=1):
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("block_id") or f"block_{idx}").strip() or f"block_{idx}"
            with llm_budget.block_scope(block_id):
                ok, reason = llm_budget.consume_block_call(block_id=block_id, stage=stage_name)
            if not ok:
                return False, reason
        return True, ""

    def _build_page_rng(self, project_name: str, industry_key: str, page_info: Dict[str, Any]) -> random.Random:
        page_id = str(page_info.get("page_id", page_info.get("id", "")))
        page_title = str(page_info.get("title", ""))
        seed_src = f"{project_name}|{industry_key}|{page_id}|{page_title}|{self.session_nonce}"
        digest = hashlib.md5(seed_src.encode("utf-8")).hexdigest()
        return random.Random(int(digest[:8], 16))

    def _infer_system_archetype(self, project_name: str, title: str, context: List[str]) -> Tuple[str, Dict[str, Any]]:
        """根据项目名/页面名/上下文推断页面所属系统原型。"""
        project_title_text = f"{project_name} {title}".lower()
        context_text = " ".join([str(x) for x in context]).lower()

        best_key = "generic"
        best_score = 0
        for key, meta in self.SYSTEM_ARCHETYPES.items():
            if key == "generic":
                continue

            score = 0
            for kw in meta.get("keywords", []):
                kw_l = str(kw).lower()
                if kw_l in project_title_text:
                    score += 3
                elif kw_l in context_text:
                    score += 1

            if score > best_score:
                best_score = score
                best_key = key

        return best_key, self.SYSTEM_ARCHETYPES.get(best_key, self.SYSTEM_ARCHETYPES["generic"])

    @staticmethod
    def _merge_pools(primary: List[str], fallback: List[str]) -> List[str]:
        merged: List[str] = []
        for item in primary + fallback:
            if item not in merged:
                merged.append(item)
        return merged

    def _build_blueprint_requirements_prompt(self, page_blueprint: Dict[str, Any]) -> str:
        if not isinstance(page_blueprint, dict) or not page_blueprint:
            return ""

        blocks = page_blueprint.get("functional_blocks") or []
        if not isinstance(blocks, list) or not blocks:
            return ""

        lines = [
            "### 功能块与证据锚点约束（必须执行）",
            "- 每个功能块必须渲染一个外层容器：`<section class='bento-card' data-block-id='...' data-claim-id='...'>`。",
            "- 外层容器中必须包含可交互控件（按钮/输入框/下拉/链接）至少 1 个。",
            "- 禁止忽略 claim_id；每个 claim_id 必须在 html_fragment 出现一次且仅一次。",
        ]

        for block in blocks:
            block_id = str(block.get("block_id") or "").strip()
            claim_id = str(block.get("claim_id") or "").strip()
            title = str(block.get("title") or "").strip() or "未命名块"
            block_type = str(block.get("block_type") or "").strip() or "generic"
            required_widgets = [str(x).strip() for x in (block.get("required_widgets") or []) if str(x).strip()]
            api_refs = [str(x).strip() for x in (block.get("api_refs") or []) if str(x).strip()]

            lines.append(
                f"- block_id={block_id} | claim_id={claim_id} | type={block_type} | title={title}"
            )
            if required_widgets:
                lines.append(f"  * 必须包含组件ID: {', '.join(required_widgets)}")
            if api_refs:
                lines.append(f"  * 关联接口ID: {', '.join(api_refs)}")

        chart_types = [str(x).strip() for x in (page_blueprint.get("required_chart_types") or []) if str(x).strip()]
        if chart_types:
            lines.append(f"- 图表类型至少覆盖: {', '.join(chart_types)}")
        return "\n".join(lines)

    def _construct_prompt(
        self,
        style: str,
        framework: str,
        context: List[str],
        title: str,
        industry_prompt: str = "",
        project_name: str = "",
        page_id: str = "",
        industry_key: str = "general",
        rng: random.Random = None,
        page_blueprint: Dict[str, Any] = None,
        style_context: Dict[str, Any] = None,
    ) -> str:
        """构造 Prompt（收敛为产品化界面，避免 PPT/展示稿风格）"""
        rng = rng or random.Random(self.session_nonce)
        style_ctx = style_context if isinstance(style_context, dict) else {}

        # 业务词汇字符串
        context_str = ", ".join(context[:15])

        archetype_key, archetype = self._infer_system_archetype(project_name, title, context)

        # 页面级受控随机：增强差异化，同时让版式贴近系统类型。
        chart_min, chart_max = archetype.get("chart_range", (2, 4))
        table_min, table_max = archetype.get("table_range", (1, 2))
        chart_count = rng.randint(chart_min, chart_max)
        table_count = rng.randint(table_min, table_max)

        chart_pool_map = {
            "forestry": ["bar", "line", "pie", "scatter", "heatmap", "sankey", "treemap"],
            "healthcare": ["line", "bar", "pie", "scatter", "heatmap", "radar"],
            "manufacturing": ["bar", "line", "gauge", "heatmap", "sankey", "funnel"],
            "general": ["bar", "line", "pie", "scatter", "heatmap"],
        }
        chart_types_pool = self._merge_pools(
            archetype.get("preferred_chart_types", []),
            chart_pool_map.get(industry_key, chart_pool_map["general"]),
        )
        selected_types = rng.sample(chart_types_pool, k=min(chart_count, len(chart_types_pool)))

        layout_variants = archetype.get("layout_variants", self.SYSTEM_ARCHETYPES["generic"]["layout_variants"])
        layout_variant = rng.choice(layout_variants)

        signature = f"{layout_variant}|{','.join(selected_types)}|{chart_count}|{table_count}"
        retry_guard = 0
        while signature in self._used_layout_signatures and retry_guard < 4:
            rng.shuffle(selected_types)
            layout_variant = rng.choice(layout_variants)
            signature = f"{layout_variant}|{','.join(selected_types)}|{chart_count}|{table_count}"
            retry_guard += 1
        self._used_layout_signatures.add(signature)

        variation_token_src = f"{project_name}|{page_id}|{title}|{signature}|{self.session_nonce}"
        variation_token = hashlib.md5(variation_token_src.encode("utf-8")).hexdigest()[:10]

        chart_type_desc = "\n".join([
            f"  - chart_{i+1}: {t}"
            for i, t in enumerate(selected_types)
        ])

        chart_ids = ", ".join([f"widget_chart_{i+1}" for i in range(chart_count)])
        table_ids = ", ".join([f"widget_table_{i+1}" for i in range(table_count)])
        must_sections_desc = "\n".join([f"- {sec}" for sec in archetype.get("must_sections", [])])
        table_fields_desc = "、".join(archetype.get("table_fields", []))
        business_keys_desc = ", ".join(archetype.get("business_data_keys", ["summary", "filters", "records"]))
        blueprint_prompt = self._build_blueprint_requirements_prompt(page_blueprint or {})

        style_direction = str(style_ctx.get("style_direction") or "").strip()
        layout_hint = str(style_ctx.get("layout_archetype_hint") or "").strip()
        anti_template = style_ctx.get("anti_template_policy") if isinstance(style_ctx.get("anti_template_policy"), dict) else {}
        banned_copy = anti_template.get("ban_generic_copy") if isinstance(anti_template.get("ban_generic_copy"), list) else []
        banned_copy = [str(x).strip() for x in banned_copy if str(x).strip()]
        banned_copy_text = "、".join(banned_copy) if banned_copy else "Dashboard / Overview、Admin、系统菜单"
        required_non_table_sections = int(anti_template.get("require_non_table_interactive_sections") or 2)

        style_requirements = [
            f"- Skill 风格方向：{style_direction or 'workbench-default'}",
            f"- 壳层布局提示：{layout_hint or 'command_workbench'}",
            f"- 禁止出现模板化文案：{banned_copy_text}",
            f"- 每页至少包含 {required_non_table_sections} 个非表格交互区（从：流程步骤条、状态时间线、操作面板、对比卡、详情抽屉中选择）。",
            "- 表格总面积不能主导首屏，表格区在首屏视觉占比建议 <= 50%。",
            "- 页面要体现“工作台”而不是“后台首页”，禁止纯指标卡+大表直铺。",
            "- 不要输出任何 HTML/CSS/JS 注释。",
            "- 页面样式不使用非零圆角，`border-radius` 统一为 0。",
            "- 图表若包含 Chart.js 配置，必须设置 `responsive: false` 与 `maintainAspectRatio: true`。",
        ]
        style_requirements_desc = "\n".join(style_requirements)

        return f"""
你是企业级 B 端产品设计师。
请为页面 "{title}" 生成可落地的业务系统页面（不是 PPT/展示页，不是传统后台首页模板）。

{industry_prompt}

### 业务上下文
- 核心行业：{context_str}
- 系统原型：{archetype.get("label", "通用管理系统")}（key={archetype_key}）
- 视觉风格：{style}
- UI 框架：{framework}
- 页面标识：{page_id or title}
- 变体标识：{variation_token}（仅用于内部差异化，不要直接展示在界面文本中）

### 强约束
- 禁止 PPT 风格：封面大标题、口号文案、全屏背景图、轮播、时间轴演示稿排版。
- 使用 Bootstrap `row/col` + `bento-card` 产品化布局，信息密度中等。
- 禁止在外层布局容器使用拉伸高度写法：`h-100`、`vh-100`、`min-vh-100`、`style="height:100%"`、`style="min-height:100vh"`。
- 页面必须包含以下业务区块：
{must_sections_desc}
- 页面布局变体建议：{layout_variant}
- 风格执行要求：
{style_requirements_desc}
- 业务文案必须具体，不得出现“数据分析/图表展示/业务看板”等空话标题。
- 数据需接近真实业务范围，不允许 `[10,20,30]` 这类占位数组。
- 不要输出完整 HTML 页，只输出主内容片段。
- 图表容器高度统一 `300px`。
- 主表字段应优先包含：{table_fields_desc}
- 交互动作应具体（例如：新建、分配、跟进、审批、归档），禁止“操作1/操作2”占位文案。
- 主列表（`widget_table_1`）需提供不少于 8 行业务记录；次级表（如 `widget_table_2+`）不少于 4 行。
- 页面首屏（1366x768）应至少展示 3 个可见业务区块，不得出现大面积空白。

### 输出 JSON
1. `html_fragment`:
   - 包含 {chart_count} 个图表容器，ID 必须为：{chart_ids}
   - 包含 {table_count} 个表格容器，ID 必须为：{table_ids}
   - 每个业务区块必须放入 `bento-card` 内。

2. `charts_config`:
   - 输出 {chart_count} 个图表 option。
   - container_id 必须与 html_fragment 的图表容器 ID 一一对应。
   - 图表类型建议（尽量覆盖，不必机械）： 
{chart_type_desc}
   - 优先 `bar/line/pie/scatter/heatmap`，禁止炫技型图表堆砌。

3. `business_data`:
   - 提供页面关键业务数据，结构化字段即可。
   - 至少包含这些键：{business_keys_desc}
   - 补充 `layout_quality`，包含：
     - `visible_sections`（数字）
     - `main_table_rows`（数字）
     - `secondary_table_rows`（数组）

### ID 规范（必须）
{chart_ids}, {table_ids}

### 返回示例结构
{{
  "html_fragment": "<div class='row g-3'>...</div>",
  "charts_config": [{{"container_id":"widget_chart_1","option":{{...}}}}],
  "business_data": {{}}
}}

{blueprint_prompt}
"""

    def _validate_content(self, data: Dict[str, Any], page_blueprint: Dict[str, Any] = None) -> bool:
        """校验返回数据完整性"""
        if not isinstance(data, dict):
            return False
        if "html_fragment" not in data or not data["html_fragment"]:
            return False
        if "charts_config" not in data:
            return False
        if page_blueprint:
            html = str(data.get("html_fragment") or "")
            blocks = page_blueprint.get("functional_blocks") or []
            for block in blocks:
                claim_id = str(block.get("claim_id") or "").strip()
                if claim_id and claim_id not in html:
                    return False
        return True

    def _get_fallback_content(
        self,
        genome: Dict[str, Any],
        page_info: Dict[str, Any],
        page_blueprint: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """降级方案"""
        if page_blueprint and isinstance(page_blueprint, dict) and page_blueprint.get("functional_blocks"):
            return self._get_blueprint_fallback_content(genome, page_info, page_blueprint)

        context = genome.get("business_context", ["业务数据", "系统指标"])
        term1 = context[0] if len(context) > 0 else "数据"
        term2 = context[1] if len(context) > 1 else "指标"
        project_name = genome.get("name") or genome.get("project_name", "")
        title = str(page_info.get("title", "业务页面"))
        archetype_key, archetype = self._infer_system_archetype(project_name, title, context)
        table_cols = archetype.get("table_fields", ["编号", "名称", "负责人", "状态", "更新时间"])

        col1 = table_cols[0] if len(table_cols) > 0 else "编号"
        col2 = table_cols[1] if len(table_cols) > 1 else "名称"
        col3 = table_cols[2] if len(table_cols) > 2 else "负责人"
        col4 = table_cols[3] if len(table_cols) > 3 else "状态"
        col5 = table_cols[4] if len(table_cols) > 4 else "更新时间"

        # 回退结构同样保持“真实业务系统形态”：筛选 + 指标 + 主表 + 详情。
        html = f"""
        <div class="row g-3 mb-3">
            <div class="col-12">
                <div class="bento-card p-3">
                    <div class="d-flex flex-wrap gap-2 align-items-center">
                        <input class="form-control" style="max-width: 240px;" placeholder="关键词搜索 {term1}/{term2}">
                        <select class="form-select" style="max-width: 160px;">
                            <option>状态: 全部</option>
                            <option>进行中</option>
                            <option>已完成</option>
                        </select>
                        <input type="date" class="form-control" style="max-width: 180px;">
                        <button class="btn btn-primary">查询</button>
                        <button class="btn btn-outline-secondary">导出</button>
                    </div>
                </div>
            </div>
        </div>
        <div class="row g-3 mb-3">
            <div class="col-md-3"><div class="bento-card p-3"><div class="text-muted">总量</div><div class="fs-4 fw-bold">1,284</div></div></div>
            <div class="col-md-3"><div class="bento-card p-3"><div class="text-muted">进行中</div><div class="fs-4 fw-bold text-primary">318</div></div></div>
            <div class="col-md-3"><div class="bento-card p-3"><div class="text-muted">异常</div><div class="fs-4 fw-bold text-danger">23</div></div></div>
            <div class="col-md-3"><div class="bento-card p-3"><div class="text-muted">完成率</div><div class="fs-4 fw-bold text-success">92.4%</div></div></div>
        </div>
        <div class="row g-3">
            <div class="col-lg-8">
                <div class="bento-card p-3 mb-3">
                    <h5 class="mb-3">{term1}趋势</h5>
                    <div id="widget_chart_1" style="height: 300px;"></div>
                </div>
                <div class="bento-card p-3">
                    <h5 class="mb-3">{archetype.get("label", "业务系统")}主列表</h5>
                    <div id="widget_table_1" class="table-responsive">
                        <table class="table table-hover align-middle">
                            <thead>
                                <tr><th>{col1}</th><th>{col2}</th><th>{col3}</th><th>{col4}</th><th>{col5}</th><th>操作</th></tr>
                            </thead>
                            <tbody>
                                <tr><td>NO-1001</td><td>核心{term1}A</td><td>王工</td><td><span class="badge bg-primary">进行中</span></td><td>2026-02-25</td><td><a href="#">详情</a> / <a href="#">跟进</a></td></tr>
                                <tr><td>NO-1002</td><td>基础{term1}B</td><td>李工</td><td><span class="badge bg-success">已完成</span></td><td>2026-02-24</td><td><a href="#">详情</a> / <a href="#">归档</a></td></tr>
                                <tr><td>NO-1003</td><td>协同{term1}C</td><td>赵工</td><td><span class="badge bg-warning text-dark">待审核</span></td><td>2026-02-24</td><td><a href="#">详情</a> / <a href="#">审批</a></td></tr>
                                <tr><td>NO-1004</td><td>版本{term1}D</td><td>周工</td><td><span class="badge bg-primary">进行中</span></td><td>2026-02-23</td><td><a href="#">详情</a> / <a href="#">跟进</a></td></tr>
                                <tr><td>NO-1005</td><td>归档{term1}E</td><td>孙工</td><td><span class="badge bg-success">已完成</span></td><td>2026-02-23</td><td><a href="#">详情</a> / <a href="#">归档</a></td></tr>
                                <tr><td>NO-1006</td><td>策略{term1}F</td><td>郑工</td><td><span class="badge bg-warning text-dark">待审核</span></td><td>2026-02-22</td><td><a href="#">详情</a> / <a href="#">审批</a></td></tr>
                                <tr><td>NO-1007</td><td>质量{term1}G</td><td>冯工</td><td><span class="badge bg-primary">进行中</span></td><td>2026-02-22</td><td><a href="#">详情</a> / <a href="#">跟进</a></td></tr>
                                <tr><td>NO-1008</td><td>对账{term1}H</td><td>陈工</td><td><span class="badge bg-success">已完成</span></td><td>2026-02-21</td><td><a href="#">详情</a> / <a href="#">归档</a></td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            <div class="col-lg-4">
                <div class="bento-card p-3 mb-3">
                    <h5 class="mb-3">{term2}分布</h5>
                    <div id="widget_chart_2" style="height: 300px;"></div>
                </div>
                <div class="bento-card p-3">
                    <h5 class="mb-2">对象详情</h5>
                    <p class="text-muted mb-2">编号: NO-1001</p>
                    <p class="text-muted mb-2">负责人: 王工</p>
                    <p class="text-muted mb-2">状态: 进行中</p>
                    <p class="mb-0">最近跟进: 已完成阶段性评审，待执行下一步动作。</p>
                    <button class="btn btn-sm btn-outline-primary mt-3">发起跟进</button>
                    <button class="btn btn-sm btn-outline-secondary mt-3 ms-2">查看轨迹</button>
                    <div id="widget_table_2" class="table-responsive mt-3">
                        <table class="table table-sm">
                            <thead><tr><th>时间</th><th>事件</th></tr></thead>
                            <tbody>
                                <tr><td>02-25 09:30</td><td>创建记录</td></tr>
                                <tr><td>02-25 11:20</td><td>更新状态</td></tr>
                                <tr><td>02-25 13:10</td><td>节点审批通过</td></tr>
                                <tr><td>02-25 14:40</td><td>触发通知</td></tr>
                                <tr><td>02-25 16:00</td><td>归档同步</td></tr>
                                <tr><td>02-25 17:20</td><td>生成报表</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        """

        charts = [
            {
                "container_id": "widget_chart_1",
                "option": {
                    "title": {"text": f"{term1}趋势"},
                    "xAxis": {"type": "category", "data": ["周一", "周二", "周三", "周四", "周五"]},
                    "yAxis": {"type": "value"},
                    "series": [{"data": [120, 200, 150, 218, 176], "type": "line", "smooth": True}]
                }
            },
            {
                "container_id": "widget_chart_2",
                "option": {
                    "title": {"text": f"{term2}分布"},
                    "series": [{"type": "pie", "data": [{"value": 34, "name": "进行中"}, {"value": 48, "name": "已完成"}, {"value": 18, "name": "异常"}]}]
                }
            }
        ]

        return {
            "html_fragment": html,
            "charts_config": charts,
            "business_data": {
                "fallback": True,
                "archetype": archetype_key,
                "records": 8,
                "layout_quality": {
                    "visible_sections": 6,
                    "main_table_rows": 8,
                    "secondary_table_rows": [6],
                },
            }
        }

    def _get_blueprint_fallback_content(
        self,
        genome: Dict[str, Any],
        page_info: Dict[str, Any],
        page_blueprint: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        蓝图驱动回退渲染：在 LLM 波动时仍保证功能块与证据锚点完整可审计。
        """
        blocks = page_blueprint.get("functional_blocks") or []
        page_title = str(page_info.get("title") or "业务页面")
        html_chunks: List[str] = ['<div class="row g-3">']
        charts: List[Dict[str, Any]] = []

        next_chart = 1
        next_table = 1
        chart_types = [str(x).strip() for x in (page_blueprint.get("required_chart_types") or []) if str(x).strip()]
        if not chart_types:
            chart_types = ["line", "bar"]

        for idx, block in enumerate(blocks, start=1):
            block_id = str(block.get("block_id") or f"{page_info.get('page_id', 'page')}_block_{idx}")
            claim_id = str(block.get("claim_id") or f"claim:{page_info.get('page_id', 'page')}:{idx}")
            title = str(block.get("title") or f"功能块{idx}")
            block_type = str(block.get("block_type") or "generic")
            required_widgets = [str(x).strip() for x in (block.get("required_widgets") or []) if str(x).strip()]

            if block_type in {"chart_card"}:
                widget_ids = [w for w in required_widgets if w.startswith("widget_chart_")]
                if not widget_ids:
                    widget_ids = [f"widget_chart_{next_chart}", f"widget_chart_{next_chart + 1}"]
                    next_chart += 2
                chart_divs = []
                for cid_idx, container_id in enumerate(widget_ids, start=1):
                    chart_type = chart_types[(cid_idx - 1) % len(chart_types)]
                    chart_divs.append(f'<div id="{container_id}" style="height: 300px;"></div>')
                    charts.append(
                        {
                            "container_id": container_id,
                            "option": {
                                "title": {"text": f"{title}-{cid_idx}"},
                                "xAxis": {"type": "category", "data": ["周一", "周二", "周三", "周四", "周五"]},
                                "yAxis": {"type": "value"},
                                "series": [{"type": chart_type if chart_type in {"line", "bar"} else "line", "data": [128, 156, 149, 172, 188]}],
                            },
                        }
                    )
                html_chunks.append(
                    f"""
                    <div class="col-lg-6">
                      <section class="bento-card p-3" data-block-id="{block_id}" data-claim-id="{claim_id}">
                        <h5 class="mb-3">{title}</h5>
                        {' '.join(chart_divs)}
                        <button class="btn btn-sm btn-outline-primary mt-3">刷新分析</button>
                      </section>
                    </div>
                    """
                )
            elif block_type in {"data_table", "action_form"}:
                table_id = next((w for w in required_widgets if w.startswith("widget_table_")), f"widget_table_{next_table}")
                next_table += 1
                html_chunks.append(
                    f"""
                    <div class="col-12">
                      <section class="bento-card p-3" data-block-id="{block_id}" data-claim-id="{claim_id}">
                        <h5 class="mb-3">{title}</h5>
                        <div class="d-flex flex-wrap gap-2 mb-3">
                          <input class="form-control" style="max-width:220px;" placeholder="关键词">
                          <select class="form-select" style="max-width:160px;"><option>状态: 全部</option><option>进行中</option><option>已完成</option></select>
                          <button class="btn btn-primary">查询</button>
                          <button class="btn btn-outline-secondary">导出</button>
                        </div>
                        <div id="{table_id}" class="table-responsive">
                          <table class="table table-hover align-middle">
                            <thead><tr><th>编号</th><th>主题</th><th>负责人</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
                            <tbody>
                              <tr><td>NO-1001</td><td>{page_title}主记录A</td><td>王工</td><td><span class="badge bg-primary">进行中</span></td><td>2026-02-26</td><td><a href="#">详情</a></td></tr>
                              <tr><td>NO-1002</td><td>{page_title}主记录B</td><td>李工</td><td><span class="badge bg-success">已完成</span></td><td>2026-02-25</td><td><a href="#">详情</a></td></tr>
                              <tr><td>NO-1003</td><td>{page_title}主记录C</td><td>赵工</td><td><span class="badge bg-warning text-dark">待审核</span></td><td>2026-02-25</td><td><a href="#">详情</a></td></tr>
                              <tr><td>NO-1004</td><td>{page_title}主记录D</td><td>周工</td><td><span class="badge bg-primary">进行中</span></td><td>2026-02-24</td><td><a href="#">详情</a></td></tr>
                              <tr><td>NO-1005</td><td>{page_title}主记录E</td><td>孙工</td><td><span class="badge bg-success">已完成</span></td><td>2026-02-23</td><td><a href="#">详情</a></td></tr>
                              <tr><td>NO-1006</td><td>{page_title}主记录F</td><td>陈工</td><td><span class="badge bg-primary">进行中</span></td><td>2026-02-22</td><td><a href="#">详情</a></td></tr>
                              <tr><td>NO-1007</td><td>{page_title}主记录G</td><td>郑工</td><td><span class="badge bg-warning text-dark">待审核</span></td><td>2026-02-22</td><td><a href="#">详情</a></td></tr>
                              <tr><td>NO-1008</td><td>{page_title}主记录H</td><td>冯工</td><td><span class="badge bg-success">已完成</span></td><td>2026-02-21</td><td><a href="#">详情</a></td></tr>
                            </tbody>
                          </table>
                        </div>
                      </section>
                    </div>
                    """
                )
            else:
                html_chunks.append(
                    f"""
                    <div class="col-lg-6">
                      <section class="bento-card p-3" data-block-id="{block_id}" data-claim-id="{claim_id}">
                        <h5 class="mb-3">{title}</h5>
                        <p class="text-muted mb-2">对象编号: NO-1001</p>
                        <p class="text-muted mb-2">最近状态: 处理中</p>
                        <p class="mb-3">该区块用于承载 {title} 的业务动作与详情回放。</p>
                        <button class="btn btn-sm btn-outline-primary">发起处理</button>
                        <button class="btn btn-sm btn-outline-secondary ms-2">查看轨迹</button>
                      </section>
                    </div>
                    """
                )

        html_chunks.append("</div>")

        return {
            "html_fragment": "\n".join(html_chunks),
            "charts_config": charts,
            "business_data": {
                "fallback": True,
                "blueprint_fallback": True,
                "block_count": len(blocks),
                "layout_quality": {
                    "visible_sections": len(blocks),
                    "main_table_rows": 8,
                    "secondary_table_rows": [6],
                },
            },
        }
