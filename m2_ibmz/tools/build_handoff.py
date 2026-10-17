#!/usr/bin/env python3
"""build_handoff.py - assemble the M3 handoff package from your real events.

  python3 tools/build_handoff.py [--events events] [--out handoff_m3]
Creates handoff_m3/ and handoff_m3.zip containing schema, model, SQL, samples, HANDOFF.md and an acceptance test.
"""
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contract.normalize_z_event import validate  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--events", type=Path, default=ROOT / "events")
ap.add_argument("--out", type=Path, default=ROOT / "handoff_m3")
a = ap.parse_args()

events = [json.loads(p.read_text()) for p in sorted(a.events.glob("*.json"))]
if not events:
    sys.exit(f"No events in {a.events}/ - run: python3 run_pipeline.py --once --out-dir events/")
for e in events:
    validate(e)                                   # refuse to hand over anything that breaks the contract

def first(pred):
    return next((e for e in events if pred(e)), None)

picks = {
    "01_success_cc0": first(lambda e: e["completion_status"] == "CC" and e["return_code"] == 0),
    "02_abend": first(lambda e: e["completion_status"] == "ABEND"),
    "03_jcl_error": first(lambda e: e["completion_status"] == "JCL_ERROR"),
    "04_nonzero_rc": first(lambda e: e["completion_status"] == "CC" and (e["return_code"] or 0) > 0),
}
picks = {k: v for k, v in picks.items() if v}

if a.out.exists():
    shutil.rmtree(a.out)
(a.out / "contract").mkdir(parents=True)
(a.out / "m3").mkdir()
(a.out / "samples").mkdir()
shutil.copy(ROOT / "contract/criticalflow_event.schema.json", a.out / "contract")
for f in ("models.py", "incidents.sql", "incidents_api.py", "m3_stub_api.py"):
    shutil.copy(ROOT / "m3_handoff" / f, a.out / "m3" / f)
(a.out / "m3/__init__.py").write_text("")
for f in ("incidents_api.py", "m3_stub_api.py"):         # package imports are m3.*, not m3_handoff.*
    p = a.out / "m3" / f
    p.write_text(p.read_text().replace("m3_handoff.models", "m3.models"))
for name, ev in picks.items():
    (a.out / "samples" / f"{name}.json").write_text(json.dumps(ev, indent=2) + "\n")
shutil.copy(ROOT / "tools/handoff_templates/check_endpoint.py", a.out / "check_endpoint.py")

example = picks.get("02_abend") or next(iter(picks.values()))
doc = (ROOT / "tools/handoff_templates/HANDOFF.md").read_text()
doc = (doc.replace("{{SAMPLE_JSON}}", json.dumps(example, indent=2))
          .replace("{{EVENT_COUNT}}", str(len(events)))
          .replace("{{DATE}}", datetime.date.today().isoformat()))
(a.out / "HANDOFF.md").write_text(doc)

zip_path = shutil.make_archive(str(a.out), "zip", a.out.parent, a.out.name)
print(f"Events validated: {len(events)}   samples included: {len(picks)} -> {', '.join(picks)}")
missing = {"01_success_cc0", "02_abend", "03_jcl_error"} - set(picks)
if missing:
    print("NOTE: no real event for:", ", ".join(sorted(missing)))
print(f"Package folder : {a.out}\nZip file       : {zip_path}")
