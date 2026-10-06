from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str:
        ...

    @abstractmethod
    def generate_json(self, prompt: str) -> dict[str, Any]:
        ...


class FallbackProvider(LLMProvider):
    """Resilient provider that wraps primary and secondary providers with automatic failover."""

    def __init__(self, primary: LLMProvider, secondary: LLMProvider) -> None:
        self.primary = primary
        self.secondary = secondary

    @property
    def model_id(self) -> str:
        return f"fallback({self.primary.model_id} -> {self.secondary.model_id})"

    def generate_json(self, prompt: str) -> dict[str, Any]:
        try:
            return self.primary.generate_json(prompt)
        except Exception as exc:
            logger.warning(
                "FallbackProvider: Primary provider '%s' failed (%s). Failing over to secondary '%s'.",
                self.primary.model_id,
                exc,
                self.secondary.model_id,
            )
            return self.secondary.generate_json(prompt)


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._api_key = api_key
        self._model = model

    @property
    def model_id(self) -> str:
        return f"gemini:{self._model}"

    def generate_json(self, prompt: str) -> dict[str, Any]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }
        return _post_json(url, body)


class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self._api_key = api_key
        self._model = model

    @property
    def model_id(self) -> str:
        return f"groq:{self._model}"

    def generate_json(self, prompt: str) -> dict[str, Any]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt + "\n\nReturn valid JSON only.",
                }
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        raw = _post_json(url, body, headers=headers)
        content = raw["choices"][0]["message"]["content"]
        return json.loads(content)


class MockRelevanceProvider(LLMProvider):
    """Deterministic classifier for tests and offline runs."""

    @property
    def model_id(self) -> str:
        return "mock:relevance_v2"

    def generate_json(self, prompt: str) -> dict[str, Any]:
        marker = "Records:\n"
        idx = prompt.find(marker)
        records: list[dict[str, Any]] = []
        if idx >= 0:
            records = json.loads(prompt[idx + len(marker) :])

        results = []
        for rec in records:
            rid = rec["record_id"]
            text = f"{rec.get('title') or ''} {rec.get('body') or ''}".casefold()
            relevant = (
                ("google photos" in text or "google photo" in text)
                and any(
                    w in text
                    for w in (
                        "find",
                        "search",
                        "remember",
                        "can't find",
                        "cannot find",
                        "lost",
                        "look for",
                    )
                )
            )
            results.append(
                {
                    "record_id": rid,
                    "is_relevant": relevant,
                    "confidence": 0.75 if relevant else 0.2,
                    "rationale": "mock: per-record keyword heuristic",
                    "retrieval_signal_types": ["memory_gap", "search_formulation"]
                    if relevant
                    else [],
                }
            )
        return {"results": results}


class MockExtractionProvider(LLMProvider):
    """Deterministic UX extraction for tests and offline runs."""

    @property
    def model_id(self) -> str:
        return "mock:extraction_v1"

    def generate_json(self, prompt: str) -> dict[str, Any]:
        if "Exemplars:" in prompt:
            return {
                "label": "Difficulty finding photos with partial memory",
                "summary": "Users remember fragments of an image but cannot locate it in Google Photos.",
            }

        marker = "Records:\n"
        idx = prompt.find(marker)
        records: list[dict[str, Any]] = []
        if idx >= 0:
            records = json.loads(prompt[idx + len(marker) :])

        results = []
        for rec in records:
            rid = rec["record_id"]
            text = f"{rec.get('title') or ''} {rec.get('body') or ''}"
            tl = text.casefold()
            item: dict[str, Any] = {
                "record_id": rid,
                "retrieval_scenario": None,
                "remembers": None,
                "forgotten": None,
                "search_attempt": None,
                "failure_point": None,
                "workaround": None,
                "outcome": None,
                "evidence_spans": {},
            }
            if "google photos" in tl or "google photo" in tl:
                item["retrieval_scenario"] = "Find a photo in Google Photos"
            if "remember" in tl:
                item["remembers"] = "Partial memory of the visual item"
            if "can't find" in tl or "cannot find" in tl:
                item["search_attempt"] = "Searched in Google Photos"
                item["failure_point"] = "Search did not surface the item"
                item["outcome"] = "failure"
            results.append(item)
        return {"results": results}


def _post_json(url: str, body: dict, headers: dict | None = None, max_attempts: int = 5) -> dict:
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        request = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            if "candidates" in raw:
                text = raw["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            return raw
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"LLM HTTP {exc.code}: {detail}")
            if exc.code in (429, 503) and attempt < max_attempts - 1:
                delay = 5 * (2**attempt)
                try:
                    payload = json.loads(detail)
                    for err in payload.get("error", {}).get("details", []):
                        if "retryDelay" in err:
                            delay = max(delay, int(err["retryDelay"].rstrip("s")))
                except json.JSONDecodeError:
                    pass
                logger.warning("LLM rate limited; sleeping %ss (attempt %s)", delay, attempt + 1)
                time.sleep(delay)
                continue
            raise last_error from exc

    raise last_error or RuntimeError("LLM request failed")
