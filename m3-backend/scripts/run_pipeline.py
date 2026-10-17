"""Batch-load a dataset file into PostgreSQL (any supported format).

  python -m scripts.run_pipeline data/samples/training_data.csv
  python -m scripts.run_pipeline events.jsonl --format jsonl --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from config.settings import get_settings
from db.repository import save_result
from db.session import _factory, init_db
from ingestion.field_map import load_field_map
from ingestion.readers import read_records, supported_formats
from processing.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--format", choices=supported_formats(), help="default: auto-detect from extension/content")
    ap.add_argument("--dry-run", action="store_true", help="validate + process, do not write to the database")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    s = get_settings()
    res = run_pipeline(read_records(a.input, a.format), field_map=load_field_map(s.field_map_path))
    summary = {"received": res.received, "accepted": len(res.processed), "quarantined": len(res.rejected),
               "duplicates_in_batch": res.duplicates}
    if not a.dry_run:
        init_db()
        with _factory()() as session:
            summary["batch_id"] = save_result(session, res, f"file:{a.input}")
    print(json.dumps(summary, indent=2))
    return 0 if not res.rejected else 1


if __name__ == "__main__":
    sys.exit(main())
