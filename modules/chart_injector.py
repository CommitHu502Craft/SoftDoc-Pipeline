"""
图表注入器模块
负责将 ECharts 图表配置和真实感数据注入到 HTML 骨架中
"""
import json
import math
import random
import logging
import datetime
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from modules.industry_adapter import get_adapter

logger = logging.getLogger(__name__)

class ChartInjector:
    """图表注入器"""

    def __init__(self):
        self.adapter = get_adapter()
        self.industry_key = "general"

    def set_scope(self, project_name: str):
        """设置当前项目范围，用于识别行业"""
        if project_name:
            self.industry_key = self.adapter.detect_industry(project_name)
            # logger.info(f"ChartInjector scope set to: {self.industry_key} (Project: {project_name})")

    def inject_charts(self, html: str, charts: List[Dict[str, Any]], project_name: str = "") -> str:
        """
        注入图表到 HTML
        """
        if project_name:
            self.set_scope(project_name)

        soup = BeautifulSoup(html, 'html.parser')

        # 1. 注入 ECharts CDN (在 </body> 前)
        self._inject_scripts(soup)

        # 2. 生成初始化脚本
        init_script = self._generate_init_script(charts)

        # 3. 注入脚本到 body 末尾
        script_tag = soup.new_tag("script")
        script_tag.string = init_script
        if soup.body:
            soup.body.append(script_tag)
        else:
            soup.append(script_tag)

        return str(soup)

    def _inject_scripts(self, soup: BeautifulSoup):
        """注入 ECharts 核心库"""
        if soup.body:
            # ECharts 5.x
            script = soup.new_tag("script", src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js")
            script["onerror"] = (
                "if(!window.__echarts_fallback_loaded){"
                "window.__echarts_fallback_loaded=true;"
                "var s=document.createElement('script');"
                "s.src='https://unpkg.com/echarts@5.4.3/dist/echarts.min.js';"
                "document.head.appendChild(s);"
                "}"
            )
            soup.body.insert(len(soup.body.contents), script)

    def _generate_init_script(self, charts: List[Dict[str, Any]]) -> str:
        """生成图表初始化 JS 代码（增强版：容错、重试、可见性守卫）"""
        chart_payloads: List[Dict[str, Any]] = []

        for chart in charts:
            chart_id = chart.get("id")
            render_id = chart.get("_render_id")

            if not render_id and chart_id:
                render_id = f"widget_{chart_id}"

            if chart.get("type") in ["table", "stats_card"]:
                continue
            if not render_id:
                continue

            option = chart.get("option")
            if not option:
                option = self._generate_chart_option(chart)

            chart_payloads.append(
                {
                    "render_id": str(render_id),
                    "title": str(chart.get("title", "图表")),
                    "option": option or {},
                }
            )

        charts_json = json.dumps(chart_payloads, ensure_ascii=False)
        return f"""
document.addEventListener('DOMContentLoaded', function() {{
    var chartSpecs = {charts_json};
    var chartInstances = [];
    var finishedCount = 0;
    var totalCount = chartSpecs.length;
    var allDone = false;
    var resizeTimer = null;
    var sizeObserver = null;
    var diagnostics = {{
        total: totalCount,
        success: 0,
        fallback_option: 0,
        placeholder: 0,
        missing_container: 0,
        missing_library: 0,
        set_option_error: 0,
        retries_exhausted: 0,
        started_at: Date.now(),
        finished_at: null,
        duration_ms: null
    }};
    window.__chart_render_diagnostics = diagnostics;
    window.echarts_rendering_finished = false;

    function finalizeIfReady() {{
        if (allDone) {{
            return;
        }}
        if (finishedCount >= totalCount) {{
            allDone = true;
            diagnostics.finished_at = Date.now();
            diagnostics.duration_ms = diagnostics.finished_at - diagnostics.started_at;
            window.echarts_rendering_finished = true;
            console.log('ECharts render finished: ' + finishedCount + '/' + totalCount);
        }}
    }}

    function markDone(reason) {{
        if (allDone) {{
            return;
        }}
        finishedCount += 1;
        if (reason && Object.prototype.hasOwnProperty.call(diagnostics, reason)) {{
            diagnostics[reason] += 1;
        }}
        finalizeIfReady();
    }}

    function forceDoneIfStuck() {{
        if (!allDone) {{
            diagnostics.retries_exhausted += Math.max(0, totalCount - finishedCount);
            finishedCount = totalCount;
            diagnostics.finished_at = Date.now();
            diagnostics.duration_ms = diagnostics.finished_at - diagnostics.started_at;
            allDone = true;
            window.echarts_rendering_finished = true;
            console.warn('ECharts render timeout fallback triggered.');
        }}
    }}

    function readableTextColor() {{
        var cssColor = '#334155';
        try {{
            cssColor = window.getComputedStyle(document.body).color || cssColor;
        }} catch (e) {{
            cssColor = '#334155';
        }}
        return cssColor;
    }}

    function renderPlaceholder(container, title, reason) {{
        if (!container) {{
            return;
        }}
        diagnostics.placeholder += 1;
        if (reason && Object.prototype.hasOwnProperty.call(diagnostics, reason)) {{
            diagnostics[reason] += 1;
        }}
        container.innerHTML =
            '<div style="height:100%;display:flex;flex-direction:column;justify-content:center;align-items:center;' +
            'border:1px dashed #cbd5e1;border-radius:8px;background:linear-gradient(135deg,#f8fafc,#eef2ff);' +
            'color:#475569;font-size:13px;gap:8px;">' +
            '<div style="font-weight:600;">' + (title || '图表加载中') + '</div>' +
            '<div style="opacity:0.8;">已使用占位视图（渲染降级）</div>' +
            '</div>';
    }}

    function fallbackOption(title) {{
        return {{
            title: {{ text: title || '趋势图', left: 'center', textStyle: {{ color: readableTextColor(), fontSize: 13 }} }},
            tooltip: {{ trigger: 'axis' }},
            grid: {{ left: '3%', right: '4%', bottom: '8%', containLabel: true }},
            xAxis: {{ type: 'category', data: ['一', '二', '三', '四', '五'] }},
            yAxis: {{ type: 'value' }},
            series: [{{ type: 'line', smooth: true, data: [12, 18, 15, 20, 17] }}]
        }};
    }}

    function normalizeOption(option, title) {{
        var opt = option;
        if (!opt || typeof opt !== 'object') {{
            return fallbackOption(title);
        }}
        var color = readableTextColor();
        opt.textStyle = opt.textStyle || {{}};
        if (!opt.textStyle.color) {{
            opt.textStyle.color = color;
        }}

        if (opt.title) {{
            if (Array.isArray(opt.title)) {{
                opt.title.forEach(function(t) {{
                    if (!t) return;
                    t.textStyle = t.textStyle || {{}};
                    if (!t.textStyle.color) t.textStyle.color = color;
                }});
            }} else {{
                opt.title.textStyle = opt.title.textStyle || {{}};
                if (!opt.title.textStyle.color) opt.title.textStyle.color = color;
            }}
        }}

        function normalizeAxis(axis) {{
            if (!axis) return;
            if (Array.isArray(axis)) {{
                axis.forEach(normalizeAxis);
                return;
            }}
            axis.axisLabel = axis.axisLabel || {{}};
            if (!axis.axisLabel.color) axis.axisLabel.color = color;
            axis.nameTextStyle = axis.nameTextStyle || {{}};
            if (!axis.nameTextStyle.color) axis.nameTextStyle.color = color;
            axis.axisLine = axis.axisLine || {{}};
            axis.axisLine.lineStyle = axis.axisLine.lineStyle || {{}};
            if (!axis.axisLine.lineStyle.color) axis.axisLine.lineStyle.color = 'rgba(100,116,139,0.45)';
        }}

        normalizeAxis(opt.xAxis);
        normalizeAxis(opt.yAxis);

        if (opt.legend) {{
            if (Array.isArray(opt.legend)) {{
                opt.legend.forEach(function(l) {{
                    if (!l) return;
                    l.textStyle = l.textStyle || {{}};
                    if (!l.textStyle.color) l.textStyle.color = color;
                }});
            }} else {{
                opt.legend.textStyle = opt.legend.textStyle || {{}};
                if (!opt.legend.textStyle.color) opt.legend.textStyle.color = color;
            }}
        }}

        if (!opt.series || (Array.isArray(opt.series) && opt.series.length === 0)) {{
            return fallbackOption(title);
        }}
        return opt;
    }}

    function safeSetOption(instance, option, title) {{
        try {{
            instance.setOption(normalizeOption(option, title), true);
            diagnostics.success += 1;
            return true;
        }} catch (e) {{
            diagnostics.set_option_error += 1;
            console.warn('setOption failed, fallback to safe line chart:', e);
            try {{
                instance.clear();
                instance.setOption(fallbackOption(title), true);
                diagnostics.fallback_option += 1;
                return true;
            }} catch (e2) {{
                console.error('fallback setOption failed:', e2);
                return false;
            }}
        }}
    }}

    function initChartWithRetry(spec, retries) {{
        var container = document.getElementById(spec.render_id);
        if (!container) {{
            if (retries > 0) {{
                setTimeout(function() {{ initChartWithRetry(spec, retries - 1); }}, 160);
            }} else {{
                console.warn('Chart container not found:', spec.render_id);
                markDone('missing_container');
            }}
            return;
        }}

        var width = container.clientWidth || 0;
        var height = container.clientHeight || 0;
        if ((width === 0 || height === 0) && retries > 0) {{
            setTimeout(function() {{ initChartWithRetry(spec, retries - 1); }}, 180);
            return;
        }}

        if (typeof echarts === 'undefined') {{
            if (retries > 0) {{
                setTimeout(function() {{ initChartWithRetry(spec, retries - 1); }}, 220);
            }} else {{
                console.error('ECharts library not available for', spec.render_id);
                renderPlaceholder(container, spec.title, 'missing_library');
                markDone();
            }}
            return;
        }}

        var instance = echarts.getInstanceByDom(container);
        if (!instance) {{
            instance = echarts.init(container, null, {{ renderer: 'canvas' }});
        }}
        if (sizeObserver) {{
            try {{ sizeObserver.observe(container); }} catch (e) {{}}
        }}

        var applied = safeSetOption(instance, spec.option, spec.title);
        if (!applied) {{
            renderPlaceholder(container, spec.title, null);
            markDone();
            return;
        }}
        chartInstances.push(instance);

        var chartDone = false;
        function markChartDoneOnce() {{
            if (chartDone) {{
                return;
            }}
            chartDone = true;
            markDone();
        }}

        if (typeof instance.on === 'function') {{
            try {{
                instance.on('finished', markChartDoneOnce);
            }} catch (e) {{}}
        }}

        requestAnimationFrame(function() {{
            try {{ instance.resize(); }} catch (e) {{}}
        }});
        setTimeout(function() {{
            try {{ instance.resize(); }} catch (e) {{}}
            markChartDoneOnce();
        }}, 220);
    }}

    if (totalCount === 0) {{
        diagnostics.finished_at = Date.now();
        diagnostics.duration_ms = diagnostics.finished_at - diagnostics.started_at;
        window.echarts_rendering_finished = true;
        return;
    }}

    function resizeAll() {{
        chartInstances.forEach(function(chart) {{
            try {{ chart.resize(); }} catch (e) {{}}
        }});
    }}

    if (typeof ResizeObserver !== 'undefined') {{
        sizeObserver = new ResizeObserver(function() {{
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(resizeAll, 100);
        }});
    }}

    chartSpecs.forEach(function(spec) {{
        initChartWithRetry(spec, 10);
    }});

    window.addEventListener('resize', function() {{
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(resizeAll, 120);
    }});

    // 避免单图表异常导致截图流程永远等待。
    setTimeout(forceDoneIfStuck, 6000);
}});
"""

    def _generate_chart_option(self, chart_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据图表类型和上下文生成 ECharts option
        V2.4: 支持工业控制系统图表类型
        """
        chart_type = chart_info.get('type', 'line').lower()
        title = chart_info.get('title', '数据图表')

        # 扩展映射：支持更多图表类型
        echarts_type = 'line'
        if 'bar' in chart_type: echarts_type = 'bar'
        elif 'pie' in chart_type or '占比' in title or '分布' in title: echarts_type = 'pie'
        elif 'radar' in chart_type or '评估' in title or '能力' in title: echarts_type = 'radar'
        elif 'scatter' in chart_type or '相关' in title: echarts_type = 'scatter'
        elif 'gauge' in chart_type or '仪表' in title or '温度' in title or '压力' in title or '速度' in title: echarts_type = 'gauge'
        elif 'liquid' in chart_type or '液位' in title or '容量' in title or '进度' in title: echarts_type = 'liquid'
        elif 'heatmap' in chart_type or '热力' in title or '分布图' in title: echarts_type = 'heatmap'
        elif 'sankey' in chart_type or '流转' in title or '工艺' in title: echarts_type = 'sankey'
        elif 'funnel' in chart_type or '漏斗' in title or '转化' in title: echarts_type = 'funnel'
        elif 'treemap' in chart_type or '构成' in title or '层级' in title: echarts_type = 'treemap'
        elif 'gantt' in chart_type or '甘特' in title or '排程' in title or '计划' in title or '进度' in title: echarts_type = 'gantt'
        elif 'graph' in chart_type or 'flow' in chart_type or '流程' in title or '拓扑' in title or '关系' in title or '网络' in title: echarts_type = 'graph'
        elif '状态' in title or '设备' in title or '监控' in title: echarts_type = 'gauge'
        elif '产量' in title or '效率' in title or '利用率' in title: echarts_type = 'gauge'

        # 生成数据 (确保 description 不为 None)
        data_context = chart_info.get('description') or title

        if echarts_type == 'line' or echarts_type == 'bar':
            return self._generate_axis_chart(title, echarts_type, data_context)
        elif echarts_type == 'pie':
            return self._generate_pie_chart(title, data_context)
        elif echarts_type == 'radar':
            return self._generate_radar_chart(title, data_context)
        elif echarts_type == 'scatter':
            return self._generate_scatter_chart(title, data_context)
        elif echarts_type == 'gauge':
            return self._generate_gauge_chart(title, data_context)
        elif echarts_type == 'liquid':
            return self._generate_liquid_chart(title, data_context)
        elif echarts_type == 'heatmap':
            return self._generate_heatmap_chart(title, data_context)
        elif echarts_type == 'sankey':
            return self._generate_sankey_chart(title, data_context)
        elif echarts_type == 'funnel':
            return self._generate_funnel_chart(title, data_context)
        elif echarts_type == 'treemap':
            return self._generate_treemap_chart(title, data_context)
        elif echarts_type == 'gantt':
            return self._generate_gantt_chart(title, data_context)
        elif echarts_type == 'graph':
            return self._generate_graph_chart(title, data_context)

        return {}

    def _generate_axis_chart(self, title: str, type_: str, context: str) -> Dict[str, Any]:
        """生成直角坐标系图表 (Line/Bar) - 增强版：多种变体"""
        # 生成时间轴 (最近7天或12个月)
        is_monthly = "月" in context or "年" in context
        categories = []
        now = datetime.datetime.now()

        if is_monthly:
            for i in range(6):
                date = now - datetime.timedelta(days=30*(5-i))
                categories.append(f"{date.month}月")
        else:
            for i in range(7):
                date = now - datetime.timedelta(days=(6-i))
                categories.append(date.strftime("%m-%d"))

        # 生成数据
        series_data = self._generate_realistic_data(len(categories), 100, 500, trend="up" if "增长" in context else "random")

        # 随机选择图表变体
        variant = random.choice(['basic', 'gradient', 'stacked', 'horizontal', 'dual_axis'])

        if type_ == 'bar':
            return self._generate_bar_variant(title, categories, series_data, variant)
        else:
            return self._generate_line_variant(title, categories, series_data, variant)

    def _generate_bar_variant(self, title: str, categories: list, data: list, variant: str) -> Dict[str, Any]:
        """生成柱状图变体"""
        base = {
            "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": "3%", "right": "4%", "bottom": "8%", "top": "15%", "containLabel": True},
        }

        if variant == 'horizontal':
            # 横向条形图
            base.update({
                "xAxis": {"type": "value"},
                "yAxis": {"type": "category", "data": categories},
                "series": [{
                    "type": "bar",
                    "data": data,
                    "itemStyle": {
                        "borderRadius": [0, 4, 4, 0],
                        "color": {"type": "linear", "x": 0, "y": 0, "x2": 1, "y2": 0,
                                  "colorStops": [{"offset": 0, "color": "#5470c6"}, {"offset": 1, "color": "#91cc75"}]}
                    },
                    "barWidth": "60%"
                }]
            })
        elif variant == 'gradient':
            # 渐变柱状图
            base.update({
                "xAxis": {"type": "category", "data": categories, "axisLine": {"lineStyle": {"color": "#ccc"}}},
                "yAxis": {"type": "value", "splitLine": {"lineStyle": {"type": "dashed"}}},
                "series": [{
                    "type": "bar",
                    "data": data,
                    "itemStyle": {
                        "borderRadius": [8, 8, 0, 0],
                        "color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                                  "colorStops": [{"offset": 0, "color": "#73c0de"}, {"offset": 1, "color": "#5470c6"}]}
                    },
                    "barWidth": "50%",
                    "label": {"show": True, "position": "top", "fontSize": 10}
                }]
            })
        elif variant == 'stacked':
            # 堆叠柱状图
            data2 = self._generate_realistic_data(len(categories), 50, 200, "random")
            base.update({
                "legend": {"data": ["系列A", "系列B"], "bottom": 0},
                "xAxis": {"type": "category", "data": categories},
                "yAxis": {"type": "value"},
                "series": [
                    {"name": "系列A", "type": "bar", "stack": "total", "data": data, "itemStyle": {"color": "#5470c6"}},
                    {"name": "系列B", "type": "bar", "stack": "total", "data": data2, "itemStyle": {"color": "#91cc75"}}
                ]
            })
        else:
            # 基础柱状图
            base.update({
                "xAxis": {"type": "category", "data": categories},
                "yAxis": {"type": "value"},
                "series": [{
                    "type": "bar",
                    "data": data,
                    "itemStyle": {"borderRadius": [4, 4, 0, 0]},
                    "barWidth": "55%"
                }]
            })
        return base

    def _generate_line_variant(self, title: str, categories: list, data: list, variant: str) -> Dict[str, Any]:
        """生成折线图变体"""
        base = {
            "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": "3%", "right": "4%", "bottom": "8%", "top": "15%", "containLabel": True},
        }

        if variant == 'gradient':
            # 渐变面积图 (透明度低)
            base.update({
                "xAxis": {"type": "category", "data": categories, "boundaryGap": False},
                "yAxis": {"type": "value"},
                "series": [{
                    "type": "line",
                    "data": data,
                    "smooth": True,
                    "lineStyle": {"width": 2},
                    "areaStyle": {
                        "opacity": 0.15,
                        "color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                                  "colorStops": [{"offset": 0, "color": "#5470c6"}, {"offset": 1, "color": "transparent"}]}
                    }
                }]
            })
        elif variant == 'dual_axis':
            # 双Y轴折线图
            data2 = self._generate_realistic_data(len(categories), 20, 100, "random")
            base.update({
                "legend": {"data": ["指标A", "指标B"], "bottom": 0},
                "xAxis": {"type": "category", "data": categories},
                "yAxis": [
                    {"type": "value", "name": "指标A"},
                    {"type": "value", "name": "指标B", "position": "right"}
                ],
                "series": [
                    {"name": "指标A", "type": "line", "data": data, "smooth": True},
                    {"name": "指标B", "type": "line", "yAxisIndex": 1, "data": data2, "smooth": True, "lineStyle": {"type": "dashed"}}
                ]
            })
        elif variant == 'stacked':
            # 堆叠面积图
            data2 = self._generate_realistic_data(len(categories), 80, 250, "random")
            base.update({
                "legend": {"data": ["数据A", "数据B"], "bottom": 0},
                "xAxis": {"type": "category", "data": categories, "boundaryGap": False},
                "yAxis": {"type": "value"},
                "series": [
                    {"name": "数据A", "type": "line", "stack": "total", "data": data, "areaStyle": {"opacity": 0.2}},
                    {"name": "数据B", "type": "line", "stack": "total", "data": data2, "areaStyle": {"opacity": 0.2}}
                ]
            })
        else:
            # 基础折线图 (无面积填充)
            base.update({
                "xAxis": {"type": "category", "data": categories},
                "yAxis": {"type": "value"},
                "series": [{
                    "type": "line",
                    "data": data,
                    "smooth": True,
                    "symbol": "circle",
                    "symbolSize": 6,
                    "lineStyle": {"width": 2}
                }]
            })
        return base

    def _generate_pie_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成饼图"""
        # 常见分类
        labels = ["类别A", "类别B", "类别C", "类别D", "其他"]
        if "用户" in context: labels = ["活跃用户", "沉默用户", "新注册", "流失用户"]
        elif "告警" in context: labels = ["严重", "高危", "中危", "低危", "提示"]
        elif "资源" in context: labels = ["CPU", "内存", "磁盘", "网络", "其他"]

        data = []
        total = 100
        for i, label in enumerate(labels):
            if i == len(labels) - 1:
                val = total
            else:
                val = random.randint(5, max(10, total - (len(labels)-i)*5))
                total -= val
            data.append({"value": val, "name": label})

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item"},
            "legend": {"orient": "vertical", "left": "left"},
            "series": [{
                "name": title,
                "type": "pie",
                "radius": "50%",
                "data": data,
                "emphasis": {
                    "itemStyle": {
                        "shadowBlur": 10,
                        "shadowOffsetX": 0,
                        "shadowColor": "rgba(0, 0, 0, 0.5)"
                    }
                }
            }]
        }

    def _generate_radar_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成雷达图"""
        indicators = [
            {"name": "性能", "max": 100},
            {"name": "稳定性", "max": 100},
            {"name": "安全性", "max": 100},
            {"name": "易用性", "max": 100},
            {"name": "兼容性", "max": 100}
        ]

        data_val = [random.randint(60, 95) for _ in range(5)]

        return {
            "title": {"text": title},
            "tooltip": {},
            "radar": {"indicator": indicators},
            "series": [{
                "name": title,
                "type": "radar",
                "data": [{"value": data_val, "name": "综合评分"}]
            }]
        }

    def _generate_scatter_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成散点图"""
        data = []
        for _ in range(50):
            x = random.uniform(0, 100)
            # 生成带相关性的 y
            y = x * 0.8 + random.uniform(-20, 20) + 10
            data.append([round(x, 1), round(y, 1)])

        return {
            "title": {"text": title},
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{
                "symbolSize": 10,
                "data": data,
                "type": "scatter"
            }]
        }

    def _generate_gauge_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成仪表盘图表 - 适用于工业监控"""
        # 根据标题推断数据类型和范围
        value = random.uniform(60, 95)
        max_val = 100
        unit = "%"

        if "温度" in title:
            value = random.uniform(20, 80)
            max_val = 120
            unit = "°C"
        elif "压力" in title:
            value = random.uniform(0.5, 2.5)
            max_val = 4
            unit = "MPa"
        elif "速度" in title or "转速" in title:
            value = random.randint(800, 3000)
            max_val = 5000
            unit = "rpm"
        elif "效率" in title or "利用率" in title:
            value = random.uniform(75, 98)
            max_val = 100
            unit = "%"
        elif "产量" in title:
            value = random.randint(500, 2000)
            max_val = 3000
            unit = "件/h"

        # 随机选择仪表盘样式
        gauge_style = random.choice(['basic', 'progress', 'stage', 'multi'])

        if gauge_style == 'progress':
            # 进度式仪表盘
            return {
                "title": {"text": title, "left": "center", "top": "top"},
                "series": [{
                    "type": "gauge",
                    "startAngle": 180,
                    "endAngle": 0,
                    "min": 0,
                    "max": max_val,
                    "progress": {"show": True, "width": 18},
                    "axisLine": {"lineStyle": {"width": 18}},
                    "axisTick": {"show": False},
                    "splitLine": {"length": 15, "lineStyle": {"width": 2, "color": "#999"}},
                    "axisLabel": {"distance": 25, "color": "#999", "fontSize": 12},
                    "anchor": {"show": True, "showAbove": True, "size": 20, "itemStyle": {"borderWidth": 8}},
                    "title": {"show": False},
                    "detail": {
                        "valueAnimation": True,
                        "fontSize": 24,
                        "offsetCenter": [0, "70%"],
                        "formatter": f"{{value}} {unit}"
                    },
                    "data": [{"value": round(value, 1)}]
                }]
            }
        elif gauge_style == 'stage':
            # 分段式仪表盘 (绿-黄-红)
            return {
                "title": {"text": title, "left": "center"},
                "series": [{
                    "type": "gauge",
                    "min": 0,
                    "max": max_val,
                    "axisLine": {
                        "lineStyle": {
                            "width": 20,
                            "color": [
                                [0.3, "#67e0e3"],
                                [0.7, "#37a2da"],
                                [1, "#fd666d"]
                            ]
                        }
                    },
                    "pointer": {"itemStyle": {"color": "auto"}},
                    "axisTick": {"distance": -20, "length": 8, "lineStyle": {"color": "#fff", "width": 2}},
                    "splitLine": {"distance": -20, "length": 20, "lineStyle": {"color": "#fff", "width": 4}},
                    "axisLabel": {"color": "inherit", "distance": 30, "fontSize": 12},
                    "detail": {
                        "valueAnimation": True,
                        "formatter": f"{{value}} {unit}",
                        "color": "inherit",
                        "fontSize": 20
                    },
                    "data": [{"value": round(value, 1)}]
                }]
            }
        elif gauge_style == 'multi':
            # 多指针仪表盘
            value2 = random.uniform(value * 0.6, value * 0.9)
            return {
                "title": {"text": title, "left": "center"},
                "series": [{
                    "type": "gauge",
                    "min": 0,
                    "max": max_val,
                    "axisLine": {"lineStyle": {"width": 15}},
                    "pointer": {"length": "60%", "width": 6},
                    "detail": {"show": False},
                    "data": [
                        {"value": round(value, 1), "name": "当前值", "itemStyle": {"color": "#5470c6"}},
                        {"value": round(value2, 1), "name": "目标值", "itemStyle": {"color": "#91cc75"}}
                    ]
                }]
            }
        else:
            # 基础仪表盘
            return {
                "title": {"text": title, "left": "center"},
                "tooltip": {"formatter": "{b}: {c}" + unit},
                "series": [{
                    "type": "gauge",
                    "min": 0,
                    "max": max_val,
                    "progress": {"show": True},
                    "detail": {
                        "valueAnimation": True,
                        "formatter": f"{{value}} {unit}",
                        "fontSize": 20
                    },
                    "data": [{"value": round(value, 1), "name": title.replace("监控", "").replace("状态", "")}]
                }]
            }

    def _generate_liquid_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成水球图/液位图 - 使用普通仪表盘模拟（ECharts原生不支持水球图）"""
        value = random.uniform(40, 85)

        # 用环形进度模拟液位效果
        return {
            "title": {"text": title, "left": "center"},
            "series": [{
                "type": "gauge",
                "startAngle": 90,
                "endAngle": -270,
                "pointer": {"show": False},
                "progress": {
                    "show": True,
                    "overlap": False,
                    "roundCap": True,
                    "clip": False,
                    "itemStyle": {
                        "color": {
                            "type": "linear",
                            "x": 0, "y": 0, "x2": 0, "y2": 1,
                            "colorStops": [
                                {"offset": 0, "color": "#00b4d8"},
                                {"offset": 1, "color": "#0077b6"}
                            ]
                        }
                    }
                },
                "axisLine": {"lineStyle": {"width": 30, "color": [[1, "#e0e0e0"]]}},
                "splitLine": {"show": False},
                "axisTick": {"show": False},
                "axisLabel": {"show": False},
                "detail": {
                    "fontSize": 28,
                    "offsetCenter": [0, 0],
                    "formatter": "{value}%",
                    "color": "#0077b6"
                },
                "data": [{"value": round(value, 1)}]
            }]
        }

    def _generate_heatmap_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成热力图 - 适用于设备运行时段分析"""
        hours = [f"{i}:00" for i in range(24)]
        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        # 生成热力数据
        data = []
        for i, day in enumerate(days):
            for j, hour in enumerate(hours):
                # 工作时间热度高
                if 8 <= j <= 18 and i < 5:
                    value = random.randint(60, 100)
                else:
                    value = random.randint(5, 40)
                data.append([j, i, value])

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"position": "top"},
            "grid": {"height": "60%", "top": "15%"},
            "xAxis": {
                "type": "category",
                "data": hours,
                "splitArea": {"show": True},
                "axisLabel": {"interval": 2}
            },
            "yAxis": {
                "type": "category",
                "data": days,
                "splitArea": {"show": True}
            },
            "visualMap": {
                "min": 0,
                "max": 100,
                "calculable": True,
                "orient": "horizontal",
                "left": "center",
                "bottom": "5%",
                "inRange": {"color": ["#e0f3f8", "#abd9e9", "#74add1", "#4575b4", "#313695"]}
            },
            "series": [{
                "name": title,
                "type": "heatmap",
                "data": data,
                "label": {"show": False},
                "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0, 0, 0, 0.5)"}}
            }]
        }

    def _generate_sankey_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成桑基图 - 适用于工艺流程、物料流转"""
        # 工业流程节点示例
        nodes = [
            {"name": "原料输入"},
            {"name": "预处理"},
            {"name": "主加工"},
            {"name": "质检"},
            {"name": "合格品"},
            {"name": "返工"},
            {"name": "成品"},
            {"name": "包装"},
            {"name": "入库"}
        ]

        # 流转关系
        links = [
            {"source": "原料输入", "target": "预处理", "value": random.randint(800, 1000)},
            {"source": "预处理", "target": "主加工", "value": random.randint(750, 950)},
            {"source": "主加工", "target": "质检", "value": random.randint(700, 900)},
            {"source": "质检", "target": "合格品", "value": random.randint(600, 800)},
            {"source": "质检", "target": "返工", "value": random.randint(50, 150)},
            {"source": "返工", "target": "主加工", "value": random.randint(40, 120)},
            {"source": "合格品", "target": "成品", "value": random.randint(550, 750)},
            {"source": "成品", "target": "包装", "value": random.randint(500, 700)},
            {"source": "包装", "target": "入库", "value": random.randint(450, 650)}
        ]

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item", "triggerOn": "mousemove"},
            "series": [{
                "type": "sankey",
                "data": nodes,
                "links": links,
                "emphasis": {"focus": "adjacency"},
                "lineStyle": {"color": "gradient", "curveness": 0.5},
                "label": {"fontSize": 12}
            }]
        }

    def _generate_funnel_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成漏斗图 - 适用于生产转化、良品率分析"""
        # 生产流程数据
        data = [
            {"value": random.randint(900, 1000), "name": "投入原料"},
            {"value": random.randint(800, 900), "name": "加工完成"},
            {"value": random.randint(700, 850), "name": "质检通过"},
            {"value": random.randint(650, 800), "name": "包装完成"},
            {"value": random.randint(600, 750), "name": "成品入库"}
        ]

        # 排序确保漏斗形状
        data.sort(key=lambda x: x["value"], reverse=True)

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item", "formatter": "{b}: {c}"},
            "legend": {"data": [d["name"] for d in data], "bottom": 0},
            "series": [{
                "name": title,
                "type": "funnel",
                "left": "10%",
                "top": 60,
                "bottom": 60,
                "width": "80%",
                "min": 0,
                "max": 1000,
                "minSize": "0%",
                "maxSize": "100%",
                "sort": "descending",
                "gap": 2,
                "label": {"show": True, "position": "inside", "formatter": "{b}\n{c}"},
                "labelLine": {"length": 10, "lineStyle": {"width": 1}},
                "itemStyle": {"borderColor": "#fff", "borderWidth": 1},
                "emphasis": {"label": {"fontSize": 16}},
                "data": data
            }]
        }

    def _generate_treemap_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成矩形树图 - 适用于产能构成、资源占比"""
        data = [
            {
                "name": "生产线A",
                "value": random.randint(300, 500),
                "children": [
                    {"name": "设备1", "value": random.randint(80, 150)},
                    {"name": "设备2", "value": random.randint(70, 130)},
                    {"name": "设备3", "value": random.randint(60, 120)}
                ]
            },
            {
                "name": "生产线B",
                "value": random.randint(250, 400),
                "children": [
                    {"name": "设备4", "value": random.randint(70, 120)},
                    {"name": "设备5", "value": random.randint(60, 110)},
                    {"name": "设备6", "value": random.randint(50, 100)}
                ]
            },
            {
                "name": "生产线C",
                "value": random.randint(200, 350),
                "children": [
                    {"name": "设备7", "value": random.randint(60, 100)},
                    {"name": "设备8", "value": random.randint(50, 90)}
                ]
            }
        ]

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"formatter": "{b}: {c}"},
            "series": [{
                "type": "treemap",
                "data": data,
                "levels": [
                    {"itemStyle": {"borderWidth": 3, "borderColor": "#333", "gapWidth": 3}},
                    {"colorSaturation": [0.3, 0.6], "itemStyle": {"borderColorSaturation": 0.7, "gapWidth": 2, "borderWidth": 2}}
                ],
                "label": {"show": True, "formatter": "{b}"},
                "breadcrumb": {"show": False}
            }]
        }

    def _generate_gantt_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成甘特图 - 使用自定义柱状图模拟，适用于项目进度、生产排程"""
        import datetime

        # 生成任务数据
        tasks = [
            {"name": "需求分析", "start": 0, "duration": 5},
            {"name": "系统设计", "start": 3, "duration": 7},
            {"name": "数据库设计", "start": 5, "duration": 4},
            {"name": "前端开发", "start": 8, "duration": 12},
            {"name": "后端开发", "start": 8, "duration": 15},
            {"name": "接口联调", "start": 18, "duration": 5},
            {"name": "系统测试", "start": 22, "duration": 6},
            {"name": "部署上线", "start": 27, "duration": 3}
        ]

        # 随机调整时间（增加差异性）
        for task in tasks:
            task["start"] += random.randint(-1, 2)
            task["duration"] += random.randint(-1, 2)
            task["duration"] = max(2, task["duration"])

        categories = [t["name"] for t in tasks]

        # 构建series数据：使用堆叠柱状图模拟甘特图
        # 第一个系列是透明的"偏移"，第二个系列是实际任务条
        offset_data = [t["start"] for t in tasks]
        duration_data = [t["duration"] for t in tasks]

        # 计算进度百分比（随机）
        progress_data = [random.randint(60, 100) if i < len(tasks) - 2 else random.randint(10, 50) for i in range(len(tasks))]

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "shadow"},
                "formatter": "function(params) { return params[1].name + '<br/>开始: 第' + params[0].value + '天<br/>工期: ' + params[1].value + '天'; }"
            },
            "grid": {"left": "15%", "right": "10%", "top": "15%", "bottom": "10%"},
            "xAxis": {
                "type": "value",
                "name": "天数",
                "min": 0,
                "max": 35,
                "axisLabel": {"formatter": "第{value}天"}
            },
            "yAxis": {
                "type": "category",
                "data": categories,
                "inverse": True,
                "axisLine": {"show": False},
                "axisTick": {"show": False}
            },
            "series": [
                {
                    "name": "offset",
                    "type": "bar",
                    "stack": "total",
                    "silent": True,
                    "itemStyle": {"color": "transparent"},
                    "data": offset_data
                },
                {
                    "name": "duration",
                    "type": "bar",
                    "stack": "total",
                    "data": duration_data,
                    "label": {
                        "show": True,
                        "position": "inside",
                        "formatter": "{c}天",
                        "fontSize": 10,
                        "color": "#fff"
                    },
                    "itemStyle": {
                        "borderRadius": [0, 4, 4, 0],
                        "color": {
                            "type": "linear",
                            "x": 0, "y": 0, "x2": 1, "y2": 0,
                            "colorStops": [
                                {"offset": 0, "color": "#5470c6"},
                                {"offset": 1, "color": "#91cc75"}
                            ]
                        }
                    },
                    "barWidth": "60%"
                }
            ]
        }

    def _generate_graph_chart(self, title: str, context: str) -> Dict[str, Any]:
        """生成关系图/流程图 - 适用于业务流程、网络拓扑、组织关系"""

        # 根据标题判断类型
        if "拓扑" in title or "网络" in title:
            return self._generate_topology_graph(title)
        elif "组织" in title or "人员" in title:
            return self._generate_org_graph(title)
        else:
            return self._generate_flow_graph(title)

    def _generate_flow_graph(self, title: str) -> Dict[str, Any]:
        """生成业务流程图"""
        nodes = [
            {"name": "开始", "x": 50, "y": 150, "symbolSize": 40, "category": 0},
            {"name": "提交申请", "x": 150, "y": 150, "symbolSize": 50, "category": 1},
            {"name": "初审", "x": 250, "y": 100, "symbolSize": 45, "category": 1},
            {"name": "复审", "x": 350, "y": 100, "symbolSize": 45, "category": 1},
            {"name": "审批", "x": 450, "y": 150, "symbolSize": 50, "category": 2},
            {"name": "驳回", "x": 300, "y": 220, "symbolSize": 40, "category": 3},
            {"name": "归档", "x": 550, "y": 150, "symbolSize": 45, "category": 2},
            {"name": "结束", "x": 650, "y": 150, "symbolSize": 40, "category": 0}
        ]

        links = [
            {"source": "开始", "target": "提交申请"},
            {"source": "提交申请", "target": "初审"},
            {"source": "初审", "target": "复审"},
            {"source": "复审", "target": "审批"},
            {"source": "审批", "target": "归档"},
            {"source": "归档", "target": "结束"},
            {"source": "初审", "target": "驳回", "lineStyle": {"type": "dashed", "color": "#ee6666"}},
            {"source": "复审", "target": "驳回", "lineStyle": {"type": "dashed", "color": "#ee6666"}},
            {"source": "驳回", "target": "提交申请", "lineStyle": {"type": "dashed", "color": "#ee6666"}}
        ]

        categories = [
            {"name": "起止节点", "itemStyle": {"color": "#91cc75"}},
            {"name": "处理节点", "itemStyle": {"color": "#5470c6"}},
            {"name": "审批节点", "itemStyle": {"color": "#fac858"}},
            {"name": "异常节点", "itemStyle": {"color": "#ee6666"}}
        ]

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item"},
            "legend": {"data": [c["name"] for c in categories], "bottom": 0},
            "series": [{
                "type": "graph",
                "layout": "none",
                "symbolSize": 50,
                "roam": True,
                "label": {"show": True, "fontSize": 11},
                "edgeSymbol": ["circle", "arrow"],
                "edgeSymbolSize": [4, 10],
                "edgeLabel": {"fontSize": 10},
                "data": nodes,
                "links": links,
                "categories": categories,
                "lineStyle": {"opacity": 0.9, "width": 2, "curveness": 0.1}
            }]
        }

    def _generate_topology_graph(self, title: str) -> Dict[str, Any]:
        """生成网络拓扑图"""
        nodes = [
            {"name": "核心交换机", "symbolSize": 60, "category": 0},
            {"name": "防火墙", "symbolSize": 50, "category": 1},
            {"name": "Web服务器1", "symbolSize": 40, "category": 2},
            {"name": "Web服务器2", "symbolSize": 40, "category": 2},
            {"name": "数据库主", "symbolSize": 45, "category": 3},
            {"name": "数据库从", "symbolSize": 40, "category": 3},
            {"name": "缓存服务器", "symbolSize": 40, "category": 2},
            {"name": "文件服务器", "symbolSize": 40, "category": 2}
        ]

        links = [
            {"source": "核心交换机", "target": "防火墙", "value": 100},
            {"source": "防火墙", "target": "Web服务器1", "value": 80},
            {"source": "防火墙", "target": "Web服务器2", "value": 80},
            {"source": "Web服务器1", "target": "数据库主", "value": 60},
            {"source": "Web服务器2", "target": "数据库主", "value": 60},
            {"source": "数据库主", "target": "数据库从", "value": 40},
            {"source": "Web服务器1", "target": "缓存服务器", "value": 50},
            {"source": "Web服务器2", "target": "缓存服务器", "value": 50},
            {"source": "核心交换机", "target": "文件服务器", "value": 30}
        ]

        categories = [
            {"name": "网络设备", "itemStyle": {"color": "#5470c6"}},
            {"name": "安全设备", "itemStyle": {"color": "#ee6666"}},
            {"name": "应用服务器", "itemStyle": {"color": "#91cc75"}},
            {"name": "数据库", "itemStyle": {"color": "#fac858"}}
        ]

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item"},
            "legend": {"data": [c["name"] for c in categories], "bottom": 0},
            "series": [{
                "type": "graph",
                "layout": "force",
                "force": {"repulsion": 500, "edgeLength": [100, 200]},
                "roam": True,
                "label": {"show": True, "fontSize": 10},
                "data": nodes,
                "links": links,
                "categories": categories,
                "lineStyle": {"opacity": 0.8, "width": 2}
            }]
        }

    def _generate_org_graph(self, title: str) -> Dict[str, Any]:
        """生成组织关系图"""
        nodes = [
            {"name": "总经理", "symbolSize": 60, "category": 0},
            {"name": "技术总监", "symbolSize": 50, "category": 1},
            {"name": "产品总监", "symbolSize": 50, "category": 1},
            {"name": "运营总监", "symbolSize": 50, "category": 1},
            {"name": "研发经理", "symbolSize": 40, "category": 2},
            {"name": "测试经理", "symbolSize": 40, "category": 2},
            {"name": "产品经理", "symbolSize": 40, "category": 2},
            {"name": "运营经理", "symbolSize": 40, "category": 2}
        ]

        links = [
            {"source": "总经理", "target": "技术总监"},
            {"source": "总经理", "target": "产品总监"},
            {"source": "总经理", "target": "运营总监"},
            {"source": "技术总监", "target": "研发经理"},
            {"source": "技术总监", "target": "测试经理"},
            {"source": "产品总监", "target": "产品经理"},
            {"source": "运营总监", "target": "运营经理"}
        ]

        categories = [
            {"name": "高管", "itemStyle": {"color": "#5470c6"}},
            {"name": "总监", "itemStyle": {"color": "#91cc75"}},
            {"name": "经理", "itemStyle": {"color": "#fac858"}}
        ]

        return {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item"},
            "legend": {"data": [c["name"] for c in categories], "bottom": 0},
            "series": [{
                "type": "graph",
                "layout": "force",
                "force": {"repulsion": 400, "gravity": 0.1, "edgeLength": [80, 150]},
                "roam": True,
                "label": {"show": True, "fontSize": 11},
                "data": nodes,
                "links": links,
                "categories": categories,
                "lineStyle": {"opacity": 0.8, "width": 2}
            }]
        }

    def _generate_realistic_data(self, count: int, min_val: int, max_val: int, trend: str = "random") -> List[int]:
        """
        生成真实感数据 (基于简化的随机漫步)
        支持行业规则修正
        """
        # 尝试从行业配置获取数据规则 (Simple heuristic override)
        # 例如: 如果是 "forestry" (林业), 数值可能较大 (蓄积量) 或较小 (增长率)
        # 这里做一个简单的倍率调整演示

        multiplier = 1.0
        if self.industry_key == 'forestry' and max_val > 1000:
             multiplier = 1.5 # 林业数据通常较大
        elif self.industry_key == 'healthcare' and '人' in str(min_val): # 假设 context 传不进来，这里比较难判断
             pass

        data = []
        current = random.randint(min_val, max_val)

        for i in range(count):
            # 波动幅度
            step = (max_val - min_val) * 0.1
            delta = random.uniform(-step, step)

            # 趋势倾向
            if trend == "up":
                delta += step * 0.2
            elif trend == "down":
                delta -= step * 0.2

            current += delta

            # 边界限制
            current = max(min_val, min(max_val, current))
            data.append(int(current * multiplier))

        return data
