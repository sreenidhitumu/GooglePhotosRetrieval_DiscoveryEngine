from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StageMetrics:
    """Per-stage counters for pipeline runs."""

    stage: str
    records_seen: int = 0
    records_processed: int = 0
    records_skipped: int = 0
    records_failed: int = 0
    extra: dict[str, int] = field(default_factory=dict)

    def inc(self, name: str, amount: int = 1) -> None:
        self.extra[name] = self.extra.get(name, 0) + amount

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "records_seen": self.records_seen,
            "records_processed": self.records_processed,
            "records_skipped": self.records_skipped,
            "records_failed": self.records_failed,
            **self.extra,
        }

    def emit(self) -> None:
        logger.info("stage_metrics %s", self.to_dict())


class MetricsCollector:
    def __init__(self) -> None:
        self._stages: dict[str, StageMetrics] = {}
        self.telemetry = TokenTelemetry()

    def for_stage(self, stage: str) -> StageMetrics:
        if stage not in self._stages:
            self._stages[stage] = StageMetrics(stage=stage)
        return self._stages[stage]

    def emit_all(self) -> None:
        for m in self._stages.values():
            m.emit()


@dataclass
class TokenTelemetry:
    """Tracks token usage, API calls, and estimated cost across pipeline stages."""

    llm_calls: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    provider_calls: dict[str, int] = field(default_factory=dict)

    def record_llm_call(self, provider: str, input_tokens: int, output_tokens: int) -> None:
        self.llm_calls += 1
        self.estimated_input_tokens += input_tokens
        self.estimated_output_tokens += output_tokens
        self.provider_calls[provider] = self.provider_calls.get(provider, 0) + 1

    @property
    def estimated_cost_usd(self) -> float:
        # Gemini 2.0 Flash pricing estimate: $0.10 / 1M input tokens, $0.40 / 1M output tokens
        input_cost = (self.estimated_input_tokens / 1_000_000) * 0.10
        output_cost = (self.estimated_output_tokens / 1_000_000) * 0.40
        return round(input_cost + output_cost, 6)

    def to_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "provider_calls": self.provider_calls,
        }
