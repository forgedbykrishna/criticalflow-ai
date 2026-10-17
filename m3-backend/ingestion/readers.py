"""Pluggable input readers. Every reader turns a binary stream into an iterator of plain dict records.

Adding a new format = one function + @register_reader("ext"). Nothing downstream knows the source format.
Supported out of the box: csv, tsv, jsonl/ndjson, json, parquet, and any of these gzip-compressed (.gz).
"""
from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator

Record = dict[str, Any]
ReaderFn = Callable[[BinaryIO], Iterator[Record]]

UNPARSEABLE = "_unparseable"   # marker key for records a reader could not decode (quarantined downstream)
_READERS: dict[str, ReaderFn] = {}


def register_reader(*names: str):
    def deco(fn: ReaderFn) -> ReaderFn:
        for n in names:
            _READERS[n.lower().lstrip(".")] = fn
        return fn
    return deco


def supported_formats() -> list[str]:
    return sorted(_READERS)


def _bad(msg: str, raw: Any) -> Record:
    return {UNPARSEABLE: msg, "_raw": str(raw)[:500]}


def _delimited(fh: BinaryIO, delimiter: str) -> Iterator[Record]:
    text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
    try:
        for row in csv.DictReader(text, delimiter=delimiter):
            row.pop(None, None)          # ragged row: extra cells have no header
            yield row
    finally:
        text.detach()


@register_reader("csv")
def _read_csv(fh: BinaryIO) -> Iterator[Record]:
    yield from _delimited(fh, ",")


@register_reader("tsv")
def _read_tsv(fh: BinaryIO) -> Iterator[Record]:
    yield from _delimited(fh, "\t")


@register_reader("jsonl", "ndjson")
def _read_jsonl(fh: BinaryIO) -> Iterator[Record]:
    text = io.TextIOWrapper(fh, encoding="utf-8-sig")
    try:
        for n, line in enumerate(text, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                yield _bad(f"line {n}: invalid JSON ({exc.msg})", line)
                continue
            yield obj if isinstance(obj, dict) else _bad(f"line {n}: not a JSON object", line)
    finally:
        text.detach()


@register_reader("json")
def _read_json(fh: BinaryIO) -> Iterator[Record]:
    try:
        obj = json.loads(fh.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        yield _bad(f"invalid JSON document ({exc})", "")
        return
    if isinstance(obj, dict) and isinstance(obj.get("events"), list):
        obj = obj["events"]
    if isinstance(obj, dict):
        obj = [obj]
    for i, item in enumerate(obj if isinstance(obj, list) else []):
        yield item if isinstance(item, dict) else _bad(f"item {i}: not a JSON object", item)


@register_reader("parquet")
def _read_parquet(fh: BinaryIO) -> Iterator[Record]:
    import pandas as pd   # pyarrow required

    df = pd.read_parquet(io.BytesIO(fh.read()))
    df = df.astype(object).where(df.notna(), None)
    yield from df.to_dict("records")


def _detect_format(name: str, head: bytes) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    if ext in _READERS:
        return ext
    if head.startswith(b"PAR1"):
        return "parquet"
    stripped = head.strip()
    if stripped.startswith(b"["):
        return "json"
    if stripped.startswith(b"{"):
        return "jsonl" if b"\n{" in stripped else "json"
    return "csv"


def read_records(source: str | Path | bytes | BinaryIO, fmt: str | None = None,
                 *, filename: str = "") -> Iterator[Record]:
    """Yield records from a path, raw bytes, or binary file object. `fmt` overrides auto-detection."""
    close = False
    if isinstance(source, (str, Path)):
        filename = filename or Path(source).name
        fh: BinaryIO = open(source, "rb")
        close = True
    elif isinstance(source, (bytes, bytearray)):
        fh = io.BytesIO(source)
    else:
        fh = source
        filename = filename or getattr(source, "name", "") or ""
    try:
        head = fh.read(2)
        fh.seek(0)
        if head == b"\x1f\x8b":                       # gzip magic
            fh = gzip.open(fh, "rb")                  # type: ignore[assignment]
            filename = filename[:-3] if filename.lower().endswith(".gz") else filename
        head = fh.read(4096)
        fh.seek(0)
        chosen = (fmt or _detect_format(filename, head)).lower().lstrip(".")
        if chosen not in _READERS:
            raise ValueError(f"Unsupported format '{chosen}'. Supported: {', '.join(supported_formats())}")
        yield from _READERS[chosen](fh)
    finally:
        if close:
            fh.close()
