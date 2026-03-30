"""
GUI 配置管理器
负责读写GUI相关配置，包括窗口状态、用户偏好等
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional

class ConfigManager:
    """GUI配置管理器"""
    
    def __init__(self, config_file: str = "gui_config.json"):
        self.base_dir = Path(__file__).parent.parent.parent
        self.config_path = self.base_dir / config_file
        self.config: Dict[str, Any] = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load config: {e}")
                return self._default_config()
        return self._default_config()
    
    def _default_config(self) -> Dict[str, Any]:
        """默认配置"""
        return {
            "theme": "dark",  # 'light' or 'dark'
            "window_geometry": {
                "width": 1200,
                "height": 800,
                "x": 100,
                "y": 100
            },
            "last_api_provider": "custom",
            "auto_refresh": True,
            "refresh_interval": 5,  # 秒
            "batch_max_parallel": 2,
            # 规格评审是否自动确认（默认开启，避免 full_pipeline 在 spec 后人工阻断）
            "auto_confirm_spec_review": True,
            # 代码质量闸门默认参数（会写入 project_plan.code_generation_config）
            "code_quality_profile": "economy",  # economy | high_constraint
            "code_novelty_threshold": 0.35,
            "code_file_novelty_budget": 0.35,
            "code_project_novelty_threshold": 0.32,
            "code_rewrite_candidates": 1,
            "code_max_rewrite_rounds": 1,
            "code_heavy_search_ratio": 0.20,
            "code_enable_project_novelty_gate": False,
            "code_max_risky_files": 8,
            "code_max_syntax_fail_files": 4,
            "code_min_ai_line_ratio": 0.10,
            "code_enforce_file_gate": False,
            "code_enforce_file_gate_on_obfuscation": False,
            "code_max_failed_files": 8,
            "code_max_llm_attempts_per_file": 2,
            "code_llm_text_retries": 1,
            "code_max_total_llm_calls": 12,
            "code_max_total_llm_failures": 4,
            "code_disable_llm_on_budget_exhausted": True,
            "code_disable_llm_on_failures": True,
            "code_enable_embedding_similarity": False,
            "code_embedding_similarity_weight": 0.15,
            "code_embedding_max_chars": 2400,
            # 代码阶段可单独指定 API 提供商/模型；留空表示跟随全局 API 配置
            "code_llm_provider_override": "",
            "code_llm_model_override": "",
        }
    
    def save(self):
        """保存配置到文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save config: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置项"""
        self.config[key] = value
        self.save()

# 全局配置实例
config_manager = ConfigManager()
