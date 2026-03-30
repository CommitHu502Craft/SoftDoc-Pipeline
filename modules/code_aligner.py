"""
业务关键词动态注入模块
根据项目规划中的行业词汇，将通用代码模板转换为行业特定代码
"""
import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodeAligner:
    """代码对齐器：将通用模板代码转换为行业特定代码"""
    
    # 通用模板词 -> 占位符映射
    GENERIC_PATTERNS = {
        # 类名
        "GenericController": "{controller_name}",
        "DataItem": "{data_class}",
        "BaseService": "{service_name}",
        "GenericRepository": "{repository_name}",
        "GenericEntity": "{entity_name}",
        
        # 方法名
        "process_record": "{main_action}",
        "get_data": "{get_action}",
        "save_item": "{save_action}",
        "delete_record": "{delete_action}",
        "update_item": "{update_action}",
        
        # 注释占位符
        "通用模块": "{module_desc}",
        "数据处理": "{data_desc}",
        "业务逻辑": "{business_desc}",
    }
    
    # 行业词库：根据项目名称关键词匹配
    INDUSTRY_MAPPINGS = {
        "健康": {
            "controller_name": "HealthController",
            "data_class": "HealthRecord",
            "service_name": "HealthService",
            "repository_name": "HealthRepository",
            "entity_name": "HealthEntity",
            "main_action": "monitor_health",
            "get_action": "get_health_data",
            "save_action": "save_health_record",
            "delete_action": "delete_health_record",
            "update_action": "update_health_status",
            "module_desc": "健康监测模块",
            "data_desc": "健康数据采集",
            "business_desc": "健康评估逻辑",
        },
        "林业": {
            "controller_name": "ForestController",
            "data_class": "TreeData",
            "service_name": "ForestService",
            "repository_name": "ForestRepository",
            "entity_name": "ForestEntity",
            "main_action": "track_growth",
            "get_action": "get_forest_data",
            "save_action": "save_tree_record",
            "delete_action": "delete_tree_record",
            "update_action": "update_growth_status",
            "module_desc": "林区监测模块",
            "data_desc": "林业数据采集",
            "business_desc": "生长分析逻辑",
        },
        "预警": {
            "controller_name": "AlertController",
            "data_class": "AlertRecord",
            "service_name": "AlertService",
            "repository_name": "AlertRepository",
            "entity_name": "AlertEntity",
            "main_action": "trigger_alert",
            "get_action": "get_alert_list",
            "save_action": "save_alert",
            "delete_action": "dismiss_alert",
            "update_action": "update_alert_level",
            "module_desc": "预警管理模块",
            "data_desc": "预警数据处理",
            "business_desc": "风险评估逻辑",
        },
        "监测": {
            "controller_name": "MonitorController",
            "data_class": "MonitorData",
            "service_name": "MonitorService",
            "repository_name": "MonitorRepository",
            "entity_name": "MonitorEntity",
            "main_action": "collect_metrics",
            "get_action": "get_monitor_data",
            "save_action": "save_metrics",
            "delete_action": "clear_old_data",
            "update_action": "update_threshold",
            "module_desc": "实时监测模块",
            "data_desc": "监测数据采集",
            "business_desc": "阈值判断逻辑",
        },
        "管理": {
            "controller_name": "ManageController",
            "data_class": "ManageItem",
            "service_name": "ManageService",
            "repository_name": "ManageRepository",
            "entity_name": "ManageEntity",
            "main_action": "process_task",
            "get_action": "get_items",
            "save_action": "save_item",
            "delete_action": "remove_item",
            "update_action": "modify_item",
            "module_desc": "综合管理模块",
            "data_desc": "业务数据管理",
            "business_desc": "流程控制逻辑",
        },
    }
    
    def __init__(self, plan_path: str):
        """
        初始化代码对齐器
        
        Args:
            plan_path: project_plan.json 路径
        """
        self.plan_path = Path(plan_path)
        
        with open(self.plan_path, 'r', encoding='utf-8') as f:
            self.plan = json.load(f)
        
        self.project_name = self.plan.get("project_name", "通用系统")
        self.keywords = self._extract_keywords()
        self.replacements = self._build_replacements()
    
    def _extract_keywords(self) -> List[str]:
        """从项目规划中提取行业关键词"""
        keywords = []
        
        # 从项目名称提取
        keywords.append(self.project_name)
        
        # 从系统简介提取
        intro = self.plan.get("project_intro", {})
        if intro.get("main_features"):
            keywords.extend(intro["main_features"])
        
        # 从菜单标题提取
        for menu in self.plan.get("menu_list", []):
            keywords.append(menu.get("title", ""))
        
        return keywords
    
    def _build_replacements(self) -> Dict[str, str]:
        """根据关键词构建替换字典"""
        replacements = {}
        
        # 默认使用通用映射
        default_mapping = {
            "controller_name": "BusinessController",
            "data_class": "BusinessData",
            "service_name": "BusinessService",
            "repository_name": "BusinessRepository",
            "entity_name": "BusinessEntity",
            "main_action": "process_business",
            "get_action": "get_business_data",
            "save_action": "save_business_data",
            "delete_action": "delete_business_data",
            "update_action": "update_business_data",
            "module_desc": f"{self.project_name}核心模块",
            "data_desc": f"{self.project_name}数据处理",
            "business_desc": f"{self.project_name}业务逻辑",
        }
        
        # 根据项目关键词匹配行业映射
        for keyword_text in self.keywords:
            for industry_key, industry_map in self.INDUSTRY_MAPPINGS.items():
                if industry_key in keyword_text:
                    default_mapping.update(industry_map)
                    logger.info(f"匹配到行业词库: {industry_key}")
                    break
        
        # 构建最终替换字典
        for generic, placeholder in self.GENERIC_PATTERNS.items():
            key = placeholder.strip("{}")
            if key in default_mapping:
                replacements[generic] = default_mapping[key]
        
        return replacements
    
    def align_code(self, template_dir: str, output_dir: str) -> List[str]:
        """
        对齐代码：将模板目录中的代码进行关键词替换
        
        Args:
            template_dir: 模板代码目录
            output_dir: 输出目录
            
        Returns:
            处理后的文件路径列表
        """
        template_path = Path(template_dir)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        processed_files = []
        
        # 支持的代码文件扩展名
        code_extensions = {'.py', '.java', '.js', '.ts', '.cpp', '.c', '.h', '.cs', '.go', '.rs'}
        
        for file_path in template_path.rglob("*"):
            if file_path.is_file() and file_path.suffix in code_extensions:
                # 读取原始内容
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    continue
                
                # 执行替换
                aligned_content = self._apply_replacements(content)
                
                # 注入项目信息注释
                aligned_content = self._inject_header(aligned_content, file_path.name)
                
                # 保存到输出目录
                relative_path = file_path.relative_to(template_path)
                out_file = output_path / relative_path
                out_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(out_file, 'w', encoding='utf-8') as f:
                    f.write(aligned_content)
                
                processed_files.append(str(out_file))
                logger.info(f"已处理: {relative_path}")
        
        return processed_files
    
    def _apply_replacements(self, content: str) -> str:
        """应用关键词替换"""
        for old, new in self.replacements.items():
            content = re.sub(re.escape(old), new, content)
        return content
    
    def _inject_header(self, content: str, filename: str) -> str:
        """注入项目信息头部注释"""
        header = f'''# ============================================================
# {self.project_name}
# 模块: {filename}
# 版本: V1.0.0
# 描述: {self.plan.get("project_intro", {}).get("overview", "业务功能模块")}
# ============================================================

'''
        return header + content


def align_project_code(plan_path: str, template_dir: str, output_dir: str) -> List[str]:
    """
    便捷函数：对齐项目代码
    
    Args:
        plan_path: project_plan.json 路径
        template_dir: 模板代码目录
        output_dir: 输出目录
        
    Returns:
        处理后的文件列表
    """
    aligner = CodeAligner(plan_path)
    return aligner.align_code(template_dir, output_dir)
