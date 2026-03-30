"""
HTML 组装器 (HTML Assembler)
V2.3 核心组件 (Phase 3)：负责将母版 HTML、内容片段和图表配置组装成最终的 HTML 文件
增强功能：自动规范化容器 ID，确保与截图引擎兼容 + CSS 类名混淆
"""
import logging
import json
import re
from typing import Dict, Any, List, Tuple
from modules.chart_injector import ChartInjector
from modules.runtime_skill_engine import resolve_external_script_policy

logger = logging.getLogger(__name__)

class HTMLAssembler:
    """
    HTML 组装器
    执行纯字符串替换和脚本注入，不涉及 LLM 调用
    V2.3: 增加类名混淆支持
    """

    def __init__(self):
        self.chart_injector = ChartInjector()

    def assemble(
        self,
        master_template: str,
        content_json: Dict[str, Any],
        page_info: Dict[str, Any],
        class_map: Dict[str, str] = None,
        project_name: str = "",
        page_blueprint: Dict[str, Any] = None,
        runtime_skill_constraints: Dict[str, Any] = None,
    ) -> str:
        """
        组装最终 HTML

        Args:
            master_template: 由 LayoutTemplateGenerator 生成的 HTML 母版
            content_json: 由 PageContentGenerator 生成的内容数据
            page_info: 页面基本信息 (title 等)
            class_map: 类名映射表 (用于混淆 LLM 生成的标准类名)
            project_name: 项目名称 (用于图表数据生成的行业适配)

        Returns:
            str: 最终的可渲染 HTML
        """
        try:
            # 0. 设置图表注入器的上下文
            if project_name:
                self.chart_injector.set_scope(project_name)

            # 1. 提取数据
            html_fragment = content_json.get("html_fragment", "<!-- No Content -->")
            charts_config = content_json.get("charts_config", [])
            page_title = page_info.get("title", "未命名页面")

            # 1.5 [关键] 规范化所有组件 ID，确保与截图引擎兼容
            html_fragment, charts_config = self._normalize_widget_ids(html_fragment, charts_config)

            # 1.6 [V2.3 新增] 应用类名混淆
            # 将 LLM 生成的标准类名 (bento-card, card-header 等) 替换为混淆后的类名
            if class_map:
                html_fragment = self._apply_class_obfuscation(html_fragment, class_map)

            # 1.65 将 claim/block 锚点强制写回到组件，防止 LLM 漏写 data-claim-id
            html_fragment = self._inject_claim_anchors(html_fragment, page_blueprint or {})

            # 1.7 防止“拉伸高度导致首屏空白”：清理 h-100/100vh 类写法
            html_fragment = self._sanitize_layout_density(html_fragment)

            # 2. 注入核心内容 (HTML Fragment)
            assembled_html = master_template.replace("{{ main_content_area }}", html_fragment)

            # 3. 注入页面标题
            assembled_html = assembled_html.replace("{{ page_title }}", page_title)

            # 4. 生成并注入图表脚本
            script_policy = resolve_external_script_policy(
                ((runtime_skill_constraints or {}).get("frontend") or {})
            )
            script_block = self._generate_script_block(charts_config, script_policy=script_policy)
            assembled_html = assembled_html.replace("{{ page_scripts }}", script_block)

            return assembled_html

        except Exception as e:
            logger.error(f"HTML 组装失败: {e}")
            return master_template.replace("{{ main_content_area }}", "<div>Error assembling content</div>")

    def _inject_claim_anchors(self, html: str, page_blueprint: Dict[str, Any]) -> str:
        """
        根据 ui_blueprint 将 data-claim-id/data-block-id 回写到关键组件上。
        """
        if not html or not isinstance(page_blueprint, dict):
            return html
        blocks = page_blueprint.get("functional_blocks") or []
        if not isinstance(blocks, list) or not blocks:
            return html

        result = html
        # 若已有锚点，优先保留原文
        has_claim_anchor = "data-claim-id=" in result

        for idx, block in enumerate(blocks, start=1):
            block_id = str(block.get("block_id") or f"block_{idx}").strip()
            claim_id = str(block.get("claim_id") or f"claim_{idx}").strip()
            required_widgets = [str(x).strip() for x in (block.get("required_widgets") or []) if str(x).strip()]

            # 优先把锚点挂在约定 widget 上。
            mounted = False
            for wid in required_widgets:
                pattern = rf'(<[^>]*\bid\s*=\s*["\']{re.escape(wid)}["\'][^>]*)(>)'
                def _repl(m):
                    attrs = m.group(1)
                    if "data-claim-id=" in attrs:
                        return m.group(0)
                    return f'{attrs} data-block-id="{block_id}" data-claim-id="{claim_id}"{m.group(2)}'
                updated, count = re.subn(pattern, _repl, result, count=1)
                if count > 0:
                    result = updated
                    mounted = True
                    break

            if mounted:
                continue

            # 次优：在第一个 bento-card 上补锚点（仅在完全缺锚点时触发）。
            if not has_claim_anchor:
                pattern = r'(<section[^>]*class\s*=\s*["\'][^"\']*bento-card[^"\']*["\'][^>]*)(>)'
                def _section_repl(m):
                    attrs = m.group(1)
                    if "data-claim-id=" in attrs:
                        return m.group(0)
                    return f'{attrs} data-block-id="{block_id}" data-claim-id="{claim_id}"{m.group(2)}'
                updated, count = re.subn(pattern, _section_repl, result, count=1)
                if count > 0:
                    result = updated
                    has_claim_anchor = True

        return result

    def _apply_class_obfuscation(self, html: str, class_map: Dict[str, str]) -> str:
        """
        将 HTML 中的标准类名替换为混淆后的类名

        策略：只替换 class="..." 中的类名，避免误伤其他内容
        """
        if not class_map:
            return html

        result = html

        # 对每个需要替换的类名进行处理
        for original, obfuscated in class_map.items():
            if original == obfuscated:
                continue  # 跳过没有变化的

            # 匹配 class="... original ..." 或 class='... original ...'
            # 使用 word boundary 确保精确匹配
            # 注意：类名中可能有连字符，需要转义

            # Pattern 1: class="xxx original xxx"
            pattern1 = rf'(class\s*=\s*["\'][^"\']*)\b{re.escape(original)}\b([^"\']*["\'])'
            result = re.sub(pattern1, rf'\1{obfuscated}\2', result)

        return result

    def _normalize_widget_ids(self, html_fragment: str, charts_config: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        规范化所有组件容器 ID，确保与截图引擎兼容

        截图引擎期望的 ID 格式:
        - 图表容器: widget_chart_1, widget_chart_2, ...
        - 表格容器: widget_table_1, widget_table_2, ...

        Args:
            html_fragment: 原始 HTML 片段
            charts_config: 原始图表配置

        Returns:
            Tuple[str, List]: (规范化后的 HTML, 规范化后的图表配置)
        """
        normalized_html = html_fragment
        normalized_configs = []

        # ID 映射表: old_id -> new_id
        id_mapping = {}

        chart_counter = 1
        table_counter = 1

        # 1. 处理 charts_config 中的图表容器
        for i, config in enumerate(charts_config):
            old_id = config.get("container_id") or config.get("id")

            # 容错处理：如果 LLM 未返回 ID，尝试根据顺序自动匹配
            if not old_id:
                # 默认假设：Config 中的顺序与 HTML 中的 widget_chart_X 顺序一致
                # 简单的启发式规则
                if config.get("type") == "table" or "table" in str(config).lower():
                    # 暂时无法精确匹配表格，先跳过或分配一个推测 ID
                    pass
                else:
                    # 对于图表，直接分配当前计数器的 ID
                    # 这基于假设：HTML 中已经有了 widget_chart_X，且 Config 也是按这个顺序给的
                    old_id = f"widget_chart_{chart_counter}"
                    logger.warning(f"图表配置缺少 ID，自动推断为: {old_id}")

            if not old_id:
                continue

            # 判断是图表还是表格 (根据 ID 命名或配置内容)
            is_table = "table" in old_id.lower() or config.get("type") == "table"

            if is_table:
                new_id = f"widget_table_{table_counter}"
                table_counter += 1
            else:
                new_id = f"widget_chart_{chart_counter}"
                chart_counter += 1

            id_mapping[old_id] = new_id

            # 更新配置中的 container_id
            new_config = config.copy()
            new_config["container_id"] = new_id
            normalized_configs.append(new_config)

        # 2. 在 HTML 中替换所有映射的 ID
        for old_id, new_id in id_mapping.items():
            # 匹配 id="xxx" 或 id='xxx' 格式
            pattern = rf'id\s*=\s*["\']({re.escape(old_id)})["\']'
            replacement = f'id="{new_id}"'
            normalized_html = re.sub(pattern, replacement, normalized_html)

        # 3. 扫描 HTML 中可能遗漏的图表容器 (未在 charts_config 中声明的)
        # 匹配具有 height 样式的 div (通常是图表容器)
        orphan_chart_pattern = r'<div[^>]*id\s*=\s*["\']([^"\']+)["\'][^>]*style\s*=\s*["\'][^"\']*height\s*:\s*\d+px[^"\']*["\'][^>]*>'

        for match in re.finditer(orphan_chart_pattern, normalized_html):
            found_id = match.group(1)
            # 如果这个 ID 还没有被规范化
            if found_id not in id_mapping.values() and not found_id.startswith("widget_"):
                new_id = f"widget_chart_{chart_counter}"
                chart_counter += 1

                # 替换 HTML 中的 ID
                old_pattern = rf'id\s*=\s*["\']({re.escape(found_id)})["\']'
                normalized_html = re.sub(old_pattern, f'id="{new_id}"', normalized_html, count=1)

                logger.debug(f"规范化遗漏的图表容器: {found_id} -> {new_id}")

        # 4. 扫描并规范化表格容器
        table_pattern = r'<div[^>]*id\s*=\s*["\']([^"\']*table[^"\']*)["\'][^>]*>'

        for match in re.finditer(table_pattern, normalized_html, re.IGNORECASE):
            found_id = match.group(1)
            if found_id not in id_mapping.values() and not found_id.startswith("widget_"):
                new_id = f"widget_table_{table_counter}"
                table_counter += 1

                old_pattern = rf'id\s*=\s*["\']({re.escape(found_id)})["\']'
                normalized_html = re.sub(old_pattern, f'id="{new_id}"', normalized_html, count=1)

                logger.debug(f"规范化遗漏的表格容器: {found_id} -> {new_id}")

        # 5. 以 HTML 中真实存在的图表容器为准，对齐 charts_config，避免“图表容器空白”
        html_chart_ids = re.findall(r'id\s*=\s*["\'](widget_chart_\d+)["\']', normalized_html)
        html_chart_ids = self._dedupe_preserve_order(html_chart_ids)
        if html_chart_ids:
            aligned_configs: List[Dict[str, Any]] = []
            used_ids = set()
            for cfg in normalized_configs:
                cid = str(cfg.get("container_id", "")).strip()
                if cid in html_chart_ids and cid not in used_ids:
                    aligned_configs.append(cfg)
                    used_ids.add(cid)

            # 对“有容器但无配置”的图表补默认配置占位，避免截图时出现空白容器。
            for idx, cid in enumerate(html_chart_ids, start=1):
                if cid in used_ids:
                    continue
                aligned_configs.append(
                    {
                        "container_id": cid,
                        "type": "line",
                        "title": f"趋势图{idx}",
                        "option": {},
                    }
                )
                used_ids.add(cid)

            normalized_configs = aligned_configs

        logger.info(
            f"ID 规范化完成: 重命名={len(id_mapping)}个, 图表容器={len(html_chart_ids)}, "
            f"图表配置={len(normalized_configs)}"
        )

        return normalized_html, normalized_configs

    @staticmethod
    def _dedupe_preserve_order(values: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _sanitize_layout_density(self, html: str) -> str:
        """
        清理容易造成首屏大面积空白的布局写法：
        - h-100 / vh-100 / min-vh-100
        - style 中的 height:100% / min-height:100vh
        """
        if not html:
            return html

        result = html

        # 清理常见“拉满高度”类名
        result = re.sub(r'\bh-100\b', '', result)
        result = re.sub(r'\bvh-100\b', '', result)
        result = re.sub(r'\bmin-vh-100\b', '', result)

        # 清理 class 属性中重复空格
        result = re.sub(r'class\s*=\s*["\']([^"\']*)["\']', lambda m: self._normalize_class_attr(m.group(0), m.group(1)), result)

        # 清理 style 属性里会造成拉伸的高度规则（保留图表300px等正常高度）
        result = re.sub(
            r'style\s*=\s*["\']([^"\']*)["\']',
            lambda m: self._sanitize_style_attr(m.group(0), m.group(1)),
            result,
        )
        return result

    @staticmethod
    def _normalize_class_attr(full_attr: str, class_value: str) -> str:
        parts = [x for x in class_value.split() if x]
        normalized = " ".join(parts)
        quote = '"' if '"' in full_attr else "'"
        return f'class={quote}{normalized}{quote}'

    @staticmethod
    def _sanitize_style_attr(full_attr: str, style_value: str) -> str:
        style_text = style_value
        style_text = re.sub(r'(?i)\bheight\s*:\s*100%\s*;?', '', style_text)
        style_text = re.sub(r'(?i)\bmin-height\s*:\s*100vh\s*;?', '', style_text)
        # 收敛多余分号与空白
        style_text = re.sub(r';{2,}', ';', style_text).strip()
        style_text = re.sub(r'\s{2,}', ' ', style_text)
        style_text = style_text.strip('; ').strip()
        if not style_text:
            return ''
        quote = '"' if '"' in full_attr else "'"
        return f'style={quote}{style_text}{quote}'

    @staticmethod
    def _echarts_candidates_by_domain(allowed_domains: List[str]) -> List[str]:
        domain_to_url = {
            "cdn.jsdelivr.net": "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js",
            "unpkg.com": "https://unpkg.com/echarts@5.4.3/dist/echarts.min.js",
        }
        urls: List[str] = []
        for domain in allowed_domains:
            d = str(domain or "").strip().lower()
            url = domain_to_url.get(d)
            if url and url not in urls:
                urls.append(url)
        if not urls:
            urls = [
                "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js",
                "https://unpkg.com/echarts@5.4.3/dist/echarts.min.js",
            ]
        return urls

    def _generate_script_block(self, charts_config: List[Dict[str, Any]], script_policy: Dict[str, Any]) -> str:
        """生成包含 ECharts 库引用和初始化代码的 HTML 块"""

        # 1. 生成图表初始化逻辑
        # 复用 ChartInjector 的逻辑，但它需要 chart 对象有 '_render_id'
        # PageContentGenerator 返回的 config 中有 'container_id'
        # 我们做一下适配
        adapted_charts = []
        for chart in charts_config:
            # 获取 LLM 生成的 option
            option = chart.get("option")
            # 如果 option 是有效的字典，直接使用；否则标记需要自动生成
            chart_type = "custom" if option else "line"

            adapted_charts.append({
                "id": chart.get("container_id", "unknown"),
                "_render_id": chart.get("container_id"),
                "option": option,  # 直接传递 LLM 生成的完整 option
                "title": option.get("title", {}).get("text", "图表") if isinstance(option, dict) else "图表",
                "type": chart_type
            })

        init_js = self.chart_injector._generate_init_script(adapted_charts)

        mode = str((script_policy or {}).get("mode") or "allowlist_with_vendor_fallback").strip().lower()
        allowed_domains = [str(x).strip() for x in ((script_policy or {}).get("allowed_domains") or []) if str(x).strip()]
        vendor_fallback = (script_policy or {}).get("vendor_fallback") or {}
        vendor_echarts = str(vendor_fallback.get("echarts") or "vendor/echarts/5.4.3/echarts.min.js").strip()
        candidate_urls = self._echarts_candidates_by_domain(allowed_domains)

        if mode == "strict_no_external":
            loader = (
                f"<script src=\"{vendor_echarts}\"></script>\n"
                "<script>"
                "if(typeof echarts==='undefined'){console.error('ECharts vendor fallback missing');}"
                "</script>"
            )
        else:
            primary = candidate_urls[0]
            secondary = candidate_urls[1] if len(candidate_urls) > 1 else ""
            secondary_loader = (
                f"if(!window.__echarts_secondary_loaded){{window.__echarts_secondary_loaded=true;"
                f"var s2=document.createElement('script');s2.src='{secondary}';"
                f"s2.onerror=function(){{var sv=document.createElement('script');sv.src='{vendor_echarts}';document.head.appendChild(sv);}};"
                "document.head.appendChild(s2);}"
                if secondary and mode != "allow_all"
                else f"var sv=document.createElement('script');sv.src='{vendor_echarts}';document.head.appendChild(sv);"
            )
            loader = (
                f"<script src=\"{primary}\" onerror=\"{secondary_loader}\"></script>\n"
                "<script>"
                f"if(typeof echarts==='undefined'){{var sv=document.createElement('script');sv.src='{vendor_echarts}';document.head.appendChild(sv);}}"
                "</script>"
            )

        return f"""
    {loader}
    <script>
    {init_js}
    </script>
        """
