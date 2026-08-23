# llm_clients_resilient.py
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import requests

logger = logging.getLogger(__name__)

JsonDict = Dict[str, Any]


class LLMError(Exception):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMHTTPError(LLMError):
    pass


class LLMResponseFormatError(LLMError):
    pass


@dataclass(slots=True)
class LLMRequestContext:
    ticker: str
    provider: str
    model: str
    task_name: str = "analysis"
    trace_id: Optional[str] = None

    def as_log_dict(self) -> JsonDict:
        return {
            "ticker": self.ticker,
            "provider": self.provider,
            "model": self.model,
            "task_name": self.task_name,
            "trace_id": self.trace_id,
        }


@dataclass(slots=True)
class RetryConfig:
    max_attempts: int = 3
    initial_backoff_sec: float = 3.0
    backoff_multiplier: float = 2.0
    jitter_sec: float = 0.75
    request_timeout_sec: int = 120

    def sleep_seconds_for_attempt(self, attempt: int) -> float:
        base = self.initial_backoff_sec * (self.backoff_multiplier ** max(0, attempt - 1))
        return base + random.uniform(0, self.jitter_sec)


def normalize_confidence(value: Any) -> int:
    if value is None:
        return 0
    try:
        if isinstance(value, str):
            value = value.strip()
            if value.endswith("%"):
                value = value[:-1].strip()
            value = float(value)
        if isinstance(value, bool):
            return 100 if value else 0
        if isinstance(value, int):
            return max(0, min(100, value))
        if isinstance(value, float):
            if 0.0 <= value <= 1.0:
                value = round(value * 100)
            else:
                value = round(value)
            return max(0, min(100, int(value)))
    except Exception:
        return 0
    return 0


def _normalize_side(value: Any) -> str:
    side = "NONE" if value is None else str(value).strip().upper()
    return side if side in {"BUY", "SELL", "NONE"} else "NONE"


def _normalize_decision(value: Any) -> str:
    decision = "wait" if value is None else str(value).strip().lower()
    allowed = {"buy", "sell", "wait", "hold", "manage", "reduce", "exit", "no_trade"}
    return decision if decision in allowed else "wait"


def _normalize_strategy(value: Any) -> str:
    if value is None:
        return "no_trade"
    out = str(value).strip().lower()
    return out or "no_trade"


def _normalize_size_quote(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except Exception:
        return 0.0


def _ensure_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return [str(value)]


def postprocess_analysis_payload(payload: Mapping[str, Any]) -> JsonDict:
    out: JsonDict = dict(payload)
    out["decision"] = _normalize_decision(out.get("decision"))
    out["side"] = _normalize_side(out.get("side"))
    out["strategy"] = _normalize_strategy(out.get("strategy"))
    out["confidence"] = normalize_confidence(out.get("confidence"))
    out["size_quote"] = _normalize_size_quote(out.get("size_quote"))
    out["reasons"] = _ensure_string_list(out.get("reasons"))
    out["must_reject_if"] = _ensure_string_list(out.get("must_reject_if"))

    if out["decision"] in {"wait", "no_trade"}:
        out["side"] = "NONE"
        out["size_quote"] = 0.0
        if not out["strategy"]:
            out["strategy"] = "no_trade"

    return out


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"(\{.*\})", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"(\[.*\])", re.DOTALL)


def extract_json_text(text: str) -> str:
    if not text or not text.strip():
        raise LLMResponseFormatError("Empty model response.")
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        return fence_match.group(1).strip()
    obj_match = _JSON_OBJECT_RE.search(stripped)
    if obj_match:
        return obj_match.group(1).strip()
    arr_match = _JSON_ARRAY_RE.search(stripped)
    if arr_match:
        return arr_match.group(1).strip()
    raise LLMResponseFormatError("Could not find JSON in model response.")


def parse_json_response_text(text: str) -> Any:
    try:
        return json.loads(extract_json_text(text))
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError(f"Invalid JSON from model: {exc}") from exc


def _is_timeout_exception(exc: BaseException) -> bool:
    timeout_types = (
        requests.exceptions.Timeout,
        requests.exceptions.ReadTimeout,
        requests.exceptions.ConnectTimeout,
    )
    if isinstance(exc, timeout_types):
        return True
    return "read timed out" in str(exc).lower() or "timeout" in str(exc).lower()


def _raise_for_http_error(resp: requests.Response) -> None:
    if 200 <= resp.status_code < 300:
        return
    raise LLMHTTPError(f"HTTP {resp.status_code}: {resp.text[:2000]}")


def _extract_openai_text(data: Mapping[str, Any]) -> str:
    output = data.get("output")
    if isinstance(output, list):
        chunks: List[str] = []
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, Mapping):
                        text = part.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
        if chunks:
            return "\\n".join(chunks)

    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    choices = data.get("choices")
    if isinstance(choices, list):
        parts: List[str] = []
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                parts.append(message["content"])
        if parts:
            return "\\n".join(parts)

    return ""


class BaseLLMClient:
    provider_name = "base"

    def __init__(self, model: str, retry_config: Optional[RetryConfig] = None) -> None:
        self.model = model
        self.retry_config = retry_config or RetryConfig()

    def _request_once(self, system_prompt: str, user_prompt: str, context: LLMRequestContext) -> str:
        raise NotImplementedError

    def complete_text(self, system_prompt: str, user_prompt: str, context: LLMRequestContext) -> str:
        last_error: Optional[BaseException] = None

        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                logger.info(
                    "LLM request attempt %s/%s",
                    attempt,
                    self.retry_config.max_attempts,
                    extra={"llm_context": context.as_log_dict()},
                )
                return self._request_once(system_prompt, user_prompt, context)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM request failed on attempt %s/%s: %s",
                    attempt,
                    self.retry_config.max_attempts,
                    exc,
                    extra={"llm_context": context.as_log_dict()},
                )
                if attempt >= self.retry_config.max_attempts:
                    break
                time.sleep(self.retry_config.sleep_seconds_for_attempt(attempt))

        if last_error is None:
            raise LLMError("Unknown LLM failure")
        if _is_timeout_exception(last_error):
            raise LLMTimeoutError(str(last_error)) from last_error
        if isinstance(last_error, LLMError):
            raise last_error
        raise LLMError(str(last_error)) from last_error

    def complete_json(self, system_prompt: str, user_prompt: str, context: LLMRequestContext) -> Any:
        text = self.complete_text(system_prompt, user_prompt, context)
        return parse_json_response_text(text)


class OpenAIChatClient(BaseLLMClient):
    provider_name = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4.1",
        retry_config: Optional[RetryConfig] = None,
        base_url: str = "https://api.openai.com/v1/responses",
    ) -> None:
        super().__init__(model=model, retry_config=retry_config)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url
        if not self.api_key:
            raise RuntimeError("Missing OPENAI_API_KEY")

    def _request_once(self, system_prompt: str, user_prompt: str, context: LLMRequestContext) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: JsonDict = {
            "model": self.model,
            "input": f"System instructions:\\n{system_prompt.strip()}\\n\\nUser content:\\n{user_prompt.strip()}",
        }
        try:
            resp = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.retry_config.request_timeout_sec,
            )
        except Exception as exc:
            if _is_timeout_exception(exc):
                raise LLMTimeoutError(str(exc)) from exc
            raise
        _raise_for_http_error(resp)
        data = resp.json()
        text = _extract_openai_text(data)
        if not text:
            raise LLMResponseFormatError("OpenAI response did not contain text.")
        return text


class AnthropicChatClient(BaseLLMClient):
    provider_name = "anthropic"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-7-sonnet-latest",
        retry_config: Optional[RetryConfig] = None,
        base_url: str = "https://api.anthropic.com/v1/messages",
        anthropic_version: str = "2023-06-01",
        max_tokens: int = 4000,
    ) -> None:
        super().__init__(model=model, retry_config=retry_config)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = base_url
        self.anthropic_version = anthropic_version
        self.max_tokens = max_tokens
        if not self.api_key:
            raise RuntimeError("Missing ANTHROPIC_API_KEY")

    def _request_once(self, system_prompt: str, user_prompt: str, context: LLMRequestContext) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }
        payload: JsonDict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        try:
            resp = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.retry_config.request_timeout_sec,
            )
        except Exception as exc:
            if _is_timeout_exception(exc):
                raise LLMTimeoutError(str(exc)) from exc
            raise
        _raise_for_http_error(resp)
        data = resp.json()
        content = data.get("content", [])
        if not isinstance(content, list):
            raise LLMResponseFormatError("Anthropic response 'content' is not a list.")
        texts: List[str] = []
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
        text = "\\n".join(texts).strip()
        if not text:
            raise LLMResponseFormatError("Anthropic response contained no text blocks.")
        return text


class FallbackLLMRouter:
    def __init__(self, primary: BaseLLMClient, fallback: Optional[BaseLLMClient] = None) -> None:
        self.primary = primary
        self.fallback = fallback

    def complete_json(self, system_prompt: str, user_prompt: str, context: LLMRequestContext) -> Any:
        try:
            return self.primary.complete_json(system_prompt, user_prompt, context)
        except LLMTimeoutError:
            if self.fallback is None:
                raise
            logger.warning(
                "Primary provider timed out; trying fallback provider.",
                extra={"llm_context": context.as_log_dict()},
            )
            return self.fallback.complete_json(system_prompt, user_prompt, context)


def build_analysis_json_prompt(
    ticker: str,
    feature_pack: Mapping[str, Any],
    extra_instructions: str = "",
) -> Tuple[str, str]:
    system_prompt = (
        "You are a trading analysis engine for a SPOT crypto bot. "
        "Return strict JSON only. No markdown. No prose outside JSON.\\n\\n"
        "Required keys: decision, ticker, side, strategy, confidence, size_quote, reasons, must_reject_if\\n"
        "Rules:\\n"
        "- Spot only\\n"
        "- No naked shorts\\n"
        "- If no clean setup exists, return wait / no_trade\\n"
        "- confidence should be 0..100\\n"
        "- size_quote must be 0 for no-trade / wait decisions\\n"
    )
    if extra_instructions.strip():
        system_prompt += "\\n" + extra_instructions.strip()

    user_prompt = json.dumps(
        {
            "ticker": ticker,
            "feature_pack": feature_pack,
            "output_schema": {
                "decision": "buy|sell|wait|manage|reduce|exit|no_trade",
                "ticker": ticker,
                "side": "BUY|SELL|NONE",
                "strategy": "string",
                "confidence": "0..100 integer preferred",
                "size_quote": "float",
                "reasons": ["string"],
                "must_reject_if": ["string"],
            },
        },
        ensure_ascii=False,
    )
    return system_prompt, user_prompt


def analyze_with_client(
    client: Union[BaseLLMClient, FallbackLLMRouter],
    ticker: str,
    feature_pack: Mapping[str, Any],
    provider_name: str,
    model_name: str,
    task_name: str = "analysis",
    extra_instructions: str = "",
) -> JsonDict:
    system_prompt, user_prompt = build_analysis_json_prompt(
        ticker=ticker,
        feature_pack=feature_pack,
        extra_instructions=extra_instructions,
    )
    context = LLMRequestContext(
        ticker=ticker,
        provider=provider_name,
        model=model_name,
        task_name=task_name,
    )
    payload = client.complete_json(system_prompt, user_prompt, context)
    if not isinstance(payload, Mapping):
        raise LLMResponseFormatError("Expected top-level JSON object from analysis model.")
    return postprocess_analysis_payload(payload)
