from __future__ import annotations

import logging
import time
from typing import Any

from discover.config import Settings
from discover.llm.cluster_prompts import build_cluster_label_prompt
from discover.llm.extraction_prompts import build_extraction_batch_prompt
from discover.llm.extraction_schemas import EXTRACTION_PROMPT_VERSION, validate_extraction_item
from discover.llm.providers import (
    GeminiProvider,
    GroqProvider,
    MockExtractionProvider,
)

logger = logging.getLogger(__name__)


class ExtractionGateway:
    def __init__(self, provider) -> None:
        self._provider = provider

    @property
    def model_id(self) -> str:
        return self._provider.model_id

    @property
    def prompt_version(self) -> str:
        return EXTRACTION_PROMPT_VERSION

    def generate_json_prompt(self, prompt: str) -> dict[str, Any]:
        return self._provider.generate_json(prompt)

    def label_cluster(self, exemplars: list[dict[str, Any]]) -> tuple[str, str]:
        prompt = build_cluster_label_prompt(exemplars)
        parsed = self._provider.generate_json(prompt)
        label = (parsed.get("label") or "Unlabeled cluster").strip()
        summary = (parsed.get("summary") or "").strip()
        return label[:500], summary[:2000]

    def extract_batch(
        self, records: list[dict[str, Any]], *, max_retries: int = 3
    ) -> list[dict[str, Any]]:
        if not records:
            return []

        prompt = build_extraction_batch_prompt(records)
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                parsed = self._provider.generate_json(prompt)
                return self._parse_results(parsed, records)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Extraction batch attempt %s failed (%s records): %s",
                    attempt + 1,
                    len(records),
                    exc,
                )
                if attempt < max_retries:
                    time.sleep(min(60.0, 2 ** attempt))
        if len(records) > 1:
            mid = len(records) // 2
            logger.warning(
                "Splitting failed extraction batch into %s + %s records",
                mid,
                len(records) - mid,
            )
            left = self.extract_batch(records[:mid], max_retries=max_retries)
            right = self.extract_batch(records[mid:], max_retries=max_retries)
            return left + right
        raise RuntimeError(f"Extraction batch failed after retries: {last_error}")

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
            validated.append(validate_extraction_item(item, rid))
        return validated


def get_extraction_gateway(settings: Settings, provider_name: str | None = None):
    name = (provider_name or settings.llm_provider).lower()
    if name == "mock":
        return ExtractionGateway(MockExtractionProvider())
    if name == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY required for groq provider")
        return ExtractionGateway(GroqProvider(settings.groq_api_key, settings.groq_model))
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY required for gemini provider")
        return ExtractionGateway(GeminiProvider(settings.gemini_api_key, settings.gemini_model))
    raise ValueError(f"Unknown LLM provider: {name}")
