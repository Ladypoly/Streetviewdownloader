"""CLI interface and orchestration for Street View panorama downloading."""

import argparse
import asyncio
import sys
from pathlib import Path

from svdownloader import __version__
from svdownloader.metadata import get_metadata, search_panoramas
from svdownloader.models import PanoramaInfo
from svdownloader.stitcher import crop_black_borders, save_panorama, stitch_panorama
from svdownloader.tiles import download_tiles_async
from svdownloader.utils import parse_input, sanitize_filename


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="svdownload",
        description="Download Google Street View panoramas at native quality.",
    )
    parser.add_argument(
        "input",
        nargs="+",
        help="Panorama ID, Google Maps URL, or lat,lng coordinates",
    )
    parser.add_argument(
        "-o", "--output",
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "-z", "--zoom",
        type=int,
        default=None,
        help="Zoom level 0-5 (default: max available = native quality)",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["jpeg", "png"],
        default="jpeg",
        help="Output format (default: jpeg)",
    )
    parser.add_argument(
        "-q", "--quality",
        type=int,
        default=95,
        help="JPEG quality 1-100 (default: 95)",
    )
    parser.add_argument(
        "--no-crop",
        action="store_true",
        help="Don't crop black borders from the panorama",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Max concurrent tile downloads (default: 10)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _resolve_pano_id(input_str: str, verbose: bool) -> str:
    """Resolve any input type to a panorama ID."""
    parsed = parse_input(input_str)

    if parsed.type == "pano_id":
        return parsed.value

    if parsed.type == "url":
        return parsed.value

    # Coordinates - search for nearby panorama
    if parsed.lat is None or parsed.lon is None:
        print(f"Error: Could not parse coordinates from: {input_str}", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"Searching for panorama near {parsed.lat}, {parsed.lon}...")

    results = search_panoramas(parsed.lat, parsed.lon)
    if not results:
        print(f"No Street View coverage found near {parsed.lat}, {parsed.lon}", file=sys.stderr)
        sys.exit(1)

    pano = results[0]
    if verbose:
        print(f"Found panorama: {pano.pano_id} at ({pano.lat}, {pano.lon})")
    return pano.pano_id


async def _download_one(
    input_str: str,
    output_dir: Path,
    zoom: int | None,
    fmt: str,
    quality: int,
    crop: bool,
    concurrency: int,
    verbose: bool,
) -> bool:
    """Download a single panorama. Returns True on success."""
    try:
        pano_id = _resolve_pano_id(input_str, verbose)
    except Exception as e:
        print(f"Error resolving input '{input_str}': {e}", file=sys.stderr)
        return False

    # Fetch metadata
    try:
        if verbose:
            print(f"Fetching metadata for {pano_id}...")
        info = get_metadata(pano_id)
    except Exception as e:
        print(f"Error fetching metadata for {pano_id}: {e}", file=sys.stderr)
        return False

    # Determine zoom level
    z = zoom if zoom is not None else info.max_zoom
    z = min(z, info.max_zoom)

    cols, rows = info.grid_size(z)
    width, height = info.pixel_size(z)

    print(f"Panorama: {pano_id}")
    print(f"  Resolution: {width}x{height} ({cols}x{rows} tiles at zoom {z})")
    if info.date:
        print(f"  Date: {info.date}")
    if info.lat and info.lon:
        print(f"  Location: {info.lat}, {info.lon}")

    # Download tiles
    tiles = await download_tiles_async(pano_id, z, cols, rows, concurrency)

    if not tiles:
        print(f"Error: No tiles downloaded for {pano_id}", file=sys.stderr)
        return False

    failed = cols * rows - len(tiles)
    if failed > 0:
        print(f"  Warning: {failed} tile(s) failed to download")

    # Stitch
    tw, th = info.tile_size
    canvas_w = cols * tw
    canvas_h = rows * th
    panorama = stitch_panorama(tiles, canvas_w, canvas_h, tw, th)

    # Crop
    if crop:
        panorama = crop_black_borders(panorama)

    # Save
    ext = "jpg" if fmt == "jpeg" else "png"
    filename = f"{sanitize_filename(pano_id)}.{ext}"
    output_path = output_dir / filename
    save_panorama(panorama, output_path, fmt=fmt.upper(), quality=quality)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    final_w, final_h = panorama.size
    print(f"  Saved: {output_path} ({final_w}x{final_h}, {size_mb:.1f} MB)")
    return True


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    total = len(args.input)

    for i, input_str in enumerate(args.input, 1):
        if total > 1:
            print(f"\n[{i}/{total}] Processing: {input_str}")

        ok = asyncio.run(
            _download_one(
                input_str=input_str,
                output_dir=output_dir,
                zoom=args.zoom,
                fmt=args.format,
                quality=args.quality,
                crop=not args.no_crop,
                concurrency=args.concurrency,
                verbose=args.verbose,
            )
        )
        if ok:
            success += 1

    if total > 1:
        print(f"\nDone: {success}/{total} panoramas downloaded successfully.")

    if success == 0:
        sys.exit(1)
