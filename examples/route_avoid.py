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
