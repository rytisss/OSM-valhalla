#!/usr/bin/env python3
"""Reference client: route a truck around whole states and specific points.

Builds on ``route_avoid.py``: states become ``exclude_polygons`` rings taken
from ``us_states.json`` (see ``build_us_states.py``), and points become
``exclude_locations``. Any mix of states and points can go into one request.

Valhalla treats each ring as a wall: it forbids the road edges that cross the
ring, and nothing inside can be reached without crossing it. Request cost
therefore grows with the total perimeter, which is what
``service_limits.max_exclude_polygons_length`` caps. The image built from this
repo sets that budget with the ``MAX_EXCLUDE_POLYGONS_LENGTH`` build-arg;
Valhalla's stock default of 10 000 m rejects any state (error 167).

Run the service first, then for example:
    python examples/route_exclude_states.py
    python examples/route_exclude_states.py --state Alabama --state MS
        --point 35.1531,-90.0741 --from 33.749,-84.388 --to 29.9511,-90.0715
    (one command line; wrapped here for width)

Origin and destination must lie outside every excluded state, or there is no
legal route at all.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import requests

from route_avoid import route_truck

STATES_FILE = Path(__file__).with_name("us_states.json")
EARTH_RADIUS_M = 6_371_000
# Valhalla encodes route shapes as polylines with six decimal places.
SHAPE_PRECISION = 1e6

# Defaults: Atlanta -> New Orleans normally runs I-85/I-65/I-10 straight
# through Alabama and Mississippi. Excluding both forces a loop north through
# Tennessee and Arkansas; the point sits on the I-40 Mississippi River bridge
# at Memphis, which that loop would otherwise use.
DEFAULT_START = (33.7490, -84.3880)
DEFAULT_END = (29.9511, -90.0715)
DEFAULT_STATES = ["Alabama", "Mississippi"]
DEFAULT_POINTS = [(35.1531, -90.0741)]

Ring = list[list[float]]
LatLon = tuple[float, float]


def load_states(path: Path = STATES_FILE) -> dict[str, dict]:
    """Return the outline table keyed by USPS code."""
    return json.loads(path.read_text())


def state_rings(states: dict[str, dict], key: str) -> list[Ring]:
    """Return the rings for a state given its USPS code or name.

    Args:
        states: Table from :func:`load_states`.
        key: ``"AL"``, ``"Alabama"``, or any case variant of either.

    Raises:
        KeyError: If nothing matches.
    """
    if key.upper() in states:
        return states[key.upper()]["rings"]
    for state in states.values():
        if state["name"].casefold() == key.casefold():
            return state["rings"]
    raise KeyError(f"unknown state {key!r}")


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    d_lat = lat2 - lat1
    d_lon = math.radians(b[1] - a[1])
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def perimeter_m(rings: list[Ring]) -> float:
    """Total perimeter of ``[lon, lat]`` rings, as Valhalla measures it."""
    return sum(
        haversine_m((ring[i][1], ring[i][0]), (ring[i + 1][1], ring[i + 1][0]))
        for ring in rings
        for i in range(len(ring) - 1)
    )


def decode_shape(encoded: str) -> list[LatLon]:
    """Decode a Valhalla polyline into (lat, lon) points."""
    points: list[LatLon] = []
    index = lat = lon = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            result = shift = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / SHAPE_PRECISION, lon / SHAPE_PRECISION))
    return points


def point_in_ring(point: LatLon, ring: Ring) -> bool:
    """Even-odd test of a (lat, lon) point against a ``[lon, lat]`` ring."""
    lat, lon = point
    inside = False
    for i in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < crossing:
                inside = not inside
    return inside


def route_points(result: dict) -> list[LatLon]:
    """All shape points of a route response, legs concatenated."""
    return [p for leg in result["trip"]["legs"] for p in decode_shape(leg["shape"])]


def points_inside(points: list[LatLon], rings: list[Ring]) -> int:
    """Count how many points fall inside any of the rings."""
    return sum(any(point_in_ring(p, ring) for ring in rings) for p in points)


def min_distance_m(points: list[LatLon], target: LatLon) -> float:
    """Closest approach of a shape to a target point, in metres."""
    return min(haversine_m(p, target) for p in points)


def _timed_route(**kwargs: object) -> tuple[dict, float]:
    """Call route_truck and return (response, seconds)."""
    started = time.perf_counter()
    result = route_truck(**kwargs)  # type: ignore[arg-type]
    return result, time.perf_counter() - started


def _print_row(label: str, result: dict, seconds: float) -> None:
    summary = result["trip"]["summary"]
    print(f"  {label:18s} {summary['length']:8.1f} mi  "
          f"{summary['time'] / 3600:5.2f} h  ({seconds:.1f} s)")


def _parse_latlon(text: str) -> LatLon:
    lat, lon = (float(part) for part in text.split(","))
    return lat, lon


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", action="append", metavar="NAME_OR_USPS",
                        help="state to exclude; repeatable")
    parser.add_argument("--point", action="append", type=_parse_latlon,
                        metavar="LAT,LON", help="point to exclude; repeatable")
    parser.add_argument("--from", dest="start", type=_parse_latlon,
                        default=DEFAULT_START, metavar="LAT,LON")
    parser.add_argument("--to", dest="end", type=_parse_latlon,
                        default=DEFAULT_END, metavar="LAT,LON")
    args = parser.parse_args()
    if args.state is None:
        args.state = DEFAULT_STATES
    if args.point is None:
        args.point = DEFAULT_POINTS
    return args


def main() -> int:
    """Route with and without the exclusions and return an exit code."""
    args = _parse_args()
    states = load_states()
    rings = [ring for key in args.state for ring in state_rings(states, key)]
    budget = perimeter_m(rings)
    print(f"Excluding {', '.join(args.state)}: {len(rings)} rings, "
          f"{budget / 1000:,.0f} km of perimeter; "
          f"{len(args.point)} point(s)")

    baseline, base_s = _timed_route(start=args.start, end=args.end)
    by_state, state_s = _timed_route(
        start=args.start, end=args.end, exclude_polygons=rings)
    combined, both_s = _timed_route(
        start=args.start, end=args.end, exclude_polygons=rings,
        exclude_locations=args.point)

    print("\n  scenario               miles        h   latency")
    _print_row("baseline", baseline, base_s)
    _print_row("states", by_state, state_s)
    _print_row("states + points", combined, both_s)

    ok = True
    shape = route_points(combined)
    inside = points_inside(shape, rings)
    print(f"\n  shape points inside excluded states: {inside} of {len(shape)} "
          f"(baseline: {points_inside(route_points(baseline), rings)})")
    if inside:
        print("  -> the route entered an excluded state", file=sys.stderr)
        ok = False
    for point in args.point:
        before = min_distance_m(route_points(by_state), point)
        after = min_distance_m(shape, point)
        print(f"  closest approach to {point}: {before:,.0f} m -> {after:,.0f} m")
        if after <= before:
            print("  -> the point exclusion did not move the route",
                  file=sys.stderr)
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.HTTPError as exc:
        body = exc.response.json() if exc.response is not None else {}
        print(f"Valhalla rejected the request (error_code "
              f"{body.get('error_code')}): {body.get('error', exc)}",
              file=sys.stderr)
        sys.exit(1)
    except (requests.RequestException, KeyError) as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        sys.exit(1)
