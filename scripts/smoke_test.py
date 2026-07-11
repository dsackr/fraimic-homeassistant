#!/usr/bin/env python3
"""Post-release KPF smoke test -- run by hand against a real, running Home
Assistant instance after a release (see TESTING_STRATEGY.md section 4).

Exercises the REST-shaped KPFs (frames, scenes, library, walls, schedules)
read-only, so it's safe to run repeatedly without pushing anything to a
physical frame -- image-quality/rotation checks on real hardware stay a
manual checklist item (see TESTING_STRATEGY.md), since those need eyeballing
a panel, not an API response.

Usage:
    FRAIMIC_HAPI_URL=http://your-test-ha:8123 \\
    FRAIMIC_HAPI_TOKEN=your-long-lived-access-token \\
    python3 scripts/smoke_test.py

Reads the URL/token from environment variables only -- never pass a token
on the command line (shows up in shell history / process listings) and
never commit one to this repo.

Exits non-zero if any check fails to connect or returns an unexpected
status; exits 0 if every endpoint is reachable and returns valid JSON
(an empty list is a pass -- this checks reachability/shape, not that any
particular scene/schedule/frame exists).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

CHECKS = [
    # (label, path, top-level key holding the list if the response wraps
    # one -- e.g. {"frames": [...]} -- or None if the body itself is a
    # list/dict with no wrapper).
    ("Base API reachable", "/api/", None),
    ("Frames list (KPF 3/25: setup + coordinator)", "/api/fraimic/frames", "frames"),
    ("Scenes list (KPF 16)", "/api/fraimic/scenes", "scenes"),
    ("Library list (KPF 8)", "/api/fraimic/library/list", None),
    ("Walls list (KPF 19)", "/api/fraimic/walls", None),
    ("Schedules list (KPF 20)", "/api/fraimic/schedules", None),
]


def _get(base_url: str, token: str, path: str) -> tuple[int, object | None, str | None]:
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as err:
        return err.code, None, err.reason
    except urllib.error.URLError as err:
        return 0, None, str(err.reason)

    try:
        return status, json.loads(body) if body else None, None
    except json.JSONDecodeError as err:
        return status, None, f"invalid JSON: {err}"


def main() -> int:
    base_url = os.environ.get("FRAIMIC_HAPI_URL")
    token = os.environ.get("FRAIMIC_HAPI_TOKEN")
    if not base_url or not token:
        print(
            "Set FRAIMIC_HAPI_URL and FRAIMIC_HAPI_TOKEN before running "
            "this script -- see TESTING_STRATEGY.md section 4.",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for label, path, wrapper_key in CHECKS:
        status, data, err = _get(base_url, token, path)
        if err is not None:
            print(f"FAIL  {label} ({path}): {err}")
            failures += 1
            continue
        if status != 200:
            print(f"FAIL  {label} ({path}): unexpected HTTP {status}")
            failures += 1
            continue
        if not isinstance(data, (list, dict)):
            print(f"FAIL  {label} ({path}): unexpected response shape ({type(data).__name__})")
            failures += 1
            continue

        collection = data.get(wrapper_key) if wrapper_key else data
        if wrapper_key and not isinstance(collection, list):
            print(f"FAIL  {label} ({path}): expected a \"{wrapper_key}\" list in the response")
            failures += 1
            continue

        count = len(collection) if isinstance(collection, (list, dict)) else "n/a"
        print(f"PASS  {label} ({path}) -- {count} item(s)")

    print()
    if failures:
        print(f"{failures}/{len(CHECKS)} checks FAILED")
        return 1
    print(f"All {len(CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
