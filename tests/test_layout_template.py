import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from modules.layout_template_generator import LayoutTemplateGenerator

class TestLayoutTemplateGenerator:
    """Test LayoutTemplateGenerator functionality"""

    @patch('modules.layout_template_generator.DeepSeekClient')
    def test_generate_template_success(self, mock_client_cls):
        # Setup Mock
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = """
<!DOCTYPE html>
<html>
<head>
    <style>
        :root { --primary: blue; }
        .app-shell-1234 { display: flex; }
    </style>
</head>
<body>
    <div class="app-shell-1234">
        <h1>{{ page_title }}</h1>
        {{ main_content_area }}
    </div>
    {{ page_scripts }}
</body>
</html>
"""
        mock_client_instance.client.chat.completions.create.return_value = mock_response

        # Inputs
        genome = {
            "visual_style": "Enterprise",
            "layout_mode": "sidebar-left",
            "color_scheme": {"primary": "#000000"},
            "design_system_config": {
                "border_radius": "2px",
                "shadow_style": "none"
            }
        }
        menu_list = [{"title": "Home", "icon": "fa-home"}]

        # Run
        generator = LayoutTemplateGenerator()
        html = generator.generate_template(genome, menu_list)

        # Verify
        assert "{{ main_content_area }}" in html
        assert "{{ page_scripts }}" in html
        assert "<!DOCTYPE html>" in html

    @patch('modules.layout_template_generator.DeepSeekClient')
    def test_generate_template_fallback(self, mock_client_cls):
        # Setup Mock to raise exception
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance
        mock_client_instance.client.chat.completions.create.side_effect = Exception("API Error")

        # Inputs
        genome = {
            "visual_style": "SaaS",
            "color_scheme": {"primary": "#FF0000"},
            # Missing design_system_config to test robustness
        }
        menu_list = []

        # Run
        generator = LayoutTemplateGenerator()
        html = generator.generate_template(genome, menu_list)

        # Verify Fallback
        assert "{{ main_content_area }}" in html
        assert "var(--primary-color)" in html # Check CSS injection
        assert "#FF0000" in html # Check genome usage in fallback CSS

    def test_css_generation(self):
        generator = LayoutTemplateGenerator()
        genome = {
            "color_scheme": {"primary": "#123456"},
            "design_system_config": {
                "border_radius": "10px",
                "font_family": "Arial"
            }
        }
        css = generator._generate_css_vars(genome)
        assert "--primary-color: #123456" in css
        assert "--border-radius: 10px" in css
        assert "--font-family: Arial" in css

    def test_random_class_map(self):
        generator = LayoutTemplateGenerator()
        class_map = generator._generate_random_class_map()

        assert "app_shell" in class_map
        assert "app-shell-" in class_map["app_shell"]
        assert class_map["app_shell"] != "app-shell" # Ensure suffix

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
