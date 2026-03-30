import pytest
import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.random_engine import RandomEngine

class TestGenomeV2:
    """Test V2.1 Genome Features"""

    def setup_method(self):
        RandomEngine._instance = None
        RandomEngine._initialized = False

    def test_visual_style_generation(self):
        """Verify visual_style is generated correctly"""
        engine = RandomEngine()
        engine.set_project_seed("Enterprise_System_Alpha")
        genome = engine.get_genome()

        assert "visual_style" in genome
        assert genome["visual_style"] in ["Enterprise", "SaaS", "Data"]

        # Verify deterministic behavior
        RandomEngine._instance = None
        RandomEngine._initialized = False
        engine2 = RandomEngine()
        engine2.set_project_seed("Enterprise_System_Alpha")
        genome2 = engine2.get_genome()

        assert genome["visual_style"] == genome2["visual_style"]

    def test_business_context_medical(self):
        """Verify business context for Medical domain"""
        engine = RandomEngine()
        engine.set_project_seed("智慧医疗管理系统")
        genome = engine.get_genome()

        assert "business_context" in genome
        context = genome["business_context"]
        assert len(context) == 20
        assert "门诊号" in context
        assert "医保结算" in context

    def test_business_context_fallback(self):
        """Verify fallback business context"""
        engine = RandomEngine()
        engine.set_project_seed("未知的神秘系统")
        genome = engine.get_genome()

        context = genome["business_context"]
        assert len(context) == 20
        # Should contain generic enterprise terms
        assert "审批流程" in context or "考勤打卡" in context

    def test_design_system_config(self):
        """Verify design system config retrieval"""
        engine = RandomEngine()
        engine.set_project_seed("TestProject")
        style = engine.get_visual_style()
        config = engine.get_design_system_config(style)

        assert "border_radius" in config
        assert "shadow_style" in config
        assert "font_family" in config

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
