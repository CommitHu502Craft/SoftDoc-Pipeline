"""
DeepSeek API 客户端封装
支持 JSON 生成、清洗和重试机制
"""
import json
import random
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Any, Optional, List
from openai import OpenAI
from config import MAX_RETRIES, load_api_config
from core.llm_budget import llm_budget


class DeepSeekClient:
    """
    DeepSeek API 客户端（兼容 OpenAI SDK）。

    本类的核心价值不是“简单发请求”，而是把多网关环境下的稳定性策略收敛到一处：
    - 传输层选择（SDK/HTTP）
    - 协议选择（chat/responses）
    - 重试、退避、代理旁路、不可恢复错误快速失败
    """
    # 进程内 provider 级节流状态：
    # - semaphore 控制并发上限
    # - next_request_at 控制最小请求间隔（避免并发+重试风暴）
    _throttle_state_lock = threading.Lock()
    _provider_semaphores: Dict[str, threading.BoundedSemaphore] = {}
    _provider_semaphore_limits: Dict[str, int] = {}
    _provider_next_request_at: Dict[str, float] = {}
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        provider_name: Optional[str] = None,
    ):
        """
        初始化客户端

        Args:
            api_key: API 密钥，默认从配置文件读取
            base_url: API 端点，默认从配置文件读取
            model: 模型名称，默认从配置文件读取
            max_tokens: 最大token数，默认从配置文件读取
            temperature: 温度参数，默认从配置文件读取
            timeout: 请求超时时间(秒)，默认180秒
        """
        # 每次初始化都实时读取配置，确保 GUI/API 更新后新任务立刻生效
        runtime_config = load_api_config()
        providers = runtime_config.get("providers", {}) or {}
        current_provider = runtime_config.get("current_provider", "deepseek")
        selected_provider = str(provider_name or current_provider or "deepseek").strip()
        if selected_provider not in providers:
            selected_provider = current_provider
        provider_config = providers.get(selected_provider, {})
        self.provider_name = selected_provider

        self.api_key = api_key or provider_config.get("api_key", "")
        self.base_url = base_url or provider_config.get("base_url", "https://api.deepseek.com")
        self.model = model or provider_config.get("model", "deepseek-chat")
        self.max_tokens = max_tokens or provider_config.get("max_tokens", 4096)
        self.temperature = temperature or provider_config.get("temperature", 0.7)
        self.timeout = timeout or provider_config.get("timeout", 180)
        self.http_retries = int(provider_config.get("http_retries", 4) or 4)
        # 网络异常重试时临时下调 max_tokens，降低中转站超时/断流概率；0 表示禁用
        self.retry_max_tokens_cap = int(provider_config.get("retry_max_tokens_cap", 4096) or 0)
        # 退避参数：默认使用 full-jitter，减少并发任务重试尖峰。
        self.retry_strategy = (provider_config.get("retry_strategy", "full_jitter") or "full_jitter").lower()
        self.retry_base_delay = float(provider_config.get("retry_base_delay", 1.2) or 1.2)
        self.retry_delay_cap = float(provider_config.get("retry_delay_cap", 8.0) or 8.0)
        self.use_env_proxy = bool(provider_config.get("use_env_proxy", True))
        # 是否在出现 ProxyError 后自动尝试一次直连
        self.auto_bypass_proxy_on_error = bool(provider_config.get("auto_bypass_proxy_on_error", False))
        # transport 支持: auto / sdk / http
        self.transport = (provider_config.get("transport", "auto") or "auto").lower()
        # api_style 支持: chat / responses / auto
        self.api_style = (provider_config.get("api_style", "chat") or "chat").lower()
        # 运行态标记：一旦观察到代理异常，可在本实例后续请求中持续走直连。
        self._proxy_bypassed_runtime = False
        # provider 级并发与节流控制（可由配置覆盖）
        self.max_inflight_requests = self._resolve_max_inflight_requests(
            provider_config.get("max_inflight_requests", 0)
        )
        self.min_request_interval_seconds = self._resolve_min_request_interval_seconds(
            provider_config.get("min_request_interval_seconds", 0.0)
        )
        fallback_models = provider_config.get("fallback_models") or []
        if isinstance(fallback_models, str):
            fallback_models = [x.strip() for x in fallback_models.split(",") if x.strip()]
        if not isinstance(fallback_models, list):
            fallback_models = []
        fallback_model = str(provider_config.get("fallback_model") or "").strip()
        if fallback_model:
            fallback_models = [fallback_model] + list(fallback_models)
        self.fallback_models = [
            str(m).strip()
            for m in fallback_models
            if str(m).strip() and str(m).strip() != self.model
        ]
        self.fallback_switch_failure_threshold = max(
            1,
            int(provider_config.get("fallback_switch_failure_threshold", 2) or 2),
        )
        self._consecutive_failures = 0
        self._last_usage_metrics = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY 未设置，请在环境变量或 config.py 中配置")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout
        )

    def _should_use_http_compatible(self) -> bool:
        """
        选择调用传输层：
        - sdk: 强制使用 OpenAI SDK
        - http: 强制使用兼容 HTTP 调用
        - auto: 官方 deepseek 走 SDK，其余走 HTTP（对三方网关更稳）
        """
        if self.transport == "sdk":
            return False
        if self.transport == "http":
            return True

        base_url = (self.base_url or "").lower()
        return "api.deepseek.com" not in base_url

    def _resolve_api_style(self) -> str:
        """
        解析协议风格：chat / responses。

        `auto` 保守走 chat，是因为兼容网关对 /responses 的支持差异较大，
        先保证成功率，再通过显式配置启用 responses。
        """
        if self.api_style in ("chat", "responses"):
            return self.api_style
        # auto 默认保守走 chat，避免不兼容网关直接报错
        return "chat"

    def _resolve_max_inflight_requests(self, configured_value: Any) -> int:
        """
        解析 provider 并发上限。
        默认策略：
        - http + responses: 1（最稳）
        - http + chat: 2
        - sdk: 4
        """
        try:
            parsed = int(configured_value)
        except Exception:
            parsed = 0
        if parsed > 0:
            return max(1, min(parsed, 16))

        if self._should_use_http_compatible():
            return 1 if self._resolve_api_style() == "responses" else 2
        return 4

    def _resolve_min_request_interval_seconds(self, configured_value: Any) -> float:
        """
        解析 provider 请求间隔。
        默认策略（仅 http 兼容链路启用）：
        - responses: 0.8s
        - chat: 0.25s
        """
        try:
            parsed = float(configured_value)
        except Exception:
            parsed = 0.0
        if parsed > 0:
            return max(0.0, min(parsed, 10.0))

        if self._should_use_http_compatible():
            return 0.8 if self._resolve_api_style() == "responses" else 0.25
        return 0.0

    def _throttle_key(self) -> str:
        base = (self.base_url or "").rstrip("/").lower()
        return f"{self.provider_name}|{base}"

    @classmethod
    def _get_provider_semaphore(cls, throttle_key: str, limit: int) -> threading.BoundedSemaphore:
        normalized_limit = max(1, min(int(limit), 16))
        with cls._throttle_state_lock:
            current = cls._provider_semaphores.get(throttle_key)
            current_limit = cls._provider_semaphore_limits.get(throttle_key)
            if current is None or current_limit != normalized_limit:
                current = threading.BoundedSemaphore(normalized_limit)
                cls._provider_semaphores[throttle_key] = current
                cls._provider_semaphore_limits[throttle_key] = normalized_limit
            return current

    def _apply_request_pacing(self):
        """
        provider 级请求节律控制：
        按最小时间间隔串行分配“请求起始时刻”，抑制突发并发。
        """
        interval = float(self.min_request_interval_seconds or 0.0)
        if interval <= 0:
            return

        key = self._throttle_key()
        now = time.monotonic()

        # 通过“预约下一个可发送时刻”避免并发线程争抢导致的请求尖峰
        with self._throttle_state_lock:
            next_at = self._provider_next_request_at.get(key, now)
            scheduled_at = max(now, next_at)
            jitter = random.uniform(0.0, min(0.2, interval * 0.25))
            self._provider_next_request_at[key] = scheduled_at + interval + jitter

        wait = scheduled_at - now
        if wait > 0:
            print(f"  节流等待：{wait:.1f} 秒（provider={self.provider_name}）", flush=True)
            time.sleep(wait)

    @staticmethod
    def _should_fallback_to_chat(error: Exception) -> bool:
        """判断 responses 协议失败时是否应降级回 chat/completions"""
        msg = str(error).lower()
        markers = [
            "http 404",
            "http 405",
            "http 422",
            "not found",
            "unsupported",
            "unknown endpoint",
            # 中转网关常见瞬态错误：responses 路径不稳时优先降级 chat 提高成功率。
            "connection reset",
            "connection aborted",
            "remote end closed connection",
            "proxyerror",
            "max retries exceeded",
        ]
        return any(marker in msg for marker in markers)

    @staticmethod
    def _messages_to_responses_input(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """将 chat messages 转换为 responses 协议的 input 结构"""
        converted = []
        for m in messages:
            role = m.get("role", "user")
            text = m.get("content", "")
            converted.append({
                "role": role,
                "content": [{"type": "input_text", "text": text}]
            })
        return converted

    @staticmethod
    def _extract_chat_content(result: Dict[str, Any]) -> str:
        choices = result.get("choices") or []
        if not choices:
            raise ValueError(f"API 返回格式异常（缺少 choices）: {result}")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None:
            raise ValueError(f"API 返回格式异常（缺少 message.content）: {result}")
        return content

    @staticmethod
    def _extract_responses_content(result: Dict[str, Any]) -> str:
        if isinstance(result.get("output_text"), str) and result.get("output_text"):
            return result["output_text"]

        output = result.get("output") or []
        for item in output:
            for part in item.get("content", []) or []:
                if part.get("type") in ("output_text", "text") and part.get("text"):
                    return part.get("text")

        # 部分网关会在 /responses 也返回 chat 结构，兜底兼容
        if "choices" in result:
            return DeepSeekClient._extract_chat_content(result)

        raise ValueError(f"API 返回格式异常（缺少 output_text/output）: {result}")

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            parsed = int(value)
        except Exception:
            return 0
        return max(0, parsed)

    @staticmethod
    def _object_to_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            try:
                dumped = value.model_dump()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return dict(value.__dict__)
            except Exception:
                return {}
        return {}

    @staticmethod
    def _pick_usage_value(payload: Dict[str, Any], keys: List[str]) -> int:
        for key in keys:
            if key in payload:
                return DeepSeekClient._safe_int(payload.get(key))
        return 0

    @staticmethod
    def _extract_usage_metrics_from_payload(result: Dict[str, Any]) -> Dict[str, int]:
        usage_root = result.get("usage")
        usage_meta = result.get("usageMetadata")
        usage_payload = DeepSeekClient._object_to_dict(usage_root) or DeepSeekClient._object_to_dict(usage_meta)

        input_tokens = DeepSeekClient._pick_usage_value(
            usage_payload,
            ["input_tokens", "prompt_tokens", "promptTokenCount", "inputTokenCount", "prompt_token_count"],
        )
        output_tokens = DeepSeekClient._pick_usage_value(
            usage_payload,
            ["output_tokens", "completion_tokens", "candidatesTokenCount", "outputTokenCount", "completion_token_count"],
        )
        total_tokens = DeepSeekClient._pick_usage_value(
            usage_payload,
            ["total_tokens", "totalTokenCount", "total_token_count"],
        )

        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _estimate_usage_metrics(messages: List[Dict[str, str]], output_text: str) -> Dict[str, int]:
        input_chars = 0
        for item in messages or []:
            input_chars += len(str((item or {}).get("content", "") or ""))
        output_chars = len(str(output_text or ""))
        input_tokens = max(0, round(input_chars / 4))
        output_tokens = max(0, round(output_chars / 4))
        return {
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(input_tokens + output_tokens),
        }

    def _set_last_usage_metrics(self, metrics: Optional[Dict[str, int]]) -> None:
        safe_metrics = metrics or {}
        self._last_usage_metrics = {
            "input_tokens": self._safe_int(safe_metrics.get("input_tokens")),
            "output_tokens": self._safe_int(safe_metrics.get("output_tokens")),
            "total_tokens": self._safe_int(safe_metrics.get("total_tokens")),
        }

    def _capture_usage_from_response(self, response_payload: Any) -> None:
        payload = self._object_to_dict(response_payload)
        self._set_last_usage_metrics(self._extract_usage_metrics_from_payload(payload))

    def _http_completion_with_style(self, messages: list, api_style: str) -> str:
        """
        按指定协议风格执行一次 HTTP completion 请求。

        这里实现“可退化的稳态策略”：
        - 网络瞬态错误重试 + 退避
        - 可选绕过系统代理重试
        - 重试时下调 max_tokens 降低超时/断流概率
        """
        import requests

        if api_style == "responses":
            url = f"{self.base_url.rstrip('/')}/responses"
            data = {
                "model": self.model,
                "input": self._messages_to_responses_input(messages),
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens
            }
        else:
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            data = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # 某些代理网关会拦截 OpenAI SDK 的默认 UA，显式使用通用 UA 更兼容
            "User-Agent": "python-requests/2.32.3",
        }

        transient_errors = (
            requests.exceptions.ProxyError,
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )
        bypass_env_proxy = False
        result = None
        last_error = None

        for attempt in range(self.http_retries + 1):
            # 每轮单独决定是否信任环境代理，避免动全局环境变量。
            trust_env = self.use_env_proxy and not bypass_env_proxy and not self._proxy_bypassed_runtime
            request_data = data.copy()
            token_key = "max_output_tokens" if api_style == "responses" else "max_tokens"
            if (
                (attempt > 0 or self._should_preemptive_retry_cap(api_style))
                and self.retry_max_tokens_cap > 0
                and request_data.get(token_key, 0) > self.retry_max_tokens_cap
            ):
                request_data[token_key] = self.retry_max_tokens_cap
                if attempt > 0:
                    print(f"  重试请求降载：{token_key} -> {request_data[token_key]}", flush=True)
                else:
                    print(f"  首轮稳态降载：{token_key} -> {request_data[token_key]}", flush=True)
            try:
                with requests.Session() as session:
                    session.trust_env = trust_env
                    response = session.post(url, headers=headers, json=request_data, timeout=self.timeout)

                if response.status_code >= 400:
                    error_message = self._extract_http_error_message(response)
                    if response.status_code in (401, 403):
                        # 认证/权限问题属于非瞬态错误，直接抛出明确消息
                        raise RuntimeError(error_message)
                    if self._is_retryable_http_status(response.status_code) and attempt < self.http_retries:
                        # 只对可重试状态码做退避重试，避免对业务错误盲目重试。
                        retry_after_hint = self._extract_retry_after_seconds(response)
                        wait_time = self._compute_retry_delay(attempt, retry_after_hint=retry_after_hint)
                        print(f"  网络错误(HTTP {response.status_code})，{wait_time:.1f} 秒后重试...", flush=True)
                        time.sleep(wait_time)
                        continue
                    raise RuntimeError(error_message)

                result = response.json()
                break
            except requests.exceptions.ProxyError as e:
                last_error = e
                if self._should_bypass_proxy_after_error(api_style=api_style, trust_env=trust_env, bypass_env_proxy=bypass_env_proxy):
                    # 先尝试绕过系统代理再重试一次
                    bypass_env_proxy = True
                    self._proxy_bypassed_runtime = True
                    print("  检测到代理连接异常，切换直连重试（本任务后续请求保持直连）...", flush=True)
                    continue
                if attempt < self.http_retries:
                    wait_time = self._compute_retry_delay(attempt)
                    print(f"  网络错误(ProxyError)，{wait_time:.1f} 秒后重试...", flush=True)
                    time.sleep(wait_time)
                    continue
                raise
            except transient_errors as e:
                last_error = e
                if attempt < self.http_retries:
                    wait_time = self._compute_retry_delay(attempt)
                    print(f"  网络错误({type(e).__name__})，{wait_time:.1f} 秒后重试...", flush=True)
                    time.sleep(wait_time)
                    continue
                raise
            except Exception as e:
                last_error = e
                raise

        if result is None:
            raise RuntimeError(f"HTTP调用失败: {last_error}")

        self._capture_usage_from_response(result)

        if api_style == "responses":
            return self._extract_responses_content(result)
        return self._extract_chat_content(result)

    def _should_preemptive_retry_cap(self, api_style: str) -> bool:
        """
        在高波动链路上首轮即降载，避免“先失败再降载”的固定额外耗时。
        当前仅对 http/responses 启用，chat 与 SDK 保持原策略。
        """
        return bool(self._should_use_http_compatible() and api_style == "responses")

    def _should_bypass_proxy_after_error(self, api_style: str, trust_env: bool, bypass_env_proxy: bool) -> bool:
        """
        决定在 ProxyError 后是否切换直连：
        - 显式开启 auto_bypass_proxy_on_error：始终可切换
        - http/responses：即便配置未开启，也默认允许一次自动旁路（该链路更易受代理抖动影响）
        """
        if not trust_env or bypass_env_proxy:
            return False
        if self.auto_bypass_proxy_on_error:
            return True
        return bool(self._should_use_http_compatible() and api_style == "responses")

    def _http_completion(self, messages: list, api_style_override: Optional[str] = None) -> str:
        """通过 OpenAI 兼容 HTTP 接口调用并返回文本内容（chat/responses 双协议）"""
        api_style = (api_style_override or self._resolve_api_style() or "chat").strip().lower()
        if api_style not in ("chat", "responses"):
            api_style = self._resolve_api_style()
        try:
            return self._http_completion_with_style(messages, api_style)
        except Exception as e:
            if api_style == "responses" and self._should_fallback_to_chat(e):
                # 部分网关声明支持 responses 但实际不可用，自动回退可避免整任务失败。
                print("  responses 协议不可用，回退 chat/completions...", flush=True)
                return self._http_completion_with_style(messages, "chat")
            raise

    @staticmethod
    def _extract_http_error_message(response) -> str:
        """提取服务端错误信息，便于定位令牌/权限问题"""
        try:
            body = response.json()
            error_obj = body.get("error", {}) if isinstance(body, dict) else {}
            message = error_obj.get("message") or body
            return f"HTTP {response.status_code}: {message}"
        except Exception:
            text = (response.text or "").strip()
            if len(text) > 300:
                text = text[:300] + "..."
            return f"HTTP {response.status_code}: {text}"

    @staticmethod
    def _extract_http_status_from_error(err: Exception) -> Optional[int]:
        """从异常文本中提取 HTTP 状态码（如果存在）"""
        msg = str(err).lower()
        match = re.search(r"http\s*(\d{3})", msg)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    @staticmethod
    def _extract_retry_after_seconds(response) -> Optional[float]:
        """
        解析 Retry-After 响应头（RFC 9110）：
        - delta-seconds
        - HTTP-date
        """
        raw_value = (response.headers or {}).get("Retry-After")
        if not raw_value:
            return None

        value = str(raw_value).strip()
        if not value:
            return None

        if value.isdigit():
            return max(0.0, float(value))

        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            delta = (retry_at - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, float(delta))
        except Exception:
            return None

    def _compute_retry_delay(self, attempt_index: int, retry_after_hint: Optional[float] = None) -> float:
        """
        统一重试等待时间。
        默认 full-jitter：random(0, base * 2^n)，并设置上限，减少重试同步风暴。
        """
        if retry_after_hint is not None:
            return max(0.2, min(float(retry_after_hint), max(1.0, self.retry_delay_cap * 2.0)))

        if self.retry_strategy == "linear":
            return float((attempt_index + 1) * 2)

        ceiling = min(self.retry_delay_cap, self.retry_base_delay * (2 ** attempt_index))
        return max(0.2, random.uniform(0.0, max(0.2, ceiling)))

    @staticmethod
    def _is_retryable_http_status(status_code: int) -> bool:
        """判断 HTTP 状态码是否适合重试"""
        if status_code in (408, 409, 425, 429):
            return True
        return 500 <= status_code <= 599

    @staticmethod
    def _is_non_retryable_error(err: Exception) -> bool:
        """判断是否为无需重试的错误（如令牌耗尽/鉴权失败）"""
        msg = str(err).lower()
        markers = [
            "tokenstatusexhausted",
            "额度已用尽",
            "insufficient_quota",
            "invalid api key",
            "unauthorized",
            "http 401",
            "http 403",
        ]
        if any(marker in msg for marker in markers):
            return True

        # 4xx 中多数是请求参数/权限问题，不应盲目重试（保留常见可重试码）。
        status = DeepSeekClient._extract_http_status_from_error(err)
        if status is not None and 400 <= status < 500 and status not in (408, 409, 425, 429):
            return True

        return False

    def _try_switch_fallback_model(self) -> bool:
        """在连续失败后尝试切换到备用模型。"""
        while self.fallback_models:
            candidate = str(self.fallback_models.pop(0) or "").strip()
            if not candidate or candidate == self.model:
                continue
            self.model = candidate
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
            self._consecutive_failures = 0
            print(f"  触发模型降级，切换到备用模型: {candidate}", flush=True)
            return True
        return False
    
    def _clean_json_response(self, text: str) -> str:
        """
        清洗 AI 返回的文本，提取纯 JSON
        
        Args:
            text: AI 返回的原始文本
            
        Returns:
            清洗后的纯 JSON 字符串
        """
        # 移除 Markdown 代码块标记
        text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
        
        # 去除首尾空白
        text = text.strip()
        
        return text

    def _sdk_completion(self, messages: List[Dict[str, str]], api_style_override: Optional[str] = None) -> str:
        """
        使用 OpenAI SDK 按协议风格请求。

        SDK 路径优先用于官方/高兼容端点；若 responses 能力不存在或失败，会降级到 chat。
        """
        api_style = (api_style_override or self._resolve_api_style() or "chat").strip().lower()
        if api_style not in ("chat", "responses"):
            api_style = self._resolve_api_style()
        if api_style == "responses":
            responses_api = getattr(self.client, "responses", None)
            if responses_api and hasattr(responses_api, "create"):
                try:
                    response = responses_api.create(
                        model=self.model,
                        input=self._messages_to_responses_input(messages),
                        temperature=self.temperature,
                        max_output_tokens=self.max_tokens
                    )
                    self._capture_usage_from_response(response)
                    if hasattr(response, "output_text") and response.output_text:
                        return response.output_text
                    if hasattr(response, "model_dump"):
                        return self._extract_responses_content(response.model_dump())
                    if isinstance(response, dict):
                        return self._extract_responses_content(response)
                    raise ValueError("responses SDK 返回结构无法解析")
                except Exception as e:
                    if not self._should_fallback_to_chat(e):
                        raise
                    print("  SDK responses 调用失败，回退 chat/completions...", flush=True)
            else:
                print("  当前 SDK 不支持 responses，回退 chat/completions...", flush=True)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        self._capture_usage_from_response(response)
        return response.choices[0].message.content

    def _call_completion(self, messages: List[Dict[str, str]], api_style_override: Optional[str] = None) -> str:
        """统一调用入口：根据 transport + api_style 选择底层协议。"""
        resolved_style = (api_style_override or self._resolve_api_style() or "chat").strip().lower()
        if resolved_style not in ("chat", "responses"):
            resolved_style = self._resolve_api_style()
        cache_key = llm_budget.make_cache_key(
            provider_name=self.provider_name,
            model=self.model,
            api_style=resolved_style,
            messages=messages,
        )
        cached = llm_budget.get_cached(cache_key)
        if cached is not None:
            print("  命中 LLM 缓存，跳过远程调用。", flush=True)
            self._set_last_usage_metrics({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            return cached

        allowed, reason = llm_budget.consume_call(stage=llm_budget.current_stage())
        if not allowed:
            raise RuntimeError(f"LLM预算耗尽: {reason}")

        llm_budget.record_call(
            provider_name=self.provider_name,
            model=self.model,
            api_style=resolved_style,
            stage=llm_budget.current_stage(),
        )

        self._set_last_usage_metrics({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        semaphore = self._get_provider_semaphore(self._throttle_key(), self.max_inflight_requests)
        with semaphore:
            self._apply_request_pacing()
            if self._should_use_http_compatible():
                content = self._http_completion(messages, api_style_override=resolved_style)
            else:
                content = self._sdk_completion(messages, api_style_override=resolved_style)

        usage = dict(self._last_usage_metrics or {})
        if int(usage.get("total_tokens", 0) or 0) <= 0:
            usage = self._estimate_usage_metrics(messages, content)
            self._set_last_usage_metrics(usage)
        llm_budget.record_usage(
            provider_name=self.provider_name,
            model=self.model,
            api_style=resolved_style,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
            stage=llm_budget.current_stage(),
        )
        llm_budget.set_cached(cache_key, content)
        return content

    def generate_text(
        self,
        messages: List[Dict[str, str]],
        max_retries: Optional[int] = None,
        api_style_override: Optional[str] = None,
    ) -> str:
        """
        调用 API 生成文本（非 JSON）
        用于代码重写等场景，复用统一的协议与重试策略。
        """
        max_retries = max_retries or MAX_RETRIES
        last_error = None
        cleaned_content = ""

        for attempt in range(max_retries):
            try:
                print(f"正在调用 API（第 {attempt + 1}/{max_retries} 次尝试）...", flush=True)
                print(f"  模型: {self.model}", flush=True)
                print(f"  端点: {self.base_url}", flush=True)
                print(f"  max_tokens: {self.max_tokens}, temperature: {self.temperature}", flush=True)
                transport_mode = "http-compatible" if self._should_use_http_compatible() else "openai-sdk"
                resolved_style = (api_style_override or self._resolve_api_style() or "chat").strip().lower()
                if resolved_style not in ("chat", "responses"):
                    resolved_style = self._resolve_api_style()
                print(f"  调用模式: {transport_mode}/{resolved_style}", flush=True)

                content = self._call_completion(messages, api_style_override=api_style_override)
                cleaned_content = self._clean_json_response(content)
                print(f"API 返回内容长度: {len(cleaned_content)} 字符", flush=True)
                self._consecutive_failures = 0
                return cleaned_content
            except Exception as e:
                last_error = e
                print(f"[ERR] API call failed: {e}", flush=True)
                llm_budget.record_failure(
                    stage=llm_budget.current_stage(),
                    provider_name=self.provider_name,
                )
                self._consecutive_failures += 1
                switched = False
                if self._consecutive_failures >= self.fallback_switch_failure_threshold:
                    switched = self._try_switch_fallback_model()
                if self._is_non_retryable_error(e):
                    # 鉴权/额度类错误通常不会在短时间内恢复，立即停止重试避免浪费时间。
                    print("检测到不可恢复错误（鉴权或额度问题），停止重试。", flush=True)
                    break
                if switched and attempt < max_retries - 1:
                    continue
                if attempt < max_retries - 1:
                    wait_time = self._compute_retry_delay(attempt)
                    print(f"等待 {wait_time} 秒后重试...", flush=True)
                    time.sleep(wait_time)

        raise RuntimeError(f"超过最大重试次数 ({max_retries})，文本生成失败。最后错误: {last_error}")
    
    def generate_json(self, prompt: str, max_retries: Optional[int] = None) -> Dict[str, Any]:
        """
        调用 API 生成 JSON 数据
        
        Args:
            prompt: 提示词
            max_retries: 最大重试次数，默认从配置文件读取
            
        Returns:
            解析后的 JSON 字典
            
        Raises:
            ValueError: 超过最大重试次数仍无法解析 JSON
        """
        max_retries = max_retries or MAX_RETRIES
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # 构建消息
                messages = [
                    {
                        "role": "system",
                        "content": "你是一个专业的软件架构师。请严格按照要求输出纯 JSON 格式，不要添加任何 Markdown 标记或额外说明。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
                
                # 如果是重试，添加强调信息
                if attempt > 0:
                    messages.append({
                        "role": "user",
                        "content": "请注意：上次返回的格式有误。请务必返回纯 JSON，不要包含 ```json 等 Markdown 标记。"
                    })
                
                # 调用 API
                print(f"正在调用 API（第 {attempt + 1}/{max_retries} 次尝试）...", flush=True)
                print(f"  模型: {self.model}", flush=True)
                print(f"  端点: {self.base_url}", flush=True)
                print(f"  max_tokens: {self.max_tokens}, temperature: {self.temperature}", flush=True)
                call_mode = "http-compatible" if self._should_use_http_compatible() else "openai-sdk"
                print(f"  调用模式: {call_mode}/{self._resolve_api_style()}", flush=True)

                content = self._call_completion(messages)

                # 获取返回内容
                print(f"API 返回内容长度: {len(content)} 字符", flush=True)

                # 清洗 JSON
                cleaned_content = self._clean_json_response(content)

                # 尝试解析
                result = json.loads(cleaned_content)
                print("[OK] JSON parse success", flush=True)
                self._consecutive_failures = 0
                return result

            except json.JSONDecodeError as e:
                last_error = e
                print(f"[ERR] JSON parse failed: {e}", flush=True)
                print(f"清洗后的内容: {cleaned_content[:200]}...", flush=True)
                llm_budget.record_failure(
                    stage=llm_budget.current_stage(),
                    provider_name=self.provider_name,
                )
                self._consecutive_failures += 1

                if attempt < max_retries - 1:
                    switched = False
                    if self._consecutive_failures >= self.fallback_switch_failure_threshold:
                        switched = self._try_switch_fallback_model()
                    if switched:
                        continue
                    wait_time = self._compute_retry_delay(attempt)
                    print(f"等待 {wait_time} 秒后重试...", flush=True)
                    time.sleep(wait_time)

            except Exception as e:
                last_error = e
                print(f"[ERR] API call failed: {e}", flush=True)
                llm_budget.record_failure(
                    stage=llm_budget.current_stage(),
                    provider_name=self.provider_name,
                )
                self._consecutive_failures += 1
                switched = False
                if self._consecutive_failures >= self.fallback_switch_failure_threshold:
                    switched = self._try_switch_fallback_model()
                if self._is_non_retryable_error(e):
                    # JSON 任务也遵循同样的快速失败策略，避免重复触发 401/403。
                    print("检测到不可恢复错误（鉴权或额度问题），停止重试。", flush=True)
                    break

                if attempt < max_retries - 1:
                    if switched:
                        continue
                    wait_time = self._compute_retry_delay(attempt)
                    print(f"等待 {wait_time} 秒后重试...", flush=True)
                    time.sleep(wait_time)
        
        # 超过最大重试次数
        raise ValueError(f"超过最大重试次数 ({max_retries})，仍无法解析 JSON。最后错误: {last_error}")
    
    def test_connection(self) -> bool:
        """
        测试 API 连接
        
        Returns:
            连接是否成功
        """
        try:
            self._call_completion([{"role": "user", "content": "Hello"}])
            return True
        except Exception as e:
            print(f"连接测试失败: {e}")
            return False
