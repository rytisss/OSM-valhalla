# Route Exclusions (Avoid Points / Areas) — Design

**Date:** 2026-08-04
**Status:** Approved

## Purpose

Add a reference sample showing how to make Valhalla route **around** places:
a specific point (a closed ramp, a blocked street) and a whole area (a zone a
truck must not enter). Today `examples/route_truck.py` shows only a plain A→B
truck route, and neither exclusion mechanism is documented in this repo.

The deliverable is `examples/route_avoid.py` plus a short README section.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sample shape | New standalone `examples/route_avoid.py` | Keeps `route_truck.py` as the minimal "hello world"; exclusion gets its own focused file (SRP). No refactor of the existing example. |
| Mechanisms shown | Both `exclude_locations` and `exclude_polygons` | They solve different problems and have different gotchas. |
| Scenarios | Two hardcoded routes, one per mechanism | Each mechanism is demonstrated where it actually produces a visible detour (see Verification). |
| Proof of effect | Terminal before/after summary | No extra dependencies, works headless. A non-zero delta *is* the proof. |
| Geography | US coordinates, matching `route_truck.py` | Consistent with the existing sample and the USA tileset. Requires USA/Midwest tiles. |
| Dependencies | `requests` only | `examples/requirements.txt` unchanged. |

## The two mechanisms

| Mechanism | Request field | Coordinate order | Meaning |
|---|---|---|---|
| Point | `exclude_locations: [{"lat": …, "lon": …}]` | `lat`/`lon` keys | Valhalla snaps to the **nearest edge(s)** and forbids them. |
| Area | `exclude_polygons: [[[lon, lat], …]]` | **`[lon, lat]` pairs**, GeoJSON order | The route may not cross the ring at all. |

Two gotchas the sample must teach, both confirmed against a live 3.5.1 service:

1. **`exclude_polygons` uses `[lon, lat]`** — the opposite order from
   `locations`. Swapping them silently puts the polygon in the wrong hemisphere
   and the route is unchanged.
2. **`exclude_locations` only removes the nearest edges.** On a motorway, the
   edge between interchanges is long, so the router rejoins the same highway
   almost immediately. Measured on Chicago → Indianapolis: excluding a point on
   I-65 changed the route by **13 metres** (the path merely moved from 6.6 m to
   73.7 m away from the blocked point). Point exclusion is for surgical blocking
   of a specific street or ramp; **`exclude_polygons` is the tool for "the route
   must not pass through here."**

## Constraint: polygon circumference limit

`service_limits.max_exclude_polygons_length` defaults to **10 000 m of total
perimeter** in a `valhalla_build_config` config, which this image uses.
Exceeding it fails the whole request:

```
HTTP 400 {"error_code": 167,
          "error": "Exceeded maximum circumference for exclude_polygons: 10000 meters"}
```

A 0.05° box is ~19 km of perimeter and is rejected. The sample uses a **0.01°
half-width** box (≈2.2 × 1.7 km, ~7.8 km perimeter), safely under the cap, and
the docstring explains why the box is small.

## Scenarios

Both are module-level constants so a reader can edit them in place.

**1. Point exclusion — short Chicago hop.**
`(41.8781, -87.6298)` → `(41.8850, -87.6700)`, blocking
`(41.876094, -87.656109)` on the Eisenhower Expressway (I-290).
Measured: **2.863 mi → 4.753 mi (+1.89 mi)**.

**2. Polygon exclusion — Chicago → Indianapolis** (the same pair as
`route_truck.py`), blocking a 0.01°-half-width box centred on
`(40.4163, -86.8198)`, a point on I-65 near Lafayette, IN taken from the
baseline route's own shape.
Measured: **186.6 mi → 189.1 mi (+2.5 mi)**.

The I-65 point was picked by decoding the baseline route's polyline rather than
by eyeballing a coordinate: an initial hand-picked guess of `(40.42, -86.88)`
was ~5 km off the route and would have blocked a side road, printing a 0.0
delta while looking correct.

## Structure of `examples/route_avoid.py`

Self-contained and mirroring `route_truck.py`, so it stays copy-pasteable:

- **Module docstring** — both mechanisms, the `[lon, lat]` order, the long-edge
  caveat, the circumference cap, and how to run it.
- **Constants** — `BASE_URL`, `TRUCK_OPTIONS`, the two scenarios' start/end,
  `BLOCKED_POINT`, `BLOCKED_AREA` (built by a `_box()` helper from a centre and
  a half-width, so the perimeter maths is visible).
- **`route_truck(start, end, *, exclude_locations=None, exclude_polygons=None,
  base_url=BASE_URL) -> dict`** — builds the truck payload, omits the exclusion
  keys when they are empty, POSTs `/route`, returns the parsed JSON.
- **`_box(centre, half_width) -> list[list[float]]`** — closed `[lon, lat]` ring.
- **`_summary(result) -> tuple[float, float]`** — `(miles, hours)` from
  `trip.summary`.
- **`main()`** — runs the four requests (two baselines, two excluded) and prints
  a labelled comparison with the delta against each baseline.

Full type annotations and Google-style docstrings on public functions, per
AGENTS.md rules 4 and 5.

## Error Handling

Valhalla reports failures as **HTTP 400 with a JSON body**, so a bare
`raise_for_status()` would discard the useful message. The sample catches
`requests.HTTPError`, prints Valhalla's own `error` text together with its
`error_code`, and exits non-zero. Codes seen in practice:

| Code | Meaning | When |
|---|---|---|
| 167 | Exceeded maximum circumference for `exclude_polygons` | Polygon too large |
| 442 | No path could be found for input | Exclusion seals off the destination, or no truck-legal path exists |

No bare `except:` and no silently swallowed errors, per AGENTS.md rule 9.

## Testing / Verification

This repo has no pytest harness (`examples/requirements.txt` is `requests`
only), and adding one for a reference sample is out of scope. Verification is
running the script against a live USA-tiled service and showing its output:

- Both baselines return a trip.
- Both exclusion runs return a **larger** distance than their baseline —
  a zero delta means the exclusion missed the road and is a failure.
- Expected: ~+1.9 mi for the point scenario, ~+2.5 mi for the polygon scenario.
- Additionally, an oversized polygon is confirmed to surface error 167 as a
  readable message rather than a stack trace.

Exact distances depend on the tileset vintage, so the README quotes them as
approximate.

## Documentation

`README.md` gains a short **"Avoiding places"** subsection under *Querying*:
the two request fields, the `[lon, lat]` order, the 10 km circumference cap,
the long-edge caveat for `exclude_locations`, and a pointer to the sample.

## Out of Scope (YAGNI)

- GeoJSON or HTML map output of the routes.
- CLI arguments — the scenarios are editable constants.
- Refactoring `examples/route_truck.py`.
- Raising `max_exclude_polygons_length` in the image config.
- Other exclusion knobs (`exclude_bridges`/`exclude_tunnels`/`exclude_tolls`),
  which are costing options, not geometry.
