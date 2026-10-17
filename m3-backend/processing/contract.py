"""Loads the event contract (JSON Schema) once. Cleaning/validation are driven from it, so a schema change
(new field, new type) flows through without touching the pipeline code."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from config.settings import get_settings


@dataclass(frozen=True)
class Contract:
    schema: dict
    validator: Draft202012Validator
    fields: tuple[str, ...]            # all contract properties
    types: dict[str, tuple[str, ...]]  # field -> allowed JSON types

    def nullable_fields(self) -> list[str]:
        return [f for f, t in self.types.items() if "null" in t]


@lru_cache
def load_contract(path: str | None = None) -> Contract:
    p = Path(path) if path else get_settings().schema_path
    schema = json.loads(p.read_text(encoding="utf-8"))
    props = schema["properties"]
    types: dict[str, tuple[str, ...]] = {}
    for name, spec in props.items():
        t = spec.get("type", "string")      # "const"/"enum" fields without a type are strings here
        types[name] = tuple(t) if isinstance(t, list) else (t,)
    return Contract(schema, Draft202012Validator(schema), tuple(props), types)
