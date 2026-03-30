from modules.code_transformer import CodeTransformer


class _ClientStub:
    def __init__(self, http_mode: bool, api_style: str):
        self._http_mode = http_mode
        self._api_style = api_style

    def _should_use_http_compatible(self):
        return self._http_mode

    def _resolve_api_style(self):
        return self._api_style


def _build_transformer_with_client(http_mode: bool, api_style: str) -> CodeTransformer:
    transformer = CodeTransformer.__new__(CodeTransformer)
    transformer.client = _ClientStub(http_mode=http_mode, api_style=api_style)
    return transformer


def test_parallel_policy_responses_http_uses_serial_mode():
    transformer = _build_transformer_with_client(http_mode=True, api_style="responses")
    concurrency, delay = transformer._resolve_llm_parallel_policy(ai_file_count=9)
    assert concurrency == 1
    assert delay >= 0.7


def test_parallel_policy_http_chat_caps_to_two():
    transformer = _build_transformer_with_client(http_mode=True, api_style="chat")
    concurrency, delay = transformer._resolve_llm_parallel_policy(ai_file_count=2)
    assert concurrency <= 2
    assert delay >= 0.35


def test_parallel_policy_sdk_keeps_default_speed():
    transformer = _build_transformer_with_client(http_mode=False, api_style="chat")
    concurrency_small, delay_small = transformer._resolve_llm_parallel_policy(ai_file_count=2)
    concurrency_large, delay_large = transformer._resolve_llm_parallel_policy(ai_file_count=8)
    assert concurrency_small == 3
    assert concurrency_large == 2
    assert delay_small == 0.25
    assert delay_large == 0.25
