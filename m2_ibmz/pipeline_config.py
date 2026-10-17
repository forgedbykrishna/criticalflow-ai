"""pipeline_config.py - Mock/live switch and raw-log acquisition.

MOCK_MODE=True  (default): replay datasets/raw/*.txt (no mainframe needed)
MOCK_MODE=False           : live z/OSMF extraction (Approach A)
FALLBACK_TO_MOCK=True     : if live extraction fails, replay mock data and log it loudly
All settings come from environment variables (see .env.example).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("cf.pipeline")
ROOT = Path(__file__).resolve().parent


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    mock_mode: bool
    fallback_to_mock: bool
    raw_dir: Path
    expected_dir: Path
    job_prefixes: tuple[str, ...]
    job_owner: str
    default_subsystem: str
    default_system_id: str
    state_file: Path
    quarantine_dir: Path
    utc_offset_hours: float
    api_base_url: str
    api_token: str | None
    api_timeout_s: float


def load_settings() -> Settings:
    prefixes = tuple(p.strip() for p in os.environ.get("CF_JOB_PREFIX", "PAY*,GL*").split(",") if p.strip())
    return Settings(
        mock_mode=_bool("MOCK_MODE", True),
        fallback_to_mock=_bool("FALLBACK_TO_MOCK", False),
        raw_dir=Path(os.environ.get("MOCK_RAW_DIR", ROOT / "datasets" / "raw")),
        expected_dir=Path(os.environ.get("MOCK_EXPECTED_DIR", ROOT / "datasets" / "expected")),
        job_prefixes=prefixes,
        job_owner=os.environ.get("CF_JOB_OWNER", os.environ.get("ZOSMF_USER", "*")),
        default_subsystem=os.environ.get("CF_DEFAULT_SUBSYSTEM", "PAYMENT-API"),
        default_system_id=os.environ.get("CF_DEFAULT_SYSTEM_ID", "AUTO"),
        state_file=Path(os.environ.get("CF_STATE_FILE", ROOT / ".cf_harvest_state.json")),
        quarantine_dir=Path(os.environ.get("CF_QUARANTINE_DIR", ROOT / "quarantine")),
        utc_offset_hours=float(os.environ.get("CF_UTC_OFFSET", "0")),
        api_base_url=os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/"),
        api_token=os.environ.get("API_TOKEN"),
        api_timeout_s=float(os.environ.get("API_TIMEOUT_S", "15")),
    )


def _mock_logs(s: Settings) -> list[tuple[str, str]]:
    files = sorted(s.raw_dir.glob("scenario*.txt"))
    if not files:
        raise FileNotFoundError(f"No mock datasets in {s.raw_dir}")
    return [(f.stem, f.read_text(encoding="utf-8")) for f in files]


def _live_logs(s: Settings) -> list[tuple[str, str]]:
    """Read-only live fetch (does not touch the checkpoint) - used by the smoke test."""
    from extract.extract_zosmf import client_from_env, harvest
    client = client_from_env()
    try:
        out: list[tuple[str, str]] = []
        for prefix in s.job_prefixes:
            for jobname, jobid, _key, blob in harvest(client, prefix, s.job_owner, set(),
                                                      s.default_subsystem, s.default_system_id):
                out.append((f"{jobname}_{jobid}", blob))
        return out
    finally:
        client.close()


def get_raw_logs(s: Settings | None = None) -> list[tuple[str, str]]:
    s = s or load_settings()
    if s.mock_mode:
        log.info("MOCK_MODE=True: replaying %s", s.raw_dir)
        return _mock_logs(s)
    try:
        return _live_logs(s)
    except Exception as exc:  # noqa: BLE001 - deliberate: fallback is opt-in
        if s.fallback_to_mock:
            log.error("LIVE EXTRACTION FAILED (%s). *** FALLING BACK TO MOCK DATA ***", exc)
            return _mock_logs(s)
        raise
