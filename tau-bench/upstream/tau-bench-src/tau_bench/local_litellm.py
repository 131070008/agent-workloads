import os
from typing import Any

from litellm import completion


def tau_completion(*, provider: str, **kwargs: Any) -> Any:
    """LiteLLM completion wrapper for bounded local smoke runs."""

    kwargs.setdefault("timeout", float(os.getenv("TAU_LLM_TIMEOUT", "180")))

    if provider in {"ollama", "ollama_chat"}:
        kwargs.setdefault("num_ctx", int(os.getenv("TAU_LLM_NUM_CTX", "4096")))
        kwargs.setdefault("think", os.getenv("TAU_LLM_THINK", "false").lower() == "true")

    return completion(custom_llm_provider=provider, **kwargs)
