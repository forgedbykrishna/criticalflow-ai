#!/usr/bin/env python3
"""Print a one-line-per-event table of events/*.json  (python3 tools/summarize_events.py [dir])"""
import json
import sys
from pathlib import Path

d = Path(sys.argv[1] if len(sys.argv) > 1 else "events")
rows = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]
if not rows:
    sys.exit(f"No events in {d}/")
print(f"{'JOB':9} {'ID':9} {'STATUS':10} {'RC':>4} {'ABEND':6} {'STEP':9} {'SYS':6} TIMESTAMP")
for e in rows:
    print(f"{e['job_name']:9} {e['job_id']:9} {e['completion_status']:10} "
          f"{str(e['return_code']) if e['return_code'] is not None else '-':>4} "
          f"{e['abend_code'] or '-':6} {e['step_name']:9} {e['system_id']:6} {e['timestamp']}")
print(f"\n{len(rows)} event(s)")
