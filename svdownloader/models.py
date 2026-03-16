"""Data classes for Street View panorama data."""

from dataclasses import dataclass, field
from typing import Optional

from PIL import Image


@dataclass
class PanoramaInfo:
    """Metadata about a Street View panorama."""

    pano_id: str
    lat: float = 0.0
    lon: float = 0.0
    date: Optional[str] = None
    image_sizes: list[tuple[int, int]] = field(default_factory=list)
    tile_size: tuple[int, int] = (512, 512)
    max_zoom: int = 5
    heading: Optional[float] = None
    pitch: Optional[float] = None

    def grid_size(self, zoom: int) -> tuple[int, int]:
        """Return (cols, rows) for the tile grid at the given zoom level."""
        if zoom < len(self.image_sizes):
            w, h = self.image_sizes[zoom]
            tw, th = self.tile_size
            cols = -(-w // tw)  # ceil division
            rows = -(-h // th)
            return cols, rows
        # Fallback: standard formula
        return 2**zoom, 2 ** (zoom - 1) if zoom > 0 else 1

    def pixel_size(self, zoom: int) -> tuple[int, int]:
        """Return (width, height) in pixels at the given zoom level."""
        if zoom < len(self.image_sizes):
            return self.image_sizes[zoom]
        cols, rows = self.grid_size(zoom)
        return cols * self.tile_size[0], rows * self.tile_size[1]


@dataclass
class TileResult:
    """A downloaded tile and its grid position."""

    x: int
    y: int
    image: Image.Image
