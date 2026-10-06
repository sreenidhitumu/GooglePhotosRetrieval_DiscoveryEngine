from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root: repo root (parent of src/)
_PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_ROOT.parent.parent


def project_root() -> Path:
    return _PROJECT_ROOT


def load_config(env_file: Path | None = None) -> None:
    """Load .env from project root if present."""
    path = env_file or (_PROJECT_ROOT / ".env")
    if path.is_file():
        load_dotenv(path, override=False)
    else:
        load_dotenv(override=False)


def _env_int(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str | None
    groq_api_key: str | None
    youtube_api_key: str | None
    log_level: str
    log_json: bool
    llm_provider: str
    gemini_model: str
    groq_model: str
    relevance_batch_size: int
    relevance_batch_delay_seconds: float
    relevance_max_batch_input_tokens: int
    gemini_rpm_limit: int | None
    gemini_tpm_limit: int | None
    relevance_max_llm_calls: int | None

    @classmethod
    def from_env(cls) -> Settings:
        load_config()
        default_db = f"sqlite:///{(_PROJECT_ROOT / 'data/processed/discovery.db').as_posix()}"
        return cls(
            database_url=os.getenv("DATABASE_URL", default_db),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
            youtube_api_key=os.getenv("YOUTUBE_API_KEY") or None,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_json=os.getenv("LOG_JSON", "false").lower() in ("1", "true", "yes"),
            llm_provider=os.getenv("LLM_PROVIDER", "gemini").lower(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            relevance_batch_size=int(os.getenv("RELEVANCE_BATCH_SIZE", "12")),
            relevance_batch_delay_seconds=float(
                os.getenv("RELEVANCE_BATCH_DELAY_SECONDS", "2")
            ),
            relevance_max_batch_input_tokens=int(
                os.getenv("RELEVANCE_MAX_BATCH_INPUT_TOKENS", "28000")
            ),
            gemini_rpm_limit=_env_int("GEMINI_RPM_LIMIT", 10),
            gemini_tpm_limit=_env_int("GEMINI_TPM_LIMIT", 250_000),
            relevance_max_llm_calls=_env_int("RELEVANCE_MAX_LLM_CALLS", None),
        )


def ensure_data_dirs() -> None:
    root = project_root()
    (root / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (root / "data" / "processed").mkdir(parents=True, exist_ok=True)
