# State-Scale Route Exclusions — Design

**Date:** 2026-09-02
**Status:** Approved

## Purpose

The fuel-saving product must be able to route a truck around **whole states**
(any combination, chosen per request) together with **specific points**. The
existing `examples/route_avoid.py` shows both `exclude_locations` and
`exclude_polygons`, but the published image carries Valhalla's stock
`service_limits.max_exclude_polygons_length` of 10 000 m, so any state-sized
ring fails with error 167.

Deliverables: a raised, build-time-configurable limit in the image; a
committed table of simplified state outlines; a sample that excludes any mix
of states and points and proves the effect; README coverage. The USA image is
rebuilt from the 2026-09-01 Geofabrik extract so the fresh map and the new
limit ship together.

## Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where the limit lives | Dockerfile `ARG MAX_EXCLUDE_POLYGONS_LENGTH=50000000`, applied with `jq` to the baked `valhalla.json` after the tile build | It is a service setting read at startup, not a graph property. Applying it after the build keeps the tile layer cache intact when only the limit changes. |
| Default value | 50 000 000 m (50 000 km) | Any single state fits several times over (Texas 4 624 km); a dozen states fit. The lower 48 together are 94 925 km, an unrealistic request. |
| State outline source | US Census 1:20m cartographic boundaries, converted once and committed as `examples/us_states.json` | Public domain, already generalised to a few hundred points per state, deterministic and offline. Nominatim and Overpass were rejected: external dependency at run time, rate limits, and raw boundaries that would need simplifying. |
| Outline format | `{USPS: {"name", "rings": [[[lon, lat], …]]}}`, closed rings, 5 decimals, holes dropped | Passes to Valhalla unchanged. Holes are irrelevant to a wall. |
| Sample shape | New `examples/route_exclude_states.py` importing `route_truck` from `route_avoid.py` | Reuses the request builder; keeps each sample focused. |
| Proof of effect | Decode the returned shape; count points inside excluded rings; closest approach to each blocked point before/after | A distance delta alone cannot show the route stayed out of a state. |
| Map refresh | Full rebuild via the existing Dockerfile with `--no-cache` and `CONCURRENCY=1` | The download layer would otherwise be served from the July cache. Single-threaded is the recipe that fits this machine. |
| Architectures | One `buildx` run for `linux/arm64,linux/amd64`; builder stage pinned to `$BUILDPLATFORM` | Tiles are architecture-independent data. Building them once natively and copying into a final image per platform avoids emulation entirely, since the final stage has no `RUN`. The workflow publishes both. |

## How Valhalla applies a polygon

Valhalla collects the graph bins the ring's outline passes through and
forbids the edges in them that intersect the ring. Edges deep inside the ring
are untouched, but nothing inside can be reached without crossing the ring,
so the ring acts as a wall. Cost is therefore proportional to perimeter.

Measured on the published image (single request, Atlanta to New Orleans):

| Exclusion | Distance | Time | Latency | Shape points inside Alabama |
|---|---|---|---|---|
| none | 767 km | 427 min | 0.3 s | 3395 |
| Alabama (1 741 km ring) | 1 372 km | 758 min | 3.3 s | 0 |

## Components

- `Dockerfile` — new build-arg and a `jq` step in the builder stage.
- `examples/build_us_states.py` — downloads (or reads) the Census zip, emits
  `us_states.json`. Needs `pyshp`; listed in `examples/requirements.txt`.
- `examples/us_states.json` — 52 entries, 132 rings, 292 KB.
- `examples/route_exclude_states.py` — CLI: repeatable `--state` (name or
  USPS) and `--point LAT,LON`, `--from`, `--to`. Defaults: Atlanta to New
  Orleans excluding Alabama and Mississippi plus a point on the I-40 bridge
  at Memphis. Exit 1 if the proof fails or Valhalla rejects the request.
- `README.md` — "Excluding whole states" section, build-arg documentation.

## Error handling

- Unknown state name or code: `KeyError` reported and exit 1.
- Valhalla rejection (for example error 167 on a stock image): the error
  body is printed and exit 1, matching `route_avoid.py`.
- Origin or destination inside an excluded state: Valhalla returns no route;
  reported as a rejection. Documented as a caveat.

## Testing

No pytest harness exists in this repo; samples are proven against the live
service, as with the previous sample. Proof for this change: run
`route_exclude_states.py` with the defaults and with a second combination
against the freshly built image, and record the output in the plan. Pure
helpers (state lookup, perimeter, polyline decoding, point-in-ring) were
checked by hand against known values during development.

## Out of scope

- Changes to the superproject compose, `.env`, or backend.
- Buffering outlines outward.
- Alaska, Hawaii and Puerto Rico are in the table but outside the USA graph.
