"""Optional source-column -> contract-field renaming, so a changed upstream format needs a config edit, not code."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_field_map(path: str | Path | None) -> dict[str, str]:
    if not path or not Path(path).is_file():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, str)}


def apply_field_map(record: dict[str, Any], mapping: dict[str, str] | None) -> dict[str, Any]:
    if not mapping:
        return record
    return {mapping.get(k, k): v for k, v in record.items()}
