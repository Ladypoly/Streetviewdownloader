"""Tile stitching and panorama assembly."""

from pathlib import Path

from PIL import Image

from svdownloader.models import TileResult


def stitch_panorama(
    tiles: list[TileResult],
    pano_width: int,
    pano_height: int,
    tile_width: int = 512,
    tile_height: int = 512,
) -> Image.Image:
    """Assemble downloaded tiles into a single panorama image."""
    panorama = Image.new("RGB", (pano_width, pano_height))

    for tile in tiles:
        x_px = tile.x * tile_width
        y_px = tile.y * tile_height
        panorama.paste(tile.image, (x_px, y_px))

    return panorama


def crop_black_borders(image: Image.Image, threshold: int = 10) -> Image.Image:
    """Crop black/empty borders from the right and bottom edges."""
    width, height = image.size

    # Find rightmost non-black column
    right = width
    for x in range(width - 1, max(width - 600, 0), -1):
        col_pixels = [image.getpixel((x, y)) for y in range(0, height, height // 20)]
        if any(sum(p) > threshold for p in col_pixels):
            right = x + 1
            break

    # Find bottommost non-black row
    bottom = height
    for y in range(height - 1, max(height - 600, 0), -1):
        row_pixels = [image.getpixel((x, y)) for x in range(0, width, width // 20)]
        if any(sum(p) > threshold for p in row_pixels):
            bottom = y + 1
            break

    if right < width or bottom < height:
        return image.crop((0, 0, right, bottom))
    return image


def save_panorama(
    image: Image.Image,
    output_path: str | Path,
    fmt: str = "JPEG",
    quality: int = 95,
) -> Path:
    """Save the panorama image to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    save_kwargs = {}
    if fmt.upper() == "JPEG":
        save_kwargs["quality"] = quality
        save_kwargs["subsampling"] = 0  # best quality chroma
    elif fmt.upper() == "PNG":
        save_kwargs["compress_level"] = 6

    image.save(str(output_path), format=fmt, **save_kwargs)
    return output_path
