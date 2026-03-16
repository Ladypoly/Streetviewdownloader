"""
Tile extraction module.
Calculates tile grid positions and extracts tiles from equirectangular images.
"""

import numpy as np
from pathlib import Path
from PIL import Image
from dataclasses import dataclass

from svdownloader.projection import equirect_to_rectilinear, calculate_focal_length_mm


@dataclass
class TileInfo:
    """Information about a single extracted tile."""
    yaw_deg: float
    pitch_deg: float
    fov_deg: float
    row: int
    col: int
    focal_length_mm: float


def calculate_tile_grid(
    fov_deg: float = 90.0,
    overlap: float = 0.4,
    pitch_range: tuple[float, float] = (-60.0, 60.0)
) -> list[tuple[float, float]]:
    """
    Calculate yaw/pitch positions for tiles to cover the sphere with overlap.

    Args:
        fov_deg: Field of view in degrees
        overlap: Minimum overlap ratio (0.0 to 1.0)
        pitch_range: (min_pitch, max_pitch) in degrees

    Returns:
        List of (yaw, pitch) tuples in degrees
    """
    # Angular step based on FOV and overlap
    step_deg = fov_deg * (1 - overlap)

    # Calculate horizontal positions (full 360)
    num_horizontal = int(np.ceil(360 / step_deg))
    yaw_step = 360 / num_horizontal
    yaws = [i * yaw_step for i in range(num_horizontal)]

    # Calculate vertical positions
    min_pitch, max_pitch = pitch_range
    pitch_span = max_pitch - min_pitch

    # At least one row at center, add more based on pitch range
    num_vertical = max(1, int(np.ceil(pitch_span / step_deg)))

    if num_vertical == 1:
        pitches = [0.0]
    else:
        # Distribute pitches evenly across the range
        pitch_step = pitch_span / (num_vertical - 1) if num_vertical > 1 else 0
        pitches = [min_pitch + i * pitch_step for i in range(num_vertical)]

    # Generate all combinations
    positions = []
    for pitch in pitches:
        for yaw in yaws:
            positions.append((yaw, pitch))

    return positions


def extract_tiles(
    equirect_path: Path,
    output_dir: Path,
    fov_deg: float = 90.0,
    overlap: float = 0.4,
    tile_size: int = 1024,
    pitch_range: tuple[float, float] = (-60.0, 60.0),
    image_prefix: str = None
) -> list[tuple[Path, TileInfo]]:
    """
    Extract all tiles from an equirectangular image.

    Args:
        equirect_path: Path to input equirectangular image
        output_dir: Directory to save tiles
        fov_deg: Field of view in degrees
        overlap: Minimum overlap ratio
        tile_size: Output tile dimensions (square)
        pitch_range: Vertical coverage range in degrees
        image_prefix: Prefix for tile filenames (default: source image stem)

    Returns:
        List of (output_path, tile_array, tile_info) tuples
    """
    # Load image
    img = Image.open(equirect_path)
    equirect = np.array(img)

    # Calculate tile positions
    positions = calculate_tile_grid(fov_deg, overlap, pitch_range)

    # Convert FOV to radians
    fov_rad = np.radians(fov_deg)

    # Calculate focal length for EXIF
    focal_length_mm = calculate_focal_length_mm(fov_rad)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use source image name as prefix if not provided
    if image_prefix is None:
        image_prefix = equirect_path.stem

    results = []

    # Determine number of columns for naming
    step_deg = fov_deg * (1 - overlap)
    num_cols = int(np.ceil(360 / step_deg))

    for idx, (yaw_deg, pitch_deg) in enumerate(positions):
        # Convert to radians
        yaw_rad = np.radians(yaw_deg)
        pitch_rad = np.radians(pitch_deg)

        # Extract tile
        tile = equirect_to_rectilinear(
            equirect,
            yaw_rad,
            pitch_rad,
            fov_rad,
            (tile_size, tile_size)
        )

        # Calculate row/col indices
        row = idx // num_cols
        col = idx % num_cols

        # Create filename with source image prefix for photogrammetry
        filename = f"{image_prefix}_r{row:02d}_c{col:02d}.png"
        output_path = output_dir / filename

        # Create tile info
        tile_info = TileInfo(
            yaw_deg=yaw_deg,
            pitch_deg=pitch_deg,
            fov_deg=fov_deg,
            row=row,
            col=col,
            focal_length_mm=focal_length_mm
        )

        results.append((output_path, tile, tile_info))

    return results


def get_grid_info(
    fov_deg: float = 90.0,
    overlap: float = 0.4,
    pitch_range: tuple[float, float] = (-60.0, 60.0)
) -> dict:
    """
    Get information about the tile grid configuration.

    Returns:
        Dictionary with grid statistics
    """
    positions = calculate_tile_grid(fov_deg, overlap, pitch_range)

    step_deg = fov_deg * (1 - overlap)
    num_cols = int(np.ceil(360 / step_deg))
    num_rows = len(positions) // num_cols

    actual_h_overlap = 1 - (360 / num_cols) / fov_deg
    actual_v_overlap = 1 - step_deg / fov_deg if num_rows > 1 else 1.0

    return {
        "total_tiles": len(positions),
        "rows": num_rows,
        "columns": num_cols,
        "fov_deg": fov_deg,
        "horizontal_step_deg": 360 / num_cols,
        "vertical_step_deg": step_deg,
        "actual_horizontal_overlap": actual_h_overlap,
        "actual_vertical_overlap": actual_v_overlap,
        "pitch_range": pitch_range
    }
