"""Input parsing and helper utilities."""

import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class ParsedInput:
    type: Literal["pano_id", "url", "coords"]
    value: str
    lat: float | None = None
    lon: float | None = None


# Pattern to extract pano ID from Google Maps URLs
_PANO_URL_PATTERN = re.compile(r"!1s([^!]+?)!2e")
# Alternative: pano ID in @lat,lng,... format URLs with /data= section
_PANO_URL_ALT = re.compile(r"/data=.*!1s([A-Za-z0-9_-]+)")
# Coordinate pattern: lat,lon (both can be negative, with decimals)
_COORDS_PATTERN = re.compile(
    r"^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$"
)
# Google Maps @lat,lng URL pattern
_MAPS_AT_PATTERN = re.compile(
    r"@(-?\d+\.?\d+),(-?\d+\.?\d+)"
)


def parse_input(input_str: str) -> ParsedInput:
    """Determine if input is a Google Maps URL, coordinates, or raw pano ID."""
    input_str = input_str.strip()

    # Check for Google Maps URL
    if "google.com/maps" in input_str or "goo.gl/maps" in input_str:
        match = _PANO_URL_PATTERN.search(input_str)
        if not match:
            match = _PANO_URL_ALT.search(input_str)
        if match:
            return ParsedInput(type="url", value=match.group(1))
        # Try to extract coordinates from URL
        coord_match = _MAPS_AT_PATTERN.search(input_str)
        if coord_match:
            lat, lon = float(coord_match.group(1)), float(coord_match.group(2))
            return ParsedInput(type="coords", value=input_str, lat=lat, lon=lon)
        raise ValueError(f"Could not extract panorama ID or coordinates from URL: {input_str}")

    # Check for lat,lon coordinates
    coord_match = _COORDS_PATTERN.match(input_str)
    if coord_match:
        lat, lon = float(coord_match.group(1)), float(coord_match.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return ParsedInput(type="coords", value=input_str, lat=lat, lon=lon)

    # Treat as raw panorama ID
    return ParsedInput(type="pano_id", value=input_str)


def sanitize_filename(pano_id: str) -> str:
    """Make a pano ID safe for use as a filename."""
    return re.sub(r"[^\w\-]", "_", pano_id)
