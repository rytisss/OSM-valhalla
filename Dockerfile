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
#
# Pinned to the *build* machine's platform on purpose: the tiles are plain
# data, identical on every architecture, so they are built once natively and
# copied into a final image per target platform. The final stage has no RUN,
# so a multi-platform build needs no emulation:
#   docker buildx build --platform linux/arm64,linux/amd64 -t osm-valhalla:usa --load .
# --------------------------------------------------------------------------- #
FROM --platform=$BUILDPLATFORM ghcr.io/gis-ops/docker-valhalla/valhalla:${VALHALLA_VERSION} AS builder

ARG PBF_URL=https://download.geofabrik.de/north-america/us-latest.osm.pbf
# Tile-builder thread count. Empty = all cores (fast, high peak RAM). Set to 1
# to build single-threaded, which keeps peak memory low enough for a big extract
# (e.g. USA) on a memory-constrained machine — much slower, but it fits.
ARG CONCURRENCY=

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
      > /custom_files/valhalla.json; \
    valhalla_build_timezones > /custom_files/timezone_data/timezones.sqlite; \
    valhalla_build_admins -c /custom_files/valhalla.json /custom_files/data.osm.pbf; \
    valhalla_build_tiles -c /custom_files/valhalla.json /custom_files/data.osm.pbf; \
    valhalla_build_extract -c /custom_files/valhalla.json -v; \
    # Keep the tar (served via tile_extract); drop the loose tiles and the PBF.
    rm -rf /custom_files/valhalla_tiles /custom_files/data.osm.pbf

# Total perimeter (metres) a request may pass in exclude_polygons. Valhalla's
# default of 10 000 m only fits a few city blocks; the fuel-saving backend
# excludes whole states (Alabama's simplified outline alone is ~1 750 km), so
# the baked config carries a far larger budget. It is a service_limits entry
# read at startup, not a graph property, so changing it never rebuilds tiles.
ARG MAX_EXCLUDE_POLYGONS_LENGTH=50000000
RUN set -eux; \
    jq --argjson n "${MAX_EXCLUDE_POLYGONS_LENGTH}" \
      '.service_limits.max_exclude_polygons_length = $n' \
      /custom_files/valhalla.json > /custom_files/valhalla.json.new; \
    mv /custom_files/valhalla.json.new /custom_files/valhalla.json

# --------------------------------------------------------------------------- #
# Final: engine + baked graph, serve-only. One per --platform requested.
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
