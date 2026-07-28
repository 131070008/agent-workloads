"""Bounded OpenAI-compatible model transport without LiteLLM."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, Field

from minisweagent.exceptions import FormatError
from minisweagent.models import GLOBAL_MODEL_STATS
from minisweagent.models.utils.actions_text import format_observation_messages, parse_regex_actions


LOGGER = logging.getLogger(__name__)


class DirectOpenAITextbasedModelConfig(BaseModel):
    model_name: str
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    cost_tracking: str = "ignore_errors"
    action_regex: str = r"```mswea_bash_command\s*\n(.*?)\n```"
    format_error_template: str = (
        "Please always provide EXACTLY ONE action in triple backticks, found {{actions|length}} actions."
    )
    observation_template: str = (
        "{% if output.exception_info %}<exception>{{output.exception_info}}</exception>\n{% endif %}"
        "<returncode>{{output.returncode}}</returncode>\n<output>\n{{output.output}}</output>"
    )
    multimodal_regex: str = ""


class DirectOpenAITextbasedModel:
    """Use mini-SWE's text protocol with a small, bounded REST client."""

    abort_exceptions: list[type[Exception]] = [KeyboardInterrupt]

    def __init__(self, **kwargs: Any):
        self.config = DirectOpenAITextbasedModelConfig(**kwargs)

    def _request(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        options = self.config.model_kwargs | kwargs
        api_base = str(options.get("api_base") or os.environ.get("OPENAI_API_BASE", "")).rstrip("/")
        api_key = str(options.get("api_key") or os.environ.get("OPENAI_API_KEY", ""))
        if not api_base:
            raise RuntimeError("OPENAI_API_BASE is required for DirectOpenAITextbasedModel")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for DirectOpenAITextbasedModel")

        model_name = self.config.model_name.removeprefix("openai/")
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {key: message[key] for key in ("role", "content", "name") if key in message}
                for message in messages
            ],
            "stream": False,
        }
        for name in ("temperature", "max_tokens", "top_p", "stop"):
            if name in options:
                payload[name] = options[name]

        timeout = float(options.get("timeout", 300))
        attempts = int(options.get("request_attempts", 3))
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(
                api_base + "/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                    "Connection": "close",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code not in {408, 429, 500, 502, 503, 504} or attempt == attempts:
                    raise RuntimeError(
                        f"OpenAI-compatible request failed HTTP {error.code}: {body[:1000]}"
                    ) from error
            except (TimeoutError, urllib.error.URLError) as error:
                if attempt == attempts:
                    raise RuntimeError(
                        f"OpenAI-compatible request failed after {attempts} attempts: {error}"
                    ) from error
            delay = min(2 ** (attempt - 1), 8)
            LOGGER.warning("Model request attempt %d/%d failed; retrying in %ds", attempt, attempts, delay)
            time.sleep(delay)
        raise AssertionError("unreachable")

    def query(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        response = self._request(messages, **kwargs)
        GLOBAL_MODEL_STATS.add(0.0)
        choice = response["choices"][0]
        raw_message = choice.get("message") or {}
        content = raw_message.get("content") or ""
        try:
            actions = parse_regex_actions(
                content,
                action_regex=self.config.action_regex,
                format_error_template=self.config.format_error_template,
                template_kwargs={"finish_reason": choice.get("finish_reason")},
            )
        except FormatError as error:
            error.messages[0]["extra"]["response"] = response
            raise

        message = dict(raw_message)
        message.setdefault("role", "assistant")
        message["extra"] = {
            "actions": actions,
            "response": response,
            "cost": 0.0,
            "timestamp": time.time(),
        }
        return message

    def format_message(self, **kwargs: Any) -> dict[str, Any]:
        return kwargs

    def format_observation_messages(
        self,
        message: dict[str, Any],
        outputs: list[dict[str, Any]],
        template_vars: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return format_observation_messages(
            outputs,
            observation_template=self.config.observation_template,
            template_vars=template_vars,
            multimodal_regex=self.config.multimodal_regex,
        )

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]:
        return self.config.model_dump()

    def serialize(self) -> dict[str, Any]:
        return {
            "info": {
                "config": {
                    "model": self.config.model_dump(mode="json"),
                    "model_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                }
            }
        }
