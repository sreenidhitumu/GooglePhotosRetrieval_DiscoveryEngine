from __future__ import annotations

import json
import logging
import time
from typing import Any

from discover.config import Settings
from discover.llm.prompts import build_relevance_batch_prompt
from discover.llm.providers import GeminiProvider, GroqProvider, MockRelevanceProvider
from discover.llm.schemas import RELEVANCE_PROMPT_VERSION, validate_relevance_item

logger = logging.getLogger(__name__)


class LLMGateway:
    def __init__(self, provider) -> None:
        self._provider = provider

    @property
    def model_id(self) -> str:
        return self._provider.model_id

    @property
    def prompt_version(self) -> str:
        return RELEVANCE_PROMPT_VERSION

    def classify_relevance_batch(
        self, records: list[dict[str, Any]], *, max_retries: int = 3
    ) -> list[dict[str, Any]]:
        if not records:
            return []

        prompt = build_relevance_batch_prompt(records)
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                parsed = self._provider.generate_json(prompt)
                return self._parse_results(parsed, records)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM batch attempt %s failed (%s records): %s",
                    attempt + 1,
                    len(records),
                    exc,
                )
                if attempt < max_retries:
                    time.sleep(min(60.0, 2 ** attempt))
        if len(records) > 1:
            mid = len(records) // 2
            logger.warning(
                "Splitting failed batch into %s + %s records after retries",
                mid,
                len(records) - mid,
            )
            left = self.classify_relevance_batch(records[:mid], max_retries=max_retries)
            right = self.classify_relevance_batch(records[mid:], max_retries=max_retries)
            return left + right
        raise RuntimeError(f"LLM batch failed after retries: {last_error}")

    def _parse_results(
        self, parsed: dict[str, Any], records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        items = parsed.get("results")
        if not isinstance(items, list):
            raise ValueError("LLM response missing results array")

        by_id = {item.get("record_id"): item for item in items if isinstance(item, dict)}
        validated: list[dict[str, Any]] = []
        for rec in records:
            rid = rec["record_id"]
            item = by_id.get(rid)
            if item is None:
                raise ValueError(f"LLM response missing record_id {rid}")
            validated.append(validate_relevance_item(item, rid))
        return validated


from discover.llm.providers import FallbackProvider, GeminiProvider, GroqProvider, MockRelevanceProvider


def get_llm_gateway(settings: Settings, provider_name: str | None = None) -> LLMGateway:
    name = (provider_name or settings.llm_provider).lower()
    if name == "mock":
        return LLMGateway(MockRelevanceProvider())
    if name == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY required for groq provider")
        return LLMGateway(GroqProvider(settings.groq_api_key, settings.groq_model))
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY required for gemini provider")
        return LLMGateway(GeminiProvider(settings.gemini_api_key, settings.gemini_model))
    if name in ("auto", "fallback"):
        primary = GeminiProvider(settings.gemini_api_key, settings.gemini_model) if settings.gemini_api_key else (GroqProvider(settings.groq_api_key, settings.groq_model) if settings.groq_api_key else MockRelevanceProvider())
        secondary = GroqProvider(settings.groq_api_key, settings.groq_model) if (settings.groq_api_key and settings.gemini_api_key) else MockRelevanceProvider()
        return LLMGateway(FallbackProvider(primary, secondary))
    raise ValueError(f"Unknown LLM provider: {name}")
