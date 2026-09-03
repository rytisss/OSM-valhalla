#!/usr/bin/env python3
"""Generate ``us_states.json``: simplified state outlines for exclude_polygons.

Source: the US Census Bureau's public-domain 1:20,000,000 cartographic
boundary file for states (``cb_<year>_us_state_20m``). That scale is already
generalised to a few hundred points per state, which is what a routing wall
needs: Valhalla only removes the road edges that *cross* a ring, so request
cost grows with the ring's perimeter, not with the area inside it.

Output shape, keyed by USPS code::

    {"AL": {"name": "Alabama", "rings": [[[lon, lat], ...], ...]}, ...}

Every ring is closed (first point repeated last) and in ``[lon, lat]`` order,
so it can be passed to Valhalla unchanged. Holes are dropped; only exterior
rings matter for a wall.

Usage:
    python examples/build_us_states.py                 # downloads the zip
    python examples/build_us_states.py --zip cb.zip    # uses a local copy
"""
import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import requests
import shapefile

CENSUS_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_20m.zip"
)
DEFAULT_OUTPUT = Path(__file__).with_name("us_states.json")
# Metres at the equator per 1e-5 degree is ~1.1 m: plenty for a routing wall.
DECIMALS = 5


def _fetch_zip(url: str) -> bytes:
    """Download the boundary zip and return its bytes."""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def _open_shapefile(zip_bytes: bytes) -> shapefile.Reader:
    """Open the .shp/.shx/.dbf trio inside a Census zip without extracting."""
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    members = {Path(name).suffix: name for name in archive.namelist()}
    return shapefile.Reader(
        shp=io.BytesIO(archive.read(members[".shp"])),
        shx=io.BytesIO(archive.read(members[".shx"])),
        dbf=io.BytesIO(archive.read(members[".dbf"])),
    )


def _exterior_rings(geometry: dict) -> list[list[list[float]]]:
    """Return the closed exterior ring of every polygon in a GeoJSON geometry."""
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise ValueError(f"unexpected geometry type {geometry['type']}")
    rings = []
    for polygon in polygons:
        ring = [[round(lon, DECIMALS), round(lat, DECIMALS)]
                for lon, lat in polygon[0]]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        rings.append(ring)
    return rings


def build_states(reader: shapefile.Reader) -> dict[str, dict]:
    """Return ``{usps: {"name": ..., "rings": [...]}}`` for every record."""
    states: dict[str, dict] = {}
    for record in reader.shapeRecords():
        attributes = record.record.as_dict()
        states[attributes["STUSPS"]] = {
            "name": attributes["NAME"],
            "rings": _exterior_rings(record.shape.__geo_interface__),
        }
    return dict(sorted(states.items()))


def main() -> int:
    """Build the outline file and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path,
                        help="local copy of the Census zip (skips download)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    zip_bytes = args.zip.read_bytes() if args.zip else _fetch_zip(CENSUS_URL)
    states = build_states(_open_shapefile(zip_bytes))
    args.output.write_text(json.dumps(states, separators=(",", ":")) + "\n")
    rings = sum(len(state["rings"]) for state in states.values())
    print(f"wrote {len(states)} states, {rings} rings -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
