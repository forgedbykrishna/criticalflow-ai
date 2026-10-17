#!/usr/bin/env python3
"""Docker HEALTHCHECK for the M2 poller.

Healthy = CF_HEARTBEAT_FILE exists and was written (by a fully successful cycle)
within the last CF_HEALTH_MAX_AGE seconds (default 300). Exit 0 healthy, 1 unhealthy.
"""
import os
import sys
import time

path = os.environ.get("CF_HEARTBEAT_FILE", "/data/heartbeat")
max_age = float(os.environ.get("CF_HEALTH_MAX_AGE", "300"))

try:
    age = time.time() - os.path.getmtime(path)
except OSError:
    print(f"unhealthy: heartbeat file missing: {path}")
    sys.exit(1)

if age > max_age:
    print(f"unhealthy: last successful cycle {age:.0f}s ago (max {max_age:.0f}s)")
    sys.exit(1)

print(f"healthy: last successful cycle {age:.0f}s ago")
sys.exit(0)
