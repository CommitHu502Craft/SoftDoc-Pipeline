import json
import os
import random
import logging
from typing import Dict, Any, List, Optional

class IndustryAdapter:
    """
    行业适配器模块
    负责识别项目所属行业，并提供行业特定的配置、术语、菜单和图表数据。
    """

    def __init__(self, config_path: str = "config/industry_profiles.json"):
        self.logger = logging.getLogger(__name__)
        self.config_path = config_path
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> Dict[str, Any]:
        """加载行业配置文件"""
        try:
            if not os.path.exists(self.config_path):
                self.logger.warning(f"Industry config not found at {self.config_path}, using empty profiles.")
                return {}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("profiles", {})
        except Exception as e:
            self.logger.error(f"Failed to load industry profiles: {str(e)}")
            return {}

    def detect_industry(self, project_name: str) -> str:
        """
        基于项目名称探测行业

        Args:
            project_name: 项目名称

        Returns:
            industry_key: 识别出的行业key，未识别则返回 "general"
        """
        if not project_name:
            return "general"

        project_name_lower = project_name.lower()

        # 遍历所有配置的行业
        for industry_key, profile in self.profiles.items():
            if industry_key == "general":
                continue

            aliases = profile.get("aliases", [])
            for alias in aliases:
                if alias.lower() in project_name_lower:
                    self.logger.info(f"Industry detected: {industry_key} (matched alias: {alias})")
                    return industry_key

        self.logger.info("No specific industry detected, using general profile.")
        return "general"

    def get_profile(self, industry_key: str) -> Dict[str, Any]:
        """获取特定行业的完整配置，如果不存在则返回通用配置"""
        return self.profiles.get(industry_key, self.profiles.get("general", {}))

    def enhance_genome(self, genome: Dict[str, Any]) -> Dict[str, Any]:
        """
        将行业特征注入到项目基因中

        Args:
            genome: 原始项目基因

        Returns:
            enhanced_genome: 注入了行业上下文的基因
        """
        project_name = genome.get("name", "")
        industry_key = self.detect_industry(project_name)
        profile = self.get_profile(industry_key)

        # 注入行业上下文
        industry_context = {
            "key": industry_key,
            "name": profile.get("name", "通用系统"),
            "description": profile.get("description", ""),
            "terminology": profile.get("terminology", {}),
            "color_scheme": profile.get("color_scheme", {}),
            # 标记为已注入
            "industry_adapted": True
        }

        genome["industry_context"] = industry_context

        # 如果基因中还没有配色方案，使用行业的
        if "design_style" not in genome:
            genome["design_style"] = {}

        if profile.get("color_scheme"):
            genome["design_style"]["primary_color"] = profile["color_scheme"].get("primary")
            genome["design_style"]["secondary_color"] = profile["color_scheme"].get("secondary")

        return genome

    def get_industry_prompt(self, industry_key: str) -> str:
        """生成用于 LLM 的行业背景 Prompt 片段"""
        profile = self.get_profile(industry_key)
        if not profile:
            return ""

        term_str = ", ".join([f"{k}->{v}" for k, v in profile.get("terminology", {}).items()])

        # 构建推荐菜单字符串
        menus = profile.get("menu_structure", [])
        menu_str = ""
        if menus:
            menu_items = [f"- {m.get('title')} ({', '.join(m.get('children', [])[:3])})" for m in menus]
            menu_str = "\nRecommended Menus:\n" + "\n".join(menu_items)

        prompt = f"""
[INDUSTRY CONTEXT]
Target Industry: {profile.get('name')}
Description: {profile.get('description')}
Terminology Mapping: {term_str}
Design Style: Professional, specific to {industry_key} domain.{menu_str}
Make sure all generated content (text, data, labels) reflects this industry context strictly.
"""
        return prompt

    def get_menu_structure(self, industry_key: str) -> List[Dict[str, Any]]:
        """获取行业的菜单结构"""
        profile = self.get_profile(industry_key)
        return profile.get("menu_structure", [])

    def get_chart_templates(self, industry_key: str) -> List[Dict[str, Any]]:
        """获取行业的图表模板"""
        profile = self.get_profile(industry_key)
        return profile.get("chart_templates", [])

# 单例实例
_adapter_instance = None

def get_adapter():
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = IndustryAdapter()
    return _adapter_instance
