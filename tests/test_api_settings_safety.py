import copy
import asyncio
from pathlib import Path

import api.server as server
from api.models import SettingsUpdate
from api.models import GeneralSettingsUpdate


def test_update_settings_ignores_masked_api_key(monkeypatch):
    original = {
        "current_provider": "deepseek",
        "providers": {
            "deepseek": {
                "api_key": "sk-real-key",
                "base_url": "https://api.example.com",
                "model": "model-a",
            }
        },
    }
    saved = {}

    monkeypatch.setattr(server, "load_api_config", lambda: copy.deepcopy(original))
    monkeypatch.setattr(server, "save_api_config", lambda cfg: saved.update(copy.deepcopy(cfg)))

    asyncio.run(
        server.update_settings(
            SettingsUpdate(
                current_provider="deepseek",
                api_key="sk-real-k...",
                base_url="https://api.changed.com",
                model="model-b",
            )
        )
    )

    assert saved["providers"]["deepseek"]["api_key"] == "sk-real-key"
    assert saved["providers"]["deepseek"]["base_url"] == "https://api.changed.com"
    assert saved["providers"]["deepseek"]["model"] == "model-b"


def test_general_settings_update_and_fetch(tmp_path, monkeypatch):
    settings_path = tmp_path / "general_settings.json"
    output_dir = tmp_path / "custom_output"

    monkeypatch.setattr(server, "GENERAL_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path / "output_default")

    result = asyncio.run(
        server.update_general_settings(
            GeneralSettingsUpdate(
                captcha_wait_seconds=90,
                output_directory=str(output_dir),
                ui_skill_enabled=True,
                ui_skill_mode="narrative_tool_hybrid",
                ui_token_policy="balanced",
            )
        )
    )
    assert result["settings"]["captcha_wait_seconds"] == 90
    assert Path(result["settings"]["output_directory"]).resolve() == output_dir.resolve()
    assert result["settings"]["ui_skill_enabled"] is True
    assert result["settings"]["ui_skill_mode"] == "narrative_tool_hybrid"
    assert result["settings"]["ui_token_policy"] == "balanced"
    assert settings_path.exists()

    fetched = asyncio.run(server.get_general_settings())
    assert fetched.captcha_wait_seconds == 90
    assert Path(fetched.output_directory).resolve() == output_dir.resolve()
    assert fetched.ui_skill_enabled is True
    assert fetched.ui_skill_mode == "narrative_tool_hybrid"
    assert fetched.ui_token_policy == "balanced"
