"""Panorama ID resolution and metadata fetching."""

import json
import re

import requests

from svdownloader.models import PanoramaInfo

_SEARCH_URL = (
    "https://maps.googleapis.com/maps/api/js/"
    "GeoPhotoService.SingleImageSearch"
    "?pb=!1m5!1sapiv3!5sUS!11m2!1m1!1b0!2m4!1m2!3d{lat}!4d{lon}!2d{radius}!3m10"
    "!2m2!1sen!2sGB!9m1!1e2!11m4!1m3!1e2!2b1!3e2!4m10!1e1!1e2!1e3!1e4"
    "!1e8!1e6!5m1!1e2!6m1!1e2"
    "&callback=_cb"
)


def get_metadata(pano_id: str) -> PanoramaInfo:
    """Build metadata for a panorama using standard grid formula.

    Google Street View tiles follow a fixed pattern:
    - Tile size: 512x512
    - Grid at zoom z: 2^z columns x 2^(z-1) rows
    - Max zoom: 5 (native quality)
    """
    info = PanoramaInfo(pano_id=pano_id)
    info.max_zoom = 5
    info.tile_size = (512, 512)
    info.image_sizes = []
    for z in range(6):
        cols = max(1, 2**z)
        rows = max(1, 2 ** (z - 1)) if z > 0 else 1
        info.image_sizes.append((cols * 512, rows * 512))
    return info


def search_panoramas(lat: float, lon: float, radius: float = 50) -> list[PanoramaInfo]:
    """Find Street View panoramas near the given coordinates."""
    url = _SEARCH_URL.format(lat=lat, lon=lon, radius=radius)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    text = resp.text.strip()

    # Parse JSONP: _cb( ... )
    match = re.search(r"_cb\(\s*(.*)\s*\)$", text)
    if not match:
        return []

    data = json.loads(match.group(1))

    if data == [[5, "generic", "Search returned no images."]]:
        return []

    results = []
    try:
        subset = data[1][5][0]
        raw_panos = subset[3][0]

        # Dates align with the last N panos (reversed order)
        raw_dates = []
        if len(subset) >= 9 and subset[8] is not None:
            raw_dates = subset[8]

        # Build date lookup: reverse both to align dates with panos
        reversed_panos = raw_panos[::-1]
        reversed_dates = raw_dates[::-1]
        dates = [f"{d[1][0]}-{d[1][1]:02d}" for d in reversed_dates]
        date_map = {}
        for i, pano in enumerate(reversed_panos):
            try:
                pid = pano[0][1]
                if i < len(dates):
                    date_map[pid] = dates[i]
            except (IndexError, KeyError, TypeError):
                continue

        # Process panos in original order (old-format IDs first)
        for pano in raw_panos:
            try:
                pano_id = pano[0][1]
                info = get_metadata(pano_id)
                info.lat = float(pano[2][0][2])
                info.lon = float(pano[2][0][3])
                info.heading = float(pano[2][2][0])
                info.date = date_map.get(pano_id)
                results.append(info)
            except (IndexError, KeyError, TypeError):
                continue
    except (IndexError, KeyError, TypeError):
        pass

    return results
