"""Central configuration. All values come from environment variables / .env (never hard-code secrets)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

# Training-label columns that ride along with events in the dataset but are NOT part of the event contract.
DEFAULT_LABEL_COLUMNS = ("scenario_type", "risk_score", "risk_label", "is_high_risk", "split")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@localhost:5432/criticalflow"
    api_key: str | None = None
    schema_path: Path = ROOT / "ingestion" / "schemas" / "criticalflow_event.schema.json"
    field_map_path: Path | None = None
    max_batch_size: int = 10_000
    label_columns: tuple[str, ...] = DEFAULT_LABEL_COLUMNS

    @field_validator("field_map_path", "api_key", mode="before")
    @classmethod
    def _blank_is_none(cls, v):  # `FIELD_MAP_PATH=` (empty) in .env must mean "not set", not Path('.')
        return None if isinstance(v, str) and not v.strip() else v

    # --- M4 (prediction) and M5 (explanation) services that M3 calls. Empty URL = built-in mock (dev only). ---
    m4_url: str = ""                      # docker: http://m4-prediction:8001   local: http://localhost:8001
    m5_url: str = ""                      # docker: http://m5-llm:8000          local: http://localhost:8002
    m4_path: str = "/predict"
    m5_path: str = "/explain"
    m4_timeout_s: float = 15.0
    m5_timeout_s: float = 60.0            # LLM calls are slow
    ai_retries: int = 1                   # extra attempts after the first one


@lru_cache
def get_settings() -> Settings:
    return Settings()
