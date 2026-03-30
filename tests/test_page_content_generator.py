import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from modules.page_content_generator import PageContentGenerator

class TestPageContentGenerator:
    """Test PageContentGenerator functionality"""

    @patch('modules.page_content_generator.DeepSeekClient')
    def test_generate_content_success(self, mock_client_cls):
        # Setup Mock
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        # Mock JSON response
        mock_response = {
            "html_fragment": "<div class='card'>Content</div>",
            "charts_config": [{"container_id": "chart_1"}],
            "business_data": {"key": "value"}
        }
        mock_client_instance.generate_json.return_value = mock_response

        # Inputs
        genome = {
            "visual_style": "SaaS",
            "ui_framework": "Bootstrap",
            "business_context": ["订单", "库存"]
        }
        page_info = {"title": "Dashboard"}

        # Run
        generator = PageContentGenerator()
        result = generator.generate_content(genome, page_info)

        # Verify
        assert result == mock_response
        assert "html_fragment" in result
        assert "charts_config" in result

    @patch('modules.page_content_generator.DeepSeekClient')
    def test_generate_content_fallback(self, mock_client_cls):
        # Setup Mock to raise exception
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance
        mock_client_instance.generate_json.side_effect = Exception("API Error")

        # Inputs
        genome = {
            "business_context": ["Patient", "Doctor"]
        }
        page_info = {"title": "ErrorPage"}

        # Run
        generator = PageContentGenerator()
        result = generator.generate_content(genome, page_info)

        # Verify Fallback
        assert "fallback" in result["business_data"]
        assert "Patient" in result["html_fragment"] or "Doctor" in result["html_fragment"] # Should use context
        assert len(result["charts_config"]) > 0

    def test_prompt_construction(self):
        generator = PageContentGenerator()
        style = "Data"
        framework = "Tailwind"
        context = ["Server", "CPU", "Memory"]
        title = "Monitor"

        prompt = generator._construct_prompt(style, framework, context, title)

        assert "禁止 PPT 风格" in prompt
        assert "系统原型" in prompt
        assert "h-100" in prompt
        assert "Server" in prompt
        assert "Tailwind" in prompt

    def test_infer_relationship_archetype(self):
        generator = PageContentGenerator()
        key, meta = generator._infer_system_archetype(
            project_name="客户关系管理系统",
            title="客户关系总览",
            context=["线索", "联系人", "跟进"]
        )
        assert key == "relationship"
        assert "关系管理系统" in meta.get("label", "")

@patch("modules.page_content_generator.DeepSeekClient")
def test_generate_content_block_budget_gate(mock_client_cls, monkeypatch):
    from core.llm_budget import llm_budget

    monkeypatch.setattr(
        "core.llm_budget.load_api_config",
        lambda: {
            "llm_budget": {
                "total_calls": 100,
                "stages": {"default": 100, "html": 100},
                "block_calls_per_block": 1,
                "block_stage_limits": {"default": 100, "html": 1},
                "cache_ttl_seconds": 300,
                "cache_max_entries": 16,
            }
        },
    )

    mock_client_instance = MagicMock()
    mock_client_cls.return_value = mock_client_instance
    mock_client_instance.generate_json.return_value = {
        "html_fragment": "<div>ok</div>",
        "charts_config": [],
        "business_data": {},
    }

    run_id = "block-gate-run"
    llm_budget.reset_run(run_id)
    with llm_budget.run_scope(run_id), llm_budget.stage_scope("html"):
        generator = PageContentGenerator()
        result = generator.generate_content(
            {"business_context": ["工单", "处理"]},
            {"title": "工单页", "page_id": "page_1"},
            page_blueprint={
                "functional_blocks": [
                    {"block_id": "page_1_block_1"},
                    {"block_id": "page_1_block_2"},
                ]
            },
        )

    assert result.get("business_data", {}).get("llm_budget_block_blocked") is True
    assert result.get("business_data", {}).get("fallback") is True
    assert mock_client_instance.generate_json.call_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
