# Publishes a Valhalla image with the routing graph BAKED IN, so consumers
# `docker pull` a ready-to-route image instead of building tiles at deploy time.
#
# The builder stage downloads an OSM extract and builds the tiles + tile_extract
# tar; the final stage carries only the engine plus the baked /custom_files and
# serves them (no download, no rebuild) on start.
#
# PBF_URL selects the extract to bake. Default is continental USA. Continental
# USA needs ~100 GB disk + lots of RAM + hours and will NOT build on a
# GitHub-hosted runner — use a self-hosted/large runner, or override PBF_URL
# with a smaller regional extract:
#   docker build --build-arg PBF_URL=https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf .
ARG VALHALLA_VERSION=3.5.1

# --------------------------------------------------------------------------- #
# Builder: download the extract and build the graph + tar.
# --------------------------------------------------------------------------- #
FROM ghcr.io/gis-ops/docker-valhalla/valhalla:${VALHALLA_VERSION} AS builder

ARG PBF_URL=https://download.geofabrik.de/north-america/us-latest.osm.pbf
# Tile-builder thread count. Empty = all cores (fast, high peak RAM). Set to 1
# to build single-threaded, which keeps peak memory low enough for a big extract
# (e.g. USA) on a memory-constrained machine — much slower, but it fits.
ARG CONCURRENCY=
# Total perimeter (metres) Valhalla accepts across all exclude_polygons in one
# request (service_limits.max_exclude_polygons_length; the binary default is
# 10,000). fuel-saving-backend budgets its exclusion zones against this value
# (app/api/geofences.py) -- keep the two in sync. TMS-1557.
ARG MAX_EXCLUDE_POLYGONS_LENGTH=100000

USER root
WORKDIR /custom_files

# Download the extract in its own layer so a failed build doesn't re-download.
RUN set -eux; \
    mkdir -p /custom_files/admin_data /custom_files/timezone_data; \
    curl -fSL --retry 3 -o /custom_files/data.osm.pbf "${PBF_URL}"

# Build the graph + tar. Concurrency is baked into the config, so every
# build_* step below honours it.
RUN set -eux; \
    valhalla_build_config \
      --mjolnir-tile-dir /custom_files/valhalla_tiles \
      --mjolnir-tile-extract /custom_files/valhalla_tiles.tar \
      --mjolnir-timezone /custom_files/timezone_data/timezones.sqlite \
      --mjolnir-admin /custom_files/admin_data/admins.sqlite \
      ${CONCURRENCY:+--mjolnir-concurrency ${CONCURRENCY}} \
      --service-limits-max-exclude-polygons-length ${MAX_EXCLUDE_POLYGONS_LENGTH} \
      > /custom_files/valhalla.json; \
    valhalla_build_timezones > /custom_files/timezone_data/timezones.sqlite; \
    valhalla_build_admins -c /custom_files/valhalla.json /custom_files/data.osm.pbf; \
    valhalla_build_tiles -c /custom_files/valhalla.json /custom_files/data.osm.pbf; \
    valhalla_build_extract -c /custom_files/valhalla.json -v; \
    # Keep the tar (served via tile_extract); drop the loose tiles and the PBF.
    rm -rf /custom_files/valhalla_tiles /custom_files/data.osm.pbf

# --------------------------------------------------------------------------- #
# Final: engine + baked graph, serve-only.
# --------------------------------------------------------------------------- #
FROM ghcr.io/gis-ops/docker-valhalla/valhalla:${VALHALLA_VERSION}

# Links the published GHCR package to this repo (shows under the repo's Packages).
LABEL org.opencontainers.image.source="https://github.com/rytisss/OSM-valhalla"

# The container runs as uid/gid 59999; own the baked files accordingly.
COPY --from=builder --chown=59999:59999 /custom_files /custom_files

# Serve the baked tiles immediately: never download, never rebuild.
ENV serve_tiles=True \
    use_tiles_ignore_pbf=True \
    force_rebuild=False \
    build_tar=False
