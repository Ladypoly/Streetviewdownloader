"""
EXIF metadata writer module.
Embeds camera parameters in PNG images for photogrammetry applications.
"""

import piexif
from PIL import Image
from pathlib import Path
import numpy as np


def float_to_rational(value: float) -> tuple[int, int]:
    """
    Convert a float to a rational number tuple for EXIF.

    Args:
        value: Float value to convert

    Returns:
        Tuple of (numerator, denominator)
    """
    if value == 0:
        return (0, 1)

    # Use fixed precision
    precision = 10000
    numerator = int(round(value * precision))
    denominator = precision

    # Simplify if possible
    from math import gcd
    g = gcd(abs(numerator), denominator)
    return (numerator // g, denominator // g)


def create_exif_data(
    focal_length_mm: float,
    image_width: int,
    image_height: int,
    fov_deg: float = None
) -> bytes:
    """
    Create EXIF data bytes with camera parameters.

    Args:
        focal_length_mm: Focal length in millimeters (35mm equivalent)
        image_width: Image width in pixels
        image_height: Image height in pixels
        fov_deg: Field of view in degrees (optional, for reference)

    Returns:
        EXIF data as bytes
    """
    # Create EXIF structure
    exif_dict = {
        "0th": {},
        "Exif": {},
        "GPS": {},
        "1st": {},
        "thumbnail": None
    }

    # Image dimensions
    exif_dict["0th"][piexif.ImageIFD.ImageWidth] = image_width
    exif_dict["0th"][piexif.ImageIFD.ImageLength] = image_height

    # Software tag
    exif_dict["0th"][piexif.ImageIFD.Software] = "PanoSplitter"

    # Focal length (as rational)
    focal_rational = float_to_rational(focal_length_mm)
    exif_dict["Exif"][piexif.ExifIFD.FocalLength] = focal_rational

    # Focal length in 35mm equivalent
    exif_dict["Exif"][piexif.ExifIFD.FocalLengthIn35mmFilm] = int(round(focal_length_mm))

    # Pixel dimensions
    exif_dict["Exif"][piexif.ExifIFD.PixelXDimension] = image_width
    exif_dict["Exif"][piexif.ExifIFD.PixelYDimension] = image_height

    # Create EXIF bytes
    exif_bytes = piexif.dump(exif_dict)

    return exif_bytes


def save_tile_with_exif(
    tile_array: np.ndarray,
    output_path: Path,
    focal_length_mm: float,
    fov_deg: float = None
) -> None:
    """
    Save a tile image with embedded EXIF metadata.

    Args:
        tile_array: Tile image as numpy array
        output_path: Path to save the image
        focal_length_mm: Focal length in mm for EXIF
        fov_deg: Field of view (optional, for reference)
    """
    # Convert to PIL Image
    img = Image.fromarray(tile_array)

    # Get dimensions
    width, height = img.size

    # Create EXIF data
    exif_bytes = create_exif_data(
        focal_length_mm=focal_length_mm,
        image_width=width,
        image_height=height,
        fov_deg=fov_deg
    )

    # Save with EXIF
    # Note: PNG doesn't natively support EXIF, but we can embed it
    # Some applications read it, others use the pnginfo
    output_path = Path(output_path)

    if output_path.suffix.lower() in ['.jpg', '.jpeg']:
        img.save(output_path, exif=exif_bytes, quality=95)
    else:
        # For PNG, save EXIF and also add text metadata
        from PIL import PngImagePlugin

        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("FocalLength", f"{focal_length_mm:.2f}")
        pnginfo.add_text("FocalLengthIn35mmFilm", f"{int(round(focal_length_mm))}")
        pnginfo.add_text("ImageWidth", str(width))
        pnginfo.add_text("ImageHeight", str(height))
        pnginfo.add_text("Software", "PanoSplitter")

        if fov_deg is not None:
            pnginfo.add_text("FieldOfView", f"{fov_deg:.2f}")

        img.save(output_path, pnginfo=pnginfo)


def read_exif_focal_length(image_path: Path) -> float | None:
    """
    Read focal length from image EXIF data.

    Args:
        image_path: Path to image file

    Returns:
        Focal length in mm, or None if not found
    """
    try:
        img = Image.open(image_path)

        # Try EXIF first
        if hasattr(img, '_getexif') and img._getexif():
            exif = img._getexif()
            if exif and piexif.ExifIFD.FocalLength in exif:
                focal = exif[piexif.ExifIFD.FocalLength]
                if isinstance(focal, tuple):
                    return focal[0] / focal[1]
                return float(focal)

        # Try PNG text chunks
        if hasattr(img, 'text'):
            if 'FocalLength' in img.text:
                return float(img.text['FocalLength'])

        return None

    except Exception:
        return None
