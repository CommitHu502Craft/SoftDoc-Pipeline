"""
HTML生成器模块测试
"""
import pytest
import json
import tempfile
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestHTMLGenerator:
    """HTML生成器测试"""

    def test_import_module(self):
        """测试模块可以正常导入"""
        from modules.html_generator import generate_html_pages
        assert callable(generate_html_pages)

    def test_generate_with_valid_json(self, tmp_path):
        """测试使用有效JSON生成HTML"""
        if os.getenv("RUN_LIVE_LLM_TESTS", "0") != "1":
            pytest.skip("默认跳过在线 LLM 集成测试（设置 RUN_LIVE_LLM_TESTS=1 可启用）")
        from modules.html_generator import generate_html_pages
        from config import BASE_DIR

        # 检查是否有测试用的 project_plan.json（项目专属目录）
        candidates = sorted((BASE_DIR / "output").glob("*/project_plan.json"))
        if not candidates:
            pytest.skip("需要 output/<项目名>/project_plan.json 进行测试")
        test_json = candidates[0]

        # 使用临时目录作为输出
        output_dir = tmp_path / "test_html_output"
        result = generate_html_pages(test_json, output_dir)

        assert result.exists()
        assert result.is_dir()


class TestScreenshotEngine:
    """截图引擎测试"""

    def test_import_module(self):
        """测试模块可以正常导入"""
        try:
            from modules.screenshot_engine import capture_screenshots_sync
        except ImportError:
            pytest.skip("playwright 未安装，跳过截图引擎导入测试")
        assert callable(capture_screenshots_sync)


class TestDocumentGenerator:
    """文档生成器测试"""

    def test_import_module(self):
        """测试模块可以正常导入"""
        from modules.document_generator import generate_document
        assert callable(generate_document)


class TestCodeGenerator:
    """代码生成器测试"""

    def test_import_module(self):
        """测试模块可以正常导入"""
        from modules.code_generator import generate_code_from_plan
        assert callable(generate_code_from_plan)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
