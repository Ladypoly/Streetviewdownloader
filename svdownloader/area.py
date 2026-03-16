"""Area-based panorama discovery using grid sampling."""

import math
import time

from svdownloader.metadata import get_metadata, search_panoramas
from svdownloader.models import PanoramaInfo

# Meters per degree of latitude (approximately constant)
_M_PER_DEG_LAT = 111_320


def bbox_from_radius(center_lat: float, center_lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Convert a center point + radius into a bounding box (north, south, east, west)."""
    lat_offset = radius_m / _M_PER_DEG_LAT
    lon_offset = radius_m / (_M_PER_DEG_LAT * math.cos(math.radians(center_lat)))
    return (
        center_lat + lat_offset,  # north
        center_lat - lat_offset,  # south
        center_lon + lon_offset,  # east
        center_lon - lon_offset,  # west
    )


def find_radius_panoramas(
    center_lat: float,
    center_lon: float,
    radius_m: float = 200,
    spacing_m: float = 50,
    search_delay: float = 0.15,
) -> list[PanoramaInfo]:
    """Find all unique Street View panoramas within a radius of a center point."""
    north, south, east, west = bbox_from_radius(center_lat, center_lon, radius_m)
    print(f"Searching {radius_m:.0f}m radius around ({center_lat:.5f}, {center_lon:.5f})...")
    return find_area_panoramas(north, south, east, west, spacing_m, search_delay)


def generate_grid(
    north: float,
    south: float,
    east: float,
    west: float,
    spacing_m: float = 50,
) -> list[tuple[float, float]]:
    """Generate a regular grid of (lat, lon) points over a bounding box."""
    # Ensure bounds are correct
    if north < south:
        north, south = south, north
    if east < west:
        east, west = west, east

    mid_lat = (north + south) / 2
    lat_step = spacing_m / _M_PER_DEG_LAT
    lon_step = spacing_m / (_M_PER_DEG_LAT * math.cos(math.radians(mid_lat)))

    points = []
    lat = south
    while lat <= north:
        lon = west
        while lon <= east:
            points.append((lat, lon))
            lon += lon_step
        lat += lat_step

    return points


def find_area_panoramas(
    north: float,
    south: float,
    east: float,
    west: float,
    spacing_m: float = 50,
    search_delay: float = 0.15,
) -> list[PanoramaInfo]:
    """Find all unique Street View panoramas within a bounding box.

    Args:
        north, south, east, west: Bounding box coordinates.
        spacing_m: Grid sampling interval in meters.
        search_delay: Delay between API searches to avoid rate limiting.

    Returns:
        List of unique PanoramaInfo objects found in the area.
    """
    grid = generate_grid(north, south, east, west, spacing_m)

    width_m = _M_PER_DEG_LAT * math.cos(math.radians((north + south) / 2)) * abs(east - west)
    height_m = _M_PER_DEG_LAT * abs(north - south)
    print(f"Area: ~{width_m:.0f}m x {height_m:.0f}m ({len(grid)} grid points at {spacing_m}m spacing)")

    seen_ids: set[str] = set()
    panoramas: list[PanoramaInfo] = []

    for i, (lat, lon) in enumerate(grid):
        try:
            results = search_panoramas(lat, lon, radius=spacing_m)
            for pano in results:
                if pano.pano_id not in seen_ids:
                    seen_ids.add(pano.pano_id)
                    panoramas.append(pano)
        except Exception:
            pass

        if (i + 1) % 10 == 0 or i == len(grid) - 1:
            print(f"  Searched {i + 1}/{len(grid)} points, found {len(panoramas)} unique panoramas", end="\r")

        if search_delay > 0:
            time.sleep(search_delay)

    print()
    return panoramas
