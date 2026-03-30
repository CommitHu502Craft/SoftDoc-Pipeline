"""
配置模块测试
"""
import pytest
import json
import tempfile
import shutil
from pathlib import Path
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestApiConfig:
    """API配置测试"""

    def test_load_api_config_exists(self):
        """测试加载已存在的配置文件"""
        from config import load_api_config, API_CONFIG_PATH

        if API_CONFIG_PATH.exists():
            config = load_api_config()
            assert "current_provider" in config
            assert "providers" in config

    def test_get_current_provider(self):
        """测试获取当前提供商"""
        from config import get_current_provider, load_api_config

        provider = get_current_provider()
        config = load_api_config()
        providers = config.get("providers", {})
        assert provider in providers or provider == "deepseek"

    def test_get_provider_config(self):
        """测试获取提供商配置"""
        from config import get_provider_config

        config = get_provider_config("deepseek")
        assert "api_key" in config or config == {}

    def test_base_dir_exists(self):
        """测试BASE_DIR路径存在"""
        from config import BASE_DIR

        assert BASE_DIR.exists()
        assert BASE_DIR.is_dir()

    def test_output_dir_created(self):
        """测试OUTPUT_DIR目录已创建"""
        from config import OUTPUT_DIR

        assert OUTPUT_DIR.exists()
        assert OUTPUT_DIR.is_dir()


class TestDataConfig:
    """数据配置测试"""

    def test_data_config_file_exists(self):
        """测试data_config.json文件存在"""
        from config import BASE_DIR

        data_config_path = BASE_DIR / "config" / "data_config.json"
        assert data_config_path.exists()

    def test_data_config_valid_json(self):
        """测试data_config.json是有效的JSON"""
        from config import BASE_DIR

        data_config_path = BASE_DIR / "config" / "data_config.json"
        with open(data_config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        assert "admin_names" in config
        assert isinstance(config["admin_names"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
