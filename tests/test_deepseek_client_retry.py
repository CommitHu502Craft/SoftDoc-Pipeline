import datetime

from core.deepseek_client import DeepSeekClient


class _Resp:
    def __init__(self, retry_after: str = ""):
        self.headers = {}
        if retry_after:
            self.headers["Retry-After"] = retry_after


def test_extract_retry_after_seconds_delta():
    resp = _Resp("3")
    seconds = DeepSeekClient._extract_retry_after_seconds(resp)
    assert seconds is not None
    assert 2.5 <= seconds <= 3.1


def test_extract_retry_after_seconds_http_date():
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2)
    resp = _Resp(future.strftime("%a, %d %b %Y %H:%M:%S GMT"))
    seconds = DeepSeekClient._extract_retry_after_seconds(resp)
    assert seconds is not None
    assert 0.0 <= seconds <= 5.0


def test_non_retryable_4xx_detection():
    assert DeepSeekClient._is_non_retryable_error(RuntimeError("HTTP 400: bad request"))
    assert DeepSeekClient._is_non_retryable_error(RuntimeError("HTTP 401: unauthorized"))
    assert not DeepSeekClient._is_non_retryable_error(RuntimeError("HTTP 429: too many requests"))


def test_compute_retry_delay_linear_and_jitter_ranges():
    client = DeepSeekClient.__new__(DeepSeekClient)
    client.retry_strategy = "linear"
    client.retry_base_delay = 1.2
    client.retry_delay_cap = 8.0
    assert client._compute_retry_delay(0) == 2.0
    assert client._compute_retry_delay(1) == 4.0

    client.retry_strategy = "full_jitter"
    d0 = client._compute_retry_delay(0)
    d3 = client._compute_retry_delay(3)
    assert 0.2 <= d0 <= 1.2
    assert 0.2 <= d3 <= 8.0


def test_preemptive_retry_cap_only_for_http_responses():
    client = DeepSeekClient.__new__(DeepSeekClient)
    client._should_use_http_compatible = lambda: True
    assert client._should_preemptive_retry_cap("responses") is True
    assert client._should_preemptive_retry_cap("chat") is False

    client._should_use_http_compatible = lambda: False
    assert client._should_preemptive_retry_cap("responses") is False


def test_proxy_bypass_policy_prefers_responses_http():
    client = DeepSeekClient.__new__(DeepSeekClient)
    client.auto_bypass_proxy_on_error = False
    client._should_use_http_compatible = lambda: True

    assert client._should_bypass_proxy_after_error(
        api_style="responses",
        trust_env=True,
        bypass_env_proxy=False,
    ) is True
    assert client._should_bypass_proxy_after_error(
        api_style="chat",
        trust_env=True,
        bypass_env_proxy=False,
    ) is False

    client.auto_bypass_proxy_on_error = True
    assert client._should_bypass_proxy_after_error(
        api_style="chat",
        trust_env=True,
        bypass_env_proxy=False,
    ) is True


def test_should_fallback_to_chat_includes_connection_reset_markers():
    assert DeepSeekClient._should_fallback_to_chat(RuntimeError("Connection reset by peer"))
    assert DeepSeekClient._should_fallback_to_chat(RuntimeError("Connection aborted"))


def test_http_completion_falls_back_to_chat_when_responses_fails_transiently():
    client = DeepSeekClient.__new__(DeepSeekClient)
    calls = []

    def _stub_with_style(messages, style):
        calls.append(style)
        if style == "responses":
            raise RuntimeError("Connection reset by peer")
        return "ok-from-chat"

    client._resolve_api_style = lambda: "responses"
    client._http_completion_with_style = _stub_with_style

    result = client._http_completion(messages=[{"role": "user", "content": "x"}], api_style_override="responses")
    assert result == "ok-from-chat"
    assert calls == ["responses", "chat"]


def test_client_provider_override_selects_target_provider(monkeypatch):
    fake_cfg = {
        "current_provider": "global_provider",
        "providers": {
            "global_provider": {
                "api_key": "global-key",
                "base_url": "https://global.example/v1",
                "model": "global-model",
                "max_tokens": 2048,
                "temperature": 0.6,
            },
            "code_provider": {
                "api_key": "code-key",
                "base_url": "https://code.example/v1",
                "model": "code-model",
                "max_tokens": 4096,
                "temperature": 0.7,
            },
        },
    }

    monkeypatch.setattr("core.deepseek_client.load_api_config", lambda: fake_cfg)
    client = DeepSeekClient(provider_name="code_provider")

    assert client.provider_name == "code_provider"
    assert client.api_key == "code-key"
    assert client.base_url == "https://code.example/v1"
    assert client.model == "code-model"


def test_client_auto_throttle_defaults_for_http_responses(monkeypatch):
    fake_cfg = {
        "current_provider": "unstable_gateway",
        "providers": {
            "unstable_gateway": {
                "api_key": "x",
                "base_url": "https://gw.example/v1",
                "model": "m",
                "transport": "http",
                "api_style": "responses",
            }
        },
    }
    monkeypatch.setattr("core.deepseek_client.load_api_config", lambda: fake_cfg)
    client = DeepSeekClient()
    assert client.max_inflight_requests == 1
    assert abs(client.min_request_interval_seconds - 0.8) < 1e-6


def test_client_throttle_overrides_respected(monkeypatch):
    fake_cfg = {
        "current_provider": "custom_gateway",
        "providers": {
            "custom_gateway": {
                "api_key": "x",
                "base_url": "https://gw.example/v1",
                "model": "m",
                "transport": "http",
                "api_style": "responses",
                "max_inflight_requests": 3,
                "min_request_interval_seconds": 1.5,
            }
        },
    }
    monkeypatch.setattr("core.deepseek_client.load_api_config", lambda: fake_cfg)
    client = DeepSeekClient()
    assert client.max_inflight_requests == 3
    assert abs(client.min_request_interval_seconds - 1.5) < 1e-6


def test_extract_usage_metrics_compatible_keys():
    chat_payload = {
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
    }
    chat_usage = DeepSeekClient._extract_usage_metrics_from_payload(chat_payload)
    assert chat_usage["input_tokens"] == 11
    assert chat_usage["output_tokens"] == 7
    assert chat_usage["total_tokens"] == 18

    responses_payload = {
        "usage": {
            "input_tokens": 21,
            "output_tokens": 9,
        }
    }
    responses_usage = DeepSeekClient._extract_usage_metrics_from_payload(responses_payload)
    assert responses_usage["input_tokens"] == 21
    assert responses_usage["output_tokens"] == 9
    assert responses_usage["total_tokens"] == 30
