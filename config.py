"""
配置文件 - 自动化软著申请材料生成系统
从 config/api_config.json 加载API配置
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

# 项目根目录
BASE_DIR = Path(__file__).parent

# ============= API 配置文件路径 =============
API_CONFIG_PATH = BASE_DIR / "config" / "api_config.json"
API_CONFIG_EXAMPLE_PATH = BASE_DIR / "config" / "api_config.json.example"


def load_api_config() -> Dict[str, Any]:
    """
    从 JSON 文件加载 API 配置
    如果配置文件不存在，尝试从示例文件创建
    """
    if not API_CONFIG_PATH.exists():
        # 如果示例文件存在，复制一份作为配置文件
        if API_CONFIG_EXAMPLE_PATH.exists():
            import shutil
            shutil.copy(API_CONFIG_EXAMPLE_PATH, API_CONFIG_PATH)
            print(f"⚠ 已从示例文件创建配置: {API_CONFIG_PATH}")
            print("请编辑此文件填入您的 API 密钥")
        else:
            # 创建默认配置
            default_config = {
                "current_provider": "deepseek",
                # 规格评审自动确认：默认开启，减少 Web/API 全流程人工阻断
                "auto_confirm_spec_review": True,
                "providers": {
                    "deepseek": {
                        "api_key": "your-api-key-here",
                        "base_url": "https://api.deepseek.com",
                        "model": "deepseek-chat",
                        "max_tokens": 8192,
                        "temperature": 0.7,
                        "transport": "auto",
                        "api_style": "chat",
                        "http_retries": 4,
                        "retry_strategy": "full_jitter",
                        "retry_base_delay": 1.2,
                        "retry_delay_cap": 8.0,
                        "retry_max_tokens_cap": 4096,
                        "use_env_proxy": True,
                        "auto_bypass_proxy_on_error": False
                    },
                    "custom": {
                        "api_key": "your-custom-api-key",
                        "base_url": "http://127.0.0.1:8045/v1",
                        "model": "your-model-name",
                        "max_tokens": 8192,
                        "temperature": 0.7,
                        "transport": "http",
                        "api_style": "chat",
                        "http_retries": 4,
                        "retry_strategy": "full_jitter",
                        "retry_base_delay": 1.2,
                        "retry_delay_cap": 8.0,
                        "retry_max_tokens_cap": 4096,
                        "use_env_proxy": True,
                        "auto_bypass_proxy_on_error": True
                    }
                }
            }
            API_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(API_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            print(f"⚠ 已创建默认配置文件: {API_CONFIG_PATH}")
            print("请编辑此文件填入您的 API 密钥")
            return default_config

    with open(API_CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_api_config(config: Dict[str, Any]) -> bool:
    """
    保存 API 配置到 JSON 文件
    """
    try:
        API_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(API_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False


def get_current_provider() -> str:
    """获取当前使用的 API 提供商"""
    config = load_api_config()
    return config.get("current_provider", "deepseek")


def set_current_provider(provider: str) -> bool:
    """设置当前使用的 API 提供商"""
    config = load_api_config()
    if provider not in config.get("providers", {}):
        return False
    config["current_provider"] = provider
    return save_api_config(config)


def get_provider_config(provider: Optional[str] = None) -> Dict[str, Any]:
    """获取指定提供商的配置，默认返回当前提供商配置"""
    config = load_api_config()
    if provider is None:
        provider = config.get("current_provider", "deepseek")
    return config.get("providers", {}).get(provider, {})


def update_provider_config(provider: str, api_key: str = None,
                          base_url: str = None, model: str = None,
                          max_tokens: int = None, temperature: float = None,
                          transport: str = None, api_style: str = None,
                          http_retries: int = None, retry_strategy: str = None,
                          retry_base_delay: float = None, retry_delay_cap: float = None,
                          retry_max_tokens_cap: int = None,
                          use_env_proxy: bool = None, auto_bypass_proxy_on_error: bool = None,
                          max_inflight_requests: int = None,
                          min_request_interval_seconds: float = None) -> bool:
    """更新指定提供商的配置"""
    config = load_api_config()
    if provider not in config.get("providers", {}):
        config.setdefault("providers", {})[provider] = {}

    provider_config = config["providers"][provider]
    if api_key is not None:
        provider_config["api_key"] = api_key
    if base_url is not None:
        provider_config["base_url"] = base_url
    if model is not None:
        provider_config["model"] = model
    if max_tokens is not None:
        provider_config["max_tokens"] = max_tokens
    if temperature is not None:
        provider_config["temperature"] = temperature
    if transport is not None:
        provider_config["transport"] = transport
    if api_style is not None:
        provider_config["api_style"] = api_style
    if http_retries is not None:
        provider_config["http_retries"] = http_retries
    if retry_strategy is not None:
        provider_config["retry_strategy"] = retry_strategy
    if retry_base_delay is not None:
        provider_config["retry_base_delay"] = retry_base_delay
    if retry_delay_cap is not None:
        provider_config["retry_delay_cap"] = retry_delay_cap
    if retry_max_tokens_cap is not None:
        provider_config["retry_max_tokens_cap"] = retry_max_tokens_cap
    if use_env_proxy is not None:
        provider_config["use_env_proxy"] = use_env_proxy
    if auto_bypass_proxy_on_error is not None:
        provider_config["auto_bypass_proxy_on_error"] = auto_bypass_proxy_on_error
    if max_inflight_requests is not None:
        provider_config["max_inflight_requests"] = max_inflight_requests
    if min_request_interval_seconds is not None:
        provider_config["min_request_interval_seconds"] = min_request_interval_seconds

    return save_api_config(config)


# ============= 加载配置 =============
_api_config = load_api_config()
CURRENT_API_PROVIDER = _api_config.get("current_provider", "deepseek")
API_PROVIDERS = _api_config.get("providers", {})

# 向后兼容：保留原有变量名
_current_config = API_PROVIDERS.get(CURRENT_API_PROVIDER, {})
DEEPSEEK_API_KEY = _current_config.get("api_key", "")
DEEPSEEK_BASE_URL = _current_config.get("base_url", "https://api.deepseek.com")
DEEPSEEK_MODEL = _current_config.get("model", "deepseek-chat")

# 重试配置
MAX_RETRIES = 3

# 输出目录
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"

# 确保输出目录存在
OUTPUT_DIR.mkdir(exist_ok=True)

# 验证码等待时间（秒）
CAPTCHA_WAIT_SECONDS = 60
