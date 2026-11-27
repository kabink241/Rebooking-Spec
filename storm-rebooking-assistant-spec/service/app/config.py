"""Settings. Every key is read from the environment or a .env file; nothing is hard-coded."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parent


class Settings(BaseSettings):
    # .env is looked up in the working directory, then one level up (the repo root).
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    data_backend: str = "supabase"  # "supabase" | "csv" (csv is for local runs and tests)
    bookings_csv: str = "data/cancelled_bookings_denver_storm.csv"
    flights_csv: str = "data/flight_seat_availability.csv"
    rules_path: str = str(REPO_ROOT / "rules" / "storm-waiver-den-nov26.yaml")

    # Date used to evaluate the waiver rules. None means today.
    as_of_default: Optional[date] = None

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # OpenRouter. The model id must end in ":free" so this service can never spend money.
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_referer: str = ""  # optional, shown on OpenRouter's usage page
    openrouter_title: str = "Storm Rebooking Service"
    model_timeout_s: float = 45.0
    use_model: bool = True

    service_api_key: str = ""

    max_candidates: int = 5
    batch_concurrency: int = 2  # free models are rate limited

    @field_validator("openrouter_model")
    @classmethod
    def _free_models_only(cls, v: str) -> str:
        v = v.strip()
        if v and not v.endswith(":free"):
            raise ValueError(f"OPENROUTER_MODEL must be a free model (id ending in ':free'), got {v!r}")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolve_as_of(requested: Optional[date], settings: Settings) -> date:
    return requested or settings.as_of_default or date.today()
