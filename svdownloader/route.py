"""Route-based panorama discovery using OSRM routing."""

import math
import time

import requests

from svdownloader.metadata import get_metadata, search_panoramas
from svdownloader.models import PanoramaInfo

_OSRM_URL = (
    "http://router.project-osrm.org/route/v1/driving/"
    "{lon1},{lat1};{lon2},{lat2}"
    "?overview=full&geometries=polyline"
)

EARTH_RADIUS_M = 6_371_000


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two coordinates."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def interpolate(lat1: float, lon1: float, lat2: float, lon2: float, frac: float) -> tuple[float, float]:
    """Linear interpolation between two coordinates."""
    return (lat1 + frac * (lat2 - lat1), lon1 + frac * (lon2 - lon1))


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google-encoded polyline string into (lat, lon) pairs."""
    coords = []
    i = 0
    lat = 0
    lon = 0

    while i < len(encoded):
        # Decode latitude delta
        shift = 0
        result = 0
        while True:
            b = ord(encoded[i]) - 63
            i += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += (~(result >> 1) if (result & 1) else (result >> 1))

        # Decode longitude delta
        shift = 0
        result = 0
        while True:
            b = ord(encoded[i]) - 63
            i += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lon += (~(result >> 1) if (result & 1) else (result >> 1))

        coords.append((lat / 1e5, lon / 1e5))

    return coords


def get_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> list[tuple[float, float]]:
    """Get a driving route from OSRM and return decoded coordinates."""
    url = _OSRM_URL.format(lat1=start_lat, lon1=start_lon, lat2=end_lat, lon2=end_lon)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"OSRM routing failed: {data.get('code', 'unknown error')}")

    route = data["routes"][0]
    distance_m = route["distance"]
    duration_s = route["duration"]
    print(f"Route: {distance_m / 1000:.1f} km, ~{duration_s / 60:.0f} min drive")

    return decode_polyline(route["geometry"])


def sample_points(coords: list[tuple[float, float]], interval_m: float = 20) -> list[tuple[float, float]]:
    """Sample evenly-spaced points along a polyline."""
    if not coords:
        return []

    points = [coords[0]]
    carry = 0.0  # distance carried over from previous segment

    for j in range(len(coords) - 1):
        lat1, lon1 = coords[j]
        lat2, lon2 = coords[j + 1]
        seg_dist = haversine(lat1, lon1, lat2, lon2)

        if seg_dist == 0:
            continue

        offset = interval_m - carry
        while offset <= seg_dist:
            frac = offset / seg_dist
            points.append(interpolate(lat1, lon1, lat2, lon2, frac))
            offset += interval_m

        carry = seg_dist - (offset - interval_m)

    # Always include the last point
    if coords[-1] != points[-1]:
        points.append(coords[-1])

    return points


def find_route_panoramas(
    start: tuple[float, float],
    end: tuple[float, float],
    interval_m: float = 20,
    search_delay: float = 0.15,
) -> list[PanoramaInfo]:
    """Find all unique Street View panoramas along a route.

    Args:
        start: (lat, lon) of start point
        end: (lat, lon) of end point
        interval_m: sampling interval in meters
        search_delay: delay between API searches to avoid rate limiting

    Returns:
        Ordered list of unique PanoramaInfo objects along the route.
    """
    # 1. Get route
    route_coords = get_route(start[0], start[1], end[0], end[1])

    # 2. Sample points
    points = sample_points(route_coords, interval_m)
    print(f"Sampling {len(points)} points along route (every {interval_m}m)...")

    # 3. Search for panoramas at each point, deduplicating
    seen_ids: set[str] = set()
    panoramas: list[PanoramaInfo] = []

    for i, (lat, lon) in enumerate(points):
        try:
            results = search_panoramas(lat, lon, radius=30)
            if results:
                # Take the first result (closest to the point)
                pano = results[0]
                if pano.pano_id not in seen_ids:
                    seen_ids.add(pano.pano_id)
                    panoramas.append(pano)
        except Exception:
            pass  # Skip failed searches

        # Progress
        if (i + 1) % 10 == 0 or i == len(points) - 1:
            print(f"  Searched {i + 1}/{len(points)} points, found {len(panoramas)} unique panoramas", end="\r")

        if search_delay > 0:
            time.sleep(search_delay)

    print()  # newline after \r progress
    return panoramas
