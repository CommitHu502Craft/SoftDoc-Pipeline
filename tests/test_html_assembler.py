import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from modules.html_assembler import HTMLAssembler

class TestHTMLAssembler:
    """Test HTMLAssembler functionality"""

    def test_assemble_success(self):
        # Setup
        assembler = HTMLAssembler()

        # Mock ChartInjector behavior to avoid complex dependency
        assembler.chart_injector._generate_init_script = MagicMock(return_value="console.log('init charts');")

        # Inputs
        master_template = """
        <html>
            <title>{{ page_title }}</title>
            <body>
                <div class="main">
                    {{ main_content_area }}
                </div>
                {{ page_scripts }}
            </body>
        </html>
        """

        content_json = {
            "html_fragment": "<h1>Hello World</h1>",
            "charts_config": [
                {"container_id": "chart_1", "option": {"title": {"text": "Chart A"}}}
            ]
        }

        page_info = {
            "title": "Test Page"
        }

        # Run
        result = assembler.assemble(master_template, content_json, page_info)

        # Verify
        assert "Test Page" in result
        assert "<h1>Hello World</h1>" in result
        assert "console.log('init charts');" in result
        assert "echarts.min.js" in result # Check if CDN is injected
        assert "{{ page_title }}" not in result
        assert "{{ main_content_area }}" not in result
        assert "{{ page_scripts }}" not in result

    def test_assemble_error_handling(self):
        # Setup
        assembler = HTMLAssembler()

        # Case 1: content_json is None, triggering AttributeError inside try block
        # The catch block should handle it and return master_template with error msg
        master_template = "<div>{{ main_content_area }}</div>"

        result = assembler.assemble(master_template, None, {})

        # Verify fallback behavior
        assert "Error assembling content" in result
        assert "{{ main_content_area }}" not in result

    def test_normalize_widget_ids_aligns_missing_chart_configs(self):
        assembler = HTMLAssembler()
        html_fragment = """
        <div class="row">
            <div id="widget_chart_1" style="height:300px"></div>
            <div id="widget_chart_2" style="height:300px"></div>
        </div>
        """
        charts_config = [
            {"container_id": "widget_chart_1", "option": {"title": {"text": "A"}}}
        ]

        normalized_html, normalized_configs = assembler._normalize_widget_ids(html_fragment, charts_config)

        assert 'id="widget_chart_1"' in normalized_html
        assert 'id="widget_chart_2"' in normalized_html
        assert len(normalized_configs) == 2
        assert any(x.get("container_id") == "widget_chart_2" for x in normalized_configs)

    def test_sanitize_layout_density_removes_stretching_height_rules(self):
        assembler = HTMLAssembler()
        html_fragment = """
        <div class="row h-100 min-vh-100">
            <div class="col-lg-8 vh-100">
                <div class="bento-card h-100" style="height:100%; min-height:100vh;">A</div>
            </div>
        </div>
        """
        sanitized = assembler._sanitize_layout_density(html_fragment)

        assert "h-100" not in sanitized
        assert "vh-100" not in sanitized
        assert "min-vh-100" not in sanitized
        assert "height:100%" not in sanitized
        assert "min-height:100vh" not in sanitized

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
