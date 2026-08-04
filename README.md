# OSM Valhalla — USA Routing Service

Self-hosted [Valhalla](https://github.com/valhalla/valhalla) routing engine
covering the continental USA, served at `http://localhost:8002`. Supports
auto, truck, bicycle, and pedestrian costing. Queryable by any local script.

## Actions

| Action | Command | Effect |
|--------|---------|--------|
| **Pull** (tiles baked in) | `docker pull ghcr.io/rytisss/osm-valhalla` | Ready-to-route image — graph is baked in at build time. No mount, no build. See [Packaging](#packaging--tiles-baked-into-the-image). |
| **Serve** (local tiles) | `docker compose up -d` | Serves cached tiles from a mounted `custom_files/` **(after a local build)**. No download, no rebuild. |
| **Build** (once) | `scripts/build.sh` | Downloads the USA PBF and builds tiles locally. Hours; ~100+ GB disk. |
| **Rebuild** (on demand) | `scripts/rebuild.sh` | Clears cache, fetches the **newest** map, rebuilds. |

After the initial build, nothing downloads or rebuilds automatically — you are always the trigger. **Run `scripts/build.sh` before your first `docker compose up`**: an `up` with no tiles present will auto-download and build (hours).

## Setup

```bash
cp .env.example .env        # adjust VALHALLA_PORT / PBF_URL if needed
scripts/build.sh            # one-time: download + build tiles (hours)
docker compose logs -f valhalla   # watch until tiles are loaded
```

After the build, the API is live. Routine restarts just serve the cache:

```bash
docker compose up -d
```

## Refresh to the newest map

```bash
scripts/rebuild.sh          # destructive: clears cache, rebuilds from latest
```

## Querying

Health check:

```bash
curl http://localhost:8002/status
```

Truck route (curl):

```bash
curl http://localhost:8002/route -d '{
  "locations":[{"lat":41.8781,"lon":-87.6298},{"lat":39.7684,"lon":-86.1581}],
  "costing":"truck",
  "units":"miles"
}'
```

Python (see `examples/route_truck.py`):

```bash
pip install -r examples/requirements.txt
python examples/route_truck.py
```

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

Requires Python 3.10+ (the sample uses `X | None` annotations).

Two things to know:

- **Polygons are size-capped.** `service_limits.max_exclude_polygons_length`
  defaults to 10 000 m of total perimeter; a bigger ring fails the request with
  `error_code` 167. The ~2 × 1.7 km box above is ~7 840 m of perimeter — 78% of
  the budget — and that budget is shared across every polygon in the request,
  so a second zone can easily push you over.
- **`exclude_locations` only removes the nearest edges.** On a motorway, where
  the edge between interchanges is long, the route can rejoin the same highway
  within metres — blocking a point on I-65 shifted a Chicago → Indianapolis
  route by 13 m. Reach for `exclude_polygons` when a zone must really be avoided.

Other endpoints: `/route`, `/sources_to_targets` (matrix), `/isochrone`,
`/optimized_route`. Pass `"costing":"truck"` plus optional
`costing_options.truck` (height, weight, axle_load, length, width, hazmat).

## Packaging — tiles baked into the image

The image published to GHCR as `ghcr.io/rytisss/osm-valhalla` now **bakes the
routing graph in** (see `Dockerfile`): a multi-stage build downloads an OSM
extract, builds the tiles + `valhalla_tiles.tar`, and copies them into the
final image. Consumers `docker pull` a **ready-to-route** image — no volume,
no download, no build at deploy time. `.github/workflows/docker-publish.yml`
publishes via **manual dispatch only** (auto-building on push would try to
build USA on a hosted runner and fail — publish USA by building locally and
`docker push`).

The extract is chosen by the `PBF_URL` build-arg (default: continental USA):

```bash
# Bake a small region (fast, fits any machine):
docker build --build-arg PBF_URL=https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf -t osm-valhalla:dc .
docker run --rm -p 8002:8002 osm-valhalla:dc     # routes immediately, no mount
```

> ⚠️ **The graph is built during `docker build`, so the builder needs the
> resources.** Continental USA needs **~100 GB disk, lots of RAM, and hours** —
> it will **not** build on a GitHub-hosted runner. For USA, run the workflow on
> a **self-hosted/large runner**, or build & push locally. Use the
> `workflow_dispatch` `pbf_url` input to bake a smaller region on hosted CI.
> Images are `linux/amd64`; arm64 hosts run them via emulation.

After the **first** publish, make the package public (repo → Packages →
package settings → visibility), or `docker compose pull` will need a GHCR
login. To run against upstream instead, set `VALHALLA_IMAGE` in `.env`.

Because tiles live in the image, a consumer that mounts a volume over
`/custom_files` should use a **fresh** one (an empty named volume is populated
from the image; a stale/empty bind mount would shadow the baked tiles).

## Requirements / notes

- First build needs **~100+ GB free disk**, several GB RAM, and a few hours.
- The service is unavailable during a build/rebuild.
- `custom_files/` holds the PBF + tiles and is git-ignored — never committed.
