"""
设计决策引擎 (Design Decision Engine)
V2.2 核心组件：负责生成高层视觉设计决策 (JSON)，而非直接生成代码。
解决"美观"与"稳定"的冲突：LLM 只负责创意决策，Python 负责代码生成。
"""
import json
import logging
from typing import Dict, Any, List
from core.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

class DesignDecisionEngine:
    """
    负责调用 LLM 生成视觉设计参数
    """
    def __init__(self, api_key: str = None):
        self.client = DeepSeekClient(api_key=api_key)

    def generate_decision(self, genome: Dict[str, Any], project_name: str) -> Dict[str, Any]:
        """
        根据项目背景生成设计决策

        Returns:
            Dict: 包含颜色、字体、圆角、阴影等设计参数的字典
        """
        import random

        business_context = genome.get("business_context", [])
        visual_style = genome.get("visual_style", "Enterprise")
        context_str = ", ".join(business_context[:5])

        # 设计方向收敛为“产品工作台界面”，避免传统后台模板与展示稿。
        # 注意：只使用浅色主题，避免暗色模式导致截图异常。
        design_directions = [
            "命令工作台风 (浅底+线框、命令条与工具画布并存、强调操作语义)",
            "实验控制台风 (低饱和冷色、分区明显、优先状态流与步骤面板)",
            "叙事工具面风 (顶部叙事条+下方工具区，避免纯表格堆叠)",
            "工业分析舱风 (线性边框、少圆角、强调监测轨迹与处理留痕)",
            "运营图谱风 (节点关系+流程时间线+结构化明细并列)",
        ]
        chosen_direction = random.choice(design_directions)

        # 随机选择布局模式（偏工作台，不是“后台首页模板”）
        grid_patterns = [
            "command-workbench (命令条 + 双栏工具面 + 状态侧栏)",
            "canvas-split (叙事说明区 + 主操作画布 + 证据条)",
            "atlas-hub (指标带 + 图谱区 + 事件流)",
            "lab-console (控制条 + 操作区 + 回放区)",
            "caseboard-layout (对象列表 + 详情抽屉 + 轨迹面板)",
        ]
        chosen_grid = random.choice(grid_patterns)

        prompt = f"""
你是企业级 B 端产品的视觉系统设计师。
请为项目 "{project_name}" 生成可落地、可截图、可读性高的设计参数 JSON。

### 项目背景
行业关键词: {context_str}
基础风格: {visual_style}

### 设计方向 (必须遵循)
**{chosen_direction}**

### 布局模式
**{chosen_grid}**

### 约束
- 禁止 PPT/宣传页风格（巨型标题、海报式背景、过强渐变、过重阴影、夸张动效）。
- 禁止传统“管理后台首页模板”关键词与结构（例如 Dashboard / Overview、Admin、系统菜单 + 大表格直铺）。
- 必须是浅色主题，保证打印和截图可读性。
- 优先 `flat/bordered/elevated` 卡片，不要玻璃拟态和神经拟态。
- 动效仅允许 `none` 或 `subtle`。
- 结果要有明确的“工具工作台”感，不要只给一排指标卡+一张大表。

### 输出
返回纯 JSON，字段如下：

{{
  "theme_name": "主题名称",
  "primary_color": "主色（低饱和）",
  "secondary_color": "导航/侧栏色",
  "accent_color": "强调色",
  "background_color": "页面背景色（浅色）",
  "text_color": "主文本颜色",
  "border_radius": "圆角 ('4px'/'6px'/'8px'/'12px')",
  "shadow_style": "阴影 ('none'/'subtle'/'soft')",
  "card_style": "卡片 ('flat'/'bordered'/'elevated')",
  "font_heading": "标题字体（中文优先）",
  "sidebar_style": "侧栏 ('solid'/'light')",
  "density": "密度 ('compact'/'normal'/'spacious')",
  "grid_pattern": "{chosen_grid}",
  "icon_style": "图标风格 ('outline'/'filled'/'duotone')",
  "animation_level": "动效级别 ('none'/'subtle')"
}}
"""
        try:
            decision = self.client.generate_json(prompt)
            # 简单校验
            required_keys = ["primary_color", "border_radius", "card_style"]
            for k in required_keys:
                if k not in decision:
                    raise ValueError(f"Missing key: {k}")
            return decision

        except Exception as e:
            logger.error(f"设计决策生成失败: {e}")
            return self._get_fallback_decision()

    def _get_fallback_decision(self) -> Dict[str, Any]:
        """兜底设计决策"""
        return {
            "theme_name": "Reliable Enterprise",
            "primary_color": "#2563eb",
            "secondary_color": "#1e293b",
            "accent_color": "#f43f5e",
            "background_color": "#f8fafc",
            "text_color": "#0f172a",
            "border_radius": "6px",
            "shadow_style": "subtle",
            "card_style": "flat",
            "font_heading": "Noto Sans SC",
            "sidebar_style": "solid",
            "density": "normal"
        }
