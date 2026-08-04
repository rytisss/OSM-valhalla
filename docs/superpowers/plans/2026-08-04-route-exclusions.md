# Route Exclusions Sample Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `examples/route_avoid.py`, a reference client showing how to make Valhalla route around an excluded point and around an excluded area, plus a README section documenting both.

**Architecture:** One self-contained script mirroring the existing `examples/route_truck.py`. It runs four `/route` requests — a baseline and an excluded run for each of two hardcoded scenarios — and prints a before/after comparison. A non-zero distance delta is the proof the exclusion took effect; the script exits non-zero if a delta is zero, so a mis-placed exclusion cannot pass silently.

**Tech Stack:** Python 3.13, `requests`, a running Valhalla 3.5.1 service with USA tiles.

**Spec:** `docs/superpowers/specs/2026-08-04-route-exclusions-design.md`

## Global Constraints

- Branch: `feature/exclusion_zone_route`. Never commit to `main`.
- Python 3.13. Full type annotations on every argument and return (AGENTS.md rule 4).
- Google-style docstrings on every public function and the module (rule 5). Short `_private` helpers may carry a one-liner.
- `print()` to stdout/stderr is correct **here**: this is a CLI sample, not a service, and it matches `examples/route_truck.py`. This submodule has no pre-commit/ruff config.
- No bare `except:`, no `except Exception: pass` (rule 9). Valhalla's own error text must reach the user.
- No new dependencies. `examples/requirements.txt` stays `requests>=2.31`.
- `exclude_polygons` rings are `[lon, lat]` pairs — the opposite order from `locations`.
- Total polygon perimeter must stay under `max_exclude_polygons_length` = 10 000 m, or Valhalla returns error 167.
- Verification is against the live service on `http://localhost:8002` (USA tiles). There is no pytest harness in this repo and this plan does not add one.

---

### Task 1: The exclusion sample

**Files:**
- Create: `examples/route_avoid.py`
- Reference (do not modify): `examples/route_truck.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `route_truck(start, end, *, exclude_locations=None, exclude_polygons=None, base_url=BASE_URL) -> dict`, `_box(centre: tuple[float, float], half_width: float) -> list[list[float]]`, `_summary(result: dict) -> tuple[float, float]`, `main() -> int`. Task 2 documents these but does not import them.

- [ ] **Step 1: Confirm the service is up and holds USA tiles**

Run:
```bash
curl -s http://localhost:8002/status
```
Expected: JSON with `"version":"3.5.1"` and `"route"` in `available_actions`. If this fails, start the service (`docker compose up -d`) before continuing — every step below needs it.

- [ ] **Step 2: Verify the script does not exist yet (the failing run)**

Run:
```bash
python examples/route_avoid.py
```
Expected: FAIL — `can't open file '.../examples/route_avoid.py': [Errno 2] No such file or directory`.

- [ ] **Step 3: Write `examples/route_avoid.py`**

```python
#!/usr/bin/env python3
"""Reference client: route a truck around an excluded point or area.

Valhalla offers two ways to keep a route away from a place:

* ``exclude_locations`` — a list of ``{"lat": ..., "lon": ...}`` points.
  Valhalla snaps each one to the nearest edge(s) and forbids them. This is
  surgical — it blocks a specific street or ramp. Beware: on a motorway the
  edge between interchanges is long, so blocking a point there can move the
  route by only a few metres before it rejoins the same highway.
* ``exclude_polygons`` — a list of rings of ``[lon, lat]`` pairs. Note the
  GeoJSON order, the opposite of ``locations``. The route may not cross the
  ring at all. This is the tool for "the route must not pass through here".

Polygons are capped by ``service_limits.max_exclude_polygons_length``, which
defaults to 10 000 m of total perimeter; a larger ring fails the whole request
with error 167. The box below is deliberately small (~7.8 km of perimeter).

Run the service first (docker compose up), then:
    python examples/route_avoid.py
"""
import os
import sys

import requests

BASE_URL = os.environ.get("VALHALLA_URL", "http://localhost:8002")

TRUCK_OPTIONS = {
    "height": 4.11,
    "width": 2.6,
    "length": 21.64,
    "weight": 36.3,
    "axle_load": 9.07,
    "hazmat": False,
}

# Scenario 1 — a short Chicago hop whose fastest truck path uses the
# Eisenhower Expressway (I 290). Blocking one point on it forces a detour.
HOP_START = (41.8781, -87.6298)
HOP_END = (41.8850, -87.6700)
BLOCKED_POINT = (41.876094, -87.656109)

# Scenario 2 — Chicago -> Indianapolis (the pair used by route_truck.py),
# which runs down I 65. The centre below is a point taken from that route's
# own shape near Lafayette, IN; a box around it closes the interstate there.
TRIP_START = (41.8781, -87.6298)
TRIP_END = (39.7684, -86.1581)
BLOCKED_AREA_CENTRE = (40.4163, -86.8198)
# Half the box's side, in degrees. 0.01 gives roughly 2.2 x 1.7 km — about
# 7.8 km of perimeter, comfortably under the 10 km service limit.
BLOCKED_AREA_HALF_WIDTH = 0.01


def route_truck(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    exclude_locations: list[tuple[float, float]] | None = None,
    exclude_polygons: list[list[list[float]]] | None = None,
    base_url: str = BASE_URL,
) -> dict:
    """Return Valhalla's JSON route for a truck, optionally avoiding places.

    Args:
        start: (lat, lon) of the origin.
        end: (lat, lon) of the destination.
        exclude_locations: (lat, lon) points whose nearest edges are forbidden.
        exclude_polygons: Rings of [lon, lat] pairs the route may not cross.
        base_url: Base URL of the Valhalla service.

    Returns:
        The parsed JSON response.

    Raises:
        requests.HTTPError: If Valhalla rejects the request.
    """
    payload: dict = {
        "locations": [
            {"lat": start[0], "lon": start[1]},
            {"lat": end[0], "lon": end[1]},
        ],
        "costing": "truck",
        "costing_options": {"truck": TRUCK_OPTIONS},
        "units": "miles",
    }
    if exclude_locations:
        payload["exclude_locations"] = [
            {"lat": lat, "lon": lon} for lat, lon in exclude_locations
        ]
    if exclude_polygons:
        payload["exclude_polygons"] = exclude_polygons
    resp = requests.post(f"{base_url}/route", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _box(centre: tuple[float, float], half_width: float) -> list[list[float]]:
    """Return a closed square ring of [lon, lat] pairs around a centre point."""
    lat, lon = centre
    south, north = lat - half_width, lat + half_width
    west, east = lon - half_width, lon + half_width
    return [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]


def _summary(result: dict) -> tuple[float, float]:
    """Return (miles, hours) from a Valhalla route response."""
    summary = result["trip"]["summary"]
    return summary["length"], summary["time"] / 3600


def _report(title: str, baseline: dict, excluded: dict) -> bool:
    """Print a baseline/excluded comparison and report whether it detoured."""
    base_miles, base_hours = _summary(baseline)
    excl_miles, excl_hours = _summary(excluded)
    delta = excl_miles - base_miles
    print(f"\n{title}")
    print(f"  baseline  {base_miles:8.1f} mi  {base_hours:5.2f} h")
    print(f"  excluded  {excl_miles:8.1f} mi  {excl_hours:5.2f} h   ({delta:+.1f} mi)")
    if delta <= 0:
        print("  -> the exclusion changed nothing: it missed the road it meant "
              "to block", file=sys.stderr)
        return False
    return True


def _describe_failure(exc: requests.HTTPError) -> None:
    """Print Valhalla's own error text from a rejected request."""
    response = exc.response
    if response is None:
        print(f"Request failed: {exc}", file=sys.stderr)
        return
    try:
        body = response.json()
    except ValueError:
        print(f"Valhalla returned HTTP {response.status_code}: "
              f"{response.text[:200]}", file=sys.stderr)
        return
    print(f"Valhalla rejected the request (error_code {body.get('error_code')}): "
          f"{body.get('error')}", file=sys.stderr)


def main() -> int:
    """Run both exclusion scenarios and return a process exit code."""
    point_ok = _report(
        "Scenario 1 — exclude a point (exclude_locations)",
        route_truck(HOP_START, HOP_END),
        route_truck(HOP_START, HOP_END, exclude_locations=[BLOCKED_POINT]),
    )
    area = _box(BLOCKED_AREA_CENTRE, BLOCKED_AREA_HALF_WIDTH)
    area_ok = _report(
        "Scenario 2 — exclude an area (exclude_polygons)",
        route_truck(TRIP_START, TRIP_END),
        route_truck(TRIP_START, TRIP_END, exclude_polygons=[area]),
    )
    return 0 if point_ok and area_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.HTTPError as exc:
        _describe_failure(exc)
        sys.exit(1)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        sys.exit(1)
```

Note: `requests.HTTPError` is a subclass of `requests.RequestException`, so it must be caught first.

- [ ] **Step 4: Run it and verify both exclusions detour**

Run:
```bash
python examples/route_avoid.py; echo "exit=$?"
```
Expected: PASS — `exit=0`, and output close to:
```
Scenario 1 — exclude a point (exclude_locations)
  baseline       2.9 mi   0.11 h
  excluded       4.8 mi   0.18 h   (+1.9 mi)

Scenario 2 — exclude an area (exclude_polygons)
  baseline     186.6 mi   3.03 h
  excluded     189.1 mi   3.14 h   (+2.5 mi)
```
Exact distances vary with the tileset vintage; what must hold is that both deltas are positive.

- [ ] **Step 5: Prove the no-effect guard actually fires**

Temporarily swap the ring to `lat, lon` order (the classic mistake) by editing `_box`'s return to `[[south, west], [south, east], [north, east], [north, west], [south, west]]`, then run:
```bash
python examples/route_avoid.py; echo "exit=$?"
```
Expected: Scenario 2 prints a `(+0.0 mi)` delta and the stderr line `the exclusion changed nothing`, with `exit=1`. **Revert the edit** and re-run to confirm `exit=0` again.

- [ ] **Step 6: Prove the error path prints Valhalla's message, not a traceback**

Temporarily set `BLOCKED_AREA_HALF_WIDTH = 0.05` (a ~19 km perimeter, over the cap) and run:
```bash
python examples/route_avoid.py; echo "exit=$?"
```
Expected: `exit=1` and exactly this on stderr, with no traceback:
```
Valhalla rejected the request (error_code 167): Exceeded maximum circumference for exclude_polygons: 10000 meters
```
**Revert to `0.01`** and re-run to confirm `exit=0`.

- [ ] **Step 7: Commit**

```bash
git add examples/route_avoid.py
git commit -m "feat: add route exclusion sample (avoid point and area)"
```

---

### Task 2: Document exclusions in the README

**Files:**
- Modify: `README.md` — insert a subsection into *Querying*, after the Python block that references `examples/route_truck.py` (currently lines 56-61) and before the `Other endpoints:` paragraph (currently line 63).

**Interfaces:**
- Consumes: `examples/route_avoid.py` from Task 1 — the path and the two mechanism names must match exactly.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the "Avoiding places" subsection**

Insert:

````markdown
### Avoiding places

Two request fields keep a route away from somewhere:

- `exclude_locations` — `[{"lat": …, "lon": …}]`. Valhalla forbids the edges
  nearest each point. Surgical: use it to close a specific street or ramp.
- `exclude_polygons` — `[[[lon, lat], …]]`, a closed ring in **`[lon, lat]`
  order** (GeoJSON), the opposite of `locations`. The route may not cross it.
  Use this for "the route must not pass through here".

```bash
curl http://localhost:8002/route -d '{
  "locations":[{"lat":41.8781,"lon":-87.6298},{"lat":39.7684,"lon":-86.1581}],
  "costing":"truck",
  "units":"miles",
  "exclude_polygons":[[[-86.8298,40.4063],[-86.8098,40.4063],
                       [-86.8098,40.4263],[-86.8298,40.4263],[-86.8298,40.4063]]]
}'
```

```bash
python examples/route_avoid.py   # both mechanisms, with before/after distances
```

Two things to know:

- **Polygons are size-capped.** `service_limits.max_exclude_polygons_length`
  defaults to 10 000 m of total perimeter; a bigger ring fails the request with
  `error_code` 167. The ~2 × 1.7 km box above is well inside the limit.
- **`exclude_locations` only removes the nearest edges.** On a motorway, where
  the edge between interchanges is long, the route can rejoin the same highway
  within metres — blocking a point on I-65 shifted a Chicago → Indianapolis
  route by 13 m. Reach for `exclude_polygons` when a zone must really be avoided.
````

- [ ] **Step 2: Verify the curl example works verbatim**

Run the `curl` command from the new section, piped through `python3 -m json.tool`, and check `trip.summary.length`:
```bash
curl -s http://localhost:8002/route -d '{
  "locations":[{"lat":41.8781,"lon":-87.6298},{"lat":39.7684,"lon":-86.1581}],
  "costing":"truck",
  "units":"miles",
  "exclude_polygons":[[[-86.8298,40.4063],[-86.8098,40.4063],
                       [-86.8098,40.4263],[-86.8298,40.4263],[-86.8298,40.4063]]]
}' | python3 -c "import json,sys; print(json.load(sys.stdin)['trip']['summary']['length'])"
```
Expected: PASS — a number near `189.1` (the excluded distance), **not** `186.6` (the baseline) and not an error body. A baseline figure means the pasted ring is wrong.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document exclude_locations and exclude_polygons"
```

---

## Done when

- `python examples/route_avoid.py` exits 0 and prints a positive delta for both scenarios.
- The README curl example returns the excluded distance, verified by running it.
- Both commits are on `feature/exclusion_zone_route`.

Opening the PR is a separate, human-approved step (AGENTS.md: agents never merge; the submodule PR lands before the superproject pointer bump).
