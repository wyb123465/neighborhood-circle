"""Small provider adapter. Credentials never become prompt or response data."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    base_url: str = ""
    key: str = ""
    model: str = ""
    protocol: str = "chat_completions"
    timeout: float = 45

    @classmethod
    def from_env(cls):
        local = {} if os.getenv("NEIGHBORHOOD_IGNORE_ENV") == "1" else dotenv_values(ROOT / ".env")
        def value(name, default=""):
            return (os.getenv(name) or local.get(name) or default).strip()
        try:
            timeout = min(120, max(5, float(value("AI_TIMEOUT", "45"))))
        except ValueError:
            timeout = 45
        return cls(value("AI_BASE_URL").rstrip("/"), value("AI_API_KEY"), value("AI_MODEL"), value("AI_PROTOCOL", "chat_completions"), timeout)

    @property
    def configured(self):
        return bool(self.base_url and self.key and self.model)

    def public(self):
        return {"configured": self.configured, "model": self.model or None, "protocol": self.protocol,
                "missing": [name for name, value in (("AI_BASE_URL", self.base_url), ("AI_API_KEY", self.key), ("AI_MODEL", self.model)) if not value],
                "offline_launch": os.getenv("NEIGHBORHOOD_IGNORE_ENV") == "1"}


class ModelClient:
    def __init__(self, config=None, *, transport=None):
        self.config = config or ModelConfig.from_env()
        parsed = urlparse(self.config.base_url)
        if self.config.configured and (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.username or parsed.password):
            raise ModelError("模型服务地址格式不正确，请填写不含凭证和查询参数的 API 根地址。")
        if self.config.protocol not in {"chat_completions", "responses"}:
            raise ModelError("AI_PROTOCOL 仅支持 chat_completions 或 responses。")
        self.http = httpx.Client(timeout=self.config.timeout, transport=transport)

    def close(self):
        self.http.close()

    def complete(self, messages, tools):
        config = self.config
        if not config.configured:
            raise ModelError("模型配置不完整。")
        if config.protocol == "responses":
            inputs = []
            for message in messages:
                if message.get("provider_output"):
                    inputs.extend(message["provider_output"])
                elif message["role"] == "tool":
                    inputs.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": message["content"]})
                elif message.get("tool_calls"):
                    for call in message["tool_calls"]:
                        inputs.append({"type": "function_call", "call_id": call["id"], "name": call["function"]["name"], "arguments": call["function"]["arguments"]})
                else:
                    inputs.append({"role": message["role"], "content": message.get("content") or ""})
            body = {"model": config.model, "input": inputs, "tools": [{"type": "function", **tool["function"], "strict": False} for tool in tools], "max_output_tokens": 2400, "store": False, "include": ["reasoning.encrypted_content"]}
            endpoint = "/responses"
        else:
            body = {"model": config.model, "messages": messages, "tools": tools, "tool_choice": "auto", "max_tokens": 1600}
            endpoint = "/chat/completions"
        try:
            response = self.http.post(config.base_url + endpoint, json=body, headers={"Authorization": "Bearer " + config.key})
            response.raise_for_status()
            payload = response.json()
            if config.protocol == "responses":
                calls = [{"id": item["call_id"], "type": "function", "function": {"name": item["name"], "arguments": item["arguments"]}} for item in payload.get("output", []) if item.get("type") == "function_call"]
                return {"role": "assistant", "content": None, "tool_calls": calls, "provider_output": payload.get("output", [])}
            message = payload["choices"][0]["message"]
            return {"role": "assistant", "content": message.get("content"), "tool_calls": message.get("tool_calls") or []}
        except httpx.HTTPStatusError as error:
            raise ModelError(f"模型服务返回 HTTP {error.response.status_code}，请核对本地模型配置、协议和权限。") from error
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise ModelError("模型服务超时或响应格式不可用，请检查服务后重试。") from error
