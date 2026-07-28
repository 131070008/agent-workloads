"""Deterministic mini-SWE-agent model with optional recorded response delays."""

from __future__ import annotations

import copy
import time
from typing import Any

from minisweagent.models.test_models import DeterministicModel


class TimedDeterministicModel(DeterministicModel):
    """Return recorded model messages, optionally preserving their arrival gaps."""

    def __init__(
        self,
        *,
        replay_delays: list[float] | None = None,
        delay_scale: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.replay_delays = replay_delays or []
        self.delay_scale = max(0.0, delay_scale)

    def query(self, messages: list[dict[str, str]], **kwargs: Any) -> dict:
        output_index = self.current_index + 1
        if output_index < len(self.replay_delays):
            delay = max(0.0, self.replay_delays[output_index]) * self.delay_scale
            if delay:
                time.sleep(delay)
        output = copy.deepcopy(super().query(messages, **kwargs))
        output.setdefault("extra", {})["timestamp"] = time.time()
        return output

    def serialize(self) -> dict:
        data = super().serialize()
        model = data.setdefault("info", {}).setdefault("config", {}).setdefault("model", {})
        model["delay_scale"] = self.delay_scale
        model["replay_delays"] = self.replay_delays
        return data
