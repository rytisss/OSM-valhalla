# State-Scale Route Exclusions — Implementation Record

Spec: `docs/superpowers/specs/2026-09-02-state-exclusions-design.md`.
Branch: `feature/state_exclusions`.

## Tasks

- [x] `Dockerfile`: `MAX_EXCLUDE_POLYGONS_LENGTH` build-arg (default
      50 000 000 m) applied with `jq` after the tile build.
- [x] `Dockerfile`: builder stage pinned to `$BUILDPLATFORM`; one native tile
      build feeds a final image per target platform. Workflow publishes
      `linux/amd64,linux/arm64`.
- [x] `examples/build_us_states.py` + `examples/us_states.json` (52 entries,
      132 rings, 292 KB) from the Census 1:20m boundaries.
- [x] `examples/route_exclude_states.py`: `--state`/`--point` CLI, shape-based
      proof, exit 1 on failure.
- [x] README: "Excluding whole states", build-arg and multi-platform notes.
- [x] Rebuild the USA image from the 2026-09-01 Geofabrik extract.
- [x] Proof runs against the fresh image (below).

## Build record

```
docker buildx build --no-cache --platform linux/arm64,linux/amd64 \
  --build-arg CONCURRENCY=1 -t ghcr.io/rytisss/osm-valhalla:usa-20260901 --load .
```

Apple M-series, 8 GB Docker VM, single-threaded tile build. Download 7.4 min,
admins 14 min, tiles 6.8 h, tar 1 min, export 12 min. Peak extra host disk
about 90 GB. Result: one tag with two variants, each carrying the same
20.26 GB `valhalla_tiles.tar` and `max_exclude_polygons_length = 50000000`.

## Proof

Sample run against `ghcr.io/rytisss/osm-valhalla:usa-20260901` (arm64
variant, port 8012).

```
$ python examples/route_exclude_states.py
Excluding Alabama, Mississippi: 2 rings, 3,532 km of perimeter; 1 point(s)

  scenario               miles        h   latency
  baseline              476.5 mi   7.11 h  (0.1 s)
  states               1061.6 mi  16.30 h  (10.6 s)
  states + points      1063.5 mi  16.36 h  (10.3 s)

  shape points inside excluded states: 0 of 12682 (baseline: 4151)
  closest approach to (35.1531, -90.0741): 4 m -> 2,286 m
exit=0
```

```
$ python examples/route_exclude_states.py --state Oklahoma --state "New Mexico" \
    --point 36.39992,-94.18502 --from 32.7767,-96.7970 --to 39.7392,-104.9903
Excluding Oklahoma, New Mexico: 2 rings, 4,748 km of perimeter; 1 point(s)

  scenario               miles        h   latency
  baseline              818.3 mi  12.33 h  (0.2 s)
  states               1182.3 mi  17.73 h  (4.5 s)
  states + points      1182.9 mi  17.80 h  (4.5 s)

  shape points inside excluded states: 0 of 13281 (baseline: 840)
  closest approach to (36.39992, -94.18502): 1 m -> 2,780 m
exit=0
```

A third run (Atlanta → Denver excluding Texas and Oklahoma, 6 993 km) took
29.7 s and left the route unchanged, because the baseline never enters either
state; recorded in the README as the latency ceiling seen so far.

## Lessons

- A point exclusion must sit on the road itself. The first default point was
  484 m from the I-40 bridge deck, snapped to a side street, and changed
  nothing. Take blocked points from a route's own shape.
- Latency tracks the number of road edges crossing the outline, not just its
  length: Alabama + Mississippi (river borders through dense areas) cost twice
  as much as Oklahoma + New Mexico despite a shorter perimeter.
