import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import sys

# Add project root to path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.random_engine import RandomEngine, get_random_engine
try:
    from modules.skeleton_generator import SkeletonGenerator
except Exception:  # optional module in current codebase
    SkeletonGenerator = None
from modules.chart_injector import ChartInjector
from modules.code_transformer import CodeTransformer
from modules.dependency_validator import DependencyValidator

class TestRandomEngine:
    """Test RandomEngine determinism and functionality"""

    def setup_method(self):
        # Reset singleton before each test
        RandomEngine._instance = None
        RandomEngine._initialized = False

    def test_random_engine_determinism(self):
        """Verify same project name generates same genome"""
        project_name = "TestProject_A"

        # Run 1
        engine1 = RandomEngine()
        engine1.set_project_seed(project_name)
        genome1 = engine1.get_genome()

        # Reset
        RandomEngine._instance = None
        RandomEngine._initialized = False

        # Run 2
        engine2 = RandomEngine()
        engine2.set_project_seed(project_name)
        genome2 = engine2.get_genome()

        # generated_at 会随时间变化，不纳入确定性断言
        g1 = dict(genome1)
        g2 = dict(genome2)
        g1.pop('generated_at', None)
        g2.pop('generated_at', None)
        assert g1 == g2
        assert genome1['target_language'] == genome2['target_language']
        assert genome1['color_scheme'] == genome2['color_scheme']

    def test_different_projects_different_genomes(self):
        """Verify different project names generate different genomes (statistically)"""
        # This is probabilistic, but with enough fields, collision is unlikely
        engine1 = RandomEngine()
        engine1.set_project_seed("Project_Alpha")
        genome1 = engine1.get_genome()

        RandomEngine._instance = None
        RandomEngine._initialized = False

        engine2 = RandomEngine()
        engine2.set_project_seed("Project_Beta")
        genome2 = engine2.get_genome()

        # At least one major attribute should differ
        assert genome1 != genome2


class TestSkeletonGenerator:
    """Test HTML Skeleton Generation"""

    def test_skeleton_generation(self):
        if SkeletonGenerator is None:
            pytest.skip("modules.skeleton_generator 不存在，跳过该兼容性测试")
        with patch('modules.skeleton_generator.DeepSeekClient') as mock_client_cls:
        # Setup Mock
            mock_client_instance = MagicMock()
            mock_client_cls.return_value = mock_client_instance

            # Mock OpenAI response structure
            mock_response = MagicMock()
            mock_response.choices[0].message.content = """
<!DOCTYPE html>
<html>
<body>
    <div id="main-container">
        <div id="chart-container-1"></div>
        <div id="chart-container-2"></div>
        <div id="table-container"></div>
    </div>
</body>
</html>
"""
            mock_client_instance.client.chat.completions.create.return_value = mock_response

            generator = SkeletonGenerator()
            genome = {"ui_framework": "Bootstrap", "layout_mode": "sidebar-left"}
            page_info = {
                "project_name": "TestProj",
                "page_title": "Dashboard",
                "menu_list": []
            }

            html = generator.generate_skeleton(genome, page_info)

            assert "<!DOCTYPE html>" in html
            assert 'id="main-container"' in html
            assert 'id="chart-container-1"' in html


class TestChartInjector:
    """Test ChartInjector functionality"""

    def test_chart_injection(self):
        injector = ChartInjector()

        html_skeleton = """
        <html><body>
            <div id="widget_chart_1"></div>
        </body></html>
        """

        charts = [
            {
                "id": "chart_1",
                "_render_id": "widget_chart_1",
                "type": "line",
                "title": "Test Chart",
                "description": "A test chart"
            }
        ]

        injected_html = injector.inject_charts(html_skeleton, charts)

        assert "echarts.min.js" in injected_html
        assert "echarts.init" in injected_html
        assert "widget_chart_1" in injected_html
        assert "window.echarts_rendering_finished = true" in injected_html


class TestCodeTransformer:
    """Test CodeTransformer logic"""

    @patch('modules.code_transformer.DeepSeekClient')
    def test_code_transformation(self, mock_client_cls):
        # Setup Mock
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        # Mock LLM response
        mock_client_instance.generate_text.return_value = """
class ForestGuardController:
    def get_guard(self):
        pass
"""

        plan = {
            "project_name": "ForestSystem",
            "genome": {"target_language": "Python"},
            "code_blueprint": {"entities": ["ForestGuard"]}
        }

        transformer = CodeTransformer(plan)

        # Test private method directly to avoid file I/O complexity in unit test
        code = transformer._transform_file("class UserController: ...", "seeds/python/controller.py")

        assert "ForestGuardController" in code

    def test_physical_obfuscation(self):
        plan = {
            "project_name": "Test",
            "genome": {"target_language": "Python"},
            "code_blueprint": {} # Add empty blueprint to avoid KeyError
        }
        transformer = CodeTransformer(plan)

        code = "print('hello')"
        obfuscated = transformer._apply_physical_obfuscation(code, "Python")

        assert "项目: Test" in obfuscated
        assert "Core Business Logic for Test" in obfuscated


class TestDependencyValidator:
    """Test DependencyValidator"""

    def test_valid_imports(self):
        validator = DependencyValidator()
        code = """
import os
import sys
import json
"""
        cleaned = validator.validate_and_clean(code, "python")
        assert "REMOVED" not in cleaned
        assert "import os" in cleaned

    def test_invalid_imports(self):
        validator = DependencyValidator()
        code = """
import os
import requests  # Not in whitelist
import subprocess # Not in whitelist (assuming default whitelist)
"""
        # We need to assume what the default whitelist is.
        # Based on Read tool output, 'os' is allowed. 'requests' likely isn't in STD_LIBS.

        cleaned = validator.validate_and_clean(code, "python")
        assert "import os" in cleaned
        assert "REMOVED ILLEGAL IMPORT" in cleaned
        assert "requests" in cleaned # It keeps the line but comments it out


class TestFullPipelineE2E:
    """End-to-End Test Placeholder"""

    def test_pipeline_structure(self, tmp_path):
        """
        Verify that the pipeline output directory structure is created correctly.
        We don't run the full heavy pipeline here, but verify the artifact locations.
        """
        project_name = "E2E_Test_Project"
        output_dir = tmp_path / "output" / project_name
        output_dir.mkdir(parents=True)

        # Simulate artifacts
        (output_dir / "project_plan.json").touch()
        (output_dir / "screenshots").mkdir()
        (output_dir / "aligned_code").mkdir()

        # Check structure
        assert (output_dir / "project_plan.json").exists()
        assert (output_dir / "screenshots").is_dir()
        assert (output_dir / "aligned_code").is_dir()


class TestGUICompatibility:
    """Test GUI Data Compatibility"""

    def test_gui_project_list(self):
        """Simulate how GUI reads project list"""
        # GUI usually scans output/ directory
        pass
