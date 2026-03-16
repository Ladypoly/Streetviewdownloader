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
from svdownloader.area import find_area_panoramas, find_radius_panoramas
from svdownloader.route import find_route_panoramas
from svdownloader.utils import parse_input, resolve_to_coords, sanitize_filename


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
        "--route",
        action="store_true",
        help="Route mode: treat two inputs as start and end points, download all panoramas along the route",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=20,
        help="Route sampling interval in meters (default: 20)",
    )
    parser.add_argument(
        "--area",
        action="store_true",
        help="Area mode: treat two inputs as NW and SE corners, download all panoramas in the bounding box",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=None,
        help="Radius mode: download all panoramas within N meters of a single point (e.g. --radius 200)",
    )
    parser.add_argument(
        "--spacing",
        type=int,
        default=50,
        help="Area/radius grid spacing in meters (default: 50)",
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


async def _download_pano_by_id(
    pano_id: str,
    output_dir: Path,
    zoom: int | None,
    fmt: str,
    quality: int,
    crop: bool,
    concurrency: int,
) -> bool:
    """Download a panorama by its ID directly. Returns True on success."""
    info = get_metadata(pano_id)
    z = zoom if zoom is not None else info.max_zoom
    z = min(z, info.max_zoom)
    cols, rows = info.grid_size(z)
    tw, th = info.tile_size

    tiles = await download_tiles_async(pano_id, z, cols, rows, concurrency)
    if not tiles:
        print(f"  Failed: no tiles for {pano_id}", file=sys.stderr)
        return False

    panorama = stitch_panorama(tiles, cols * tw, rows * th, tw, th)
    if crop:
        panorama = crop_black_borders(panorama)

    ext = "jpg" if fmt == "jpeg" else "png"
    path = output_dir / f"{sanitize_filename(pano_id)}.{ext}"
    save_panorama(panorama, path, fmt=fmt.upper(), quality=quality)
    size_mb = path.stat().st_size / (1024 * 1024)
    w, h = panorama.size
    print(f"  Saved: {path.name} ({w}x{h}, {size_mb:.1f} MB)")
    return True


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.route:
        _run_route(args, output_dir)
    elif args.area:
        _run_area(args, output_dir)
    elif args.radius is not None:
        _run_radius(args, output_dir)
    else:
        _run_batch(args, output_dir)


def _run_route(args, output_dir: Path) -> None:
    """Handle --route mode."""
    if len(args.input) != 2:
        print("Error: --route requires exactly 2 inputs (start and end coordinates)", file=sys.stderr)
        sys.exit(1)

    try:
        start = resolve_to_coords(args.input[0])
        end = resolve_to_coords(args.input[1])
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Finding panoramas from ({start[0]:.4f}, {start[1]:.4f}) to ({end[0]:.4f}, {end[1]:.4f})...")
    panoramas = find_route_panoramas(start, end, interval_m=args.interval)

    if not panoramas:
        print("No panoramas found along the route.", file=sys.stderr)
        sys.exit(1)

    subfolder = output_dir / f"route_{start[0]:.4f}_{start[1]:.4f}_to_{end[0]:.4f}_{end[1]:.4f}"
    subfolder.mkdir(parents=True, exist_ok=True)
    print(f"\nDownloading {len(panoramas)} panoramas to {subfolder}/...")
    success = 0
    for i, pano in enumerate(panoramas, 1):
        print(f"\n[{i}/{len(panoramas)}] {pano.pano_id} ({pano.lat:.5f}, {pano.lon:.5f})")
        ok = asyncio.run(
            _download_pano_by_id(
                pano_id=pano.pano_id,
                output_dir=subfolder,
                zoom=args.zoom,
                fmt=args.format,
                quality=args.quality,
                crop=not args.no_crop,
                concurrency=args.concurrency,
            )
        )
        if ok:
            success += 1

    print(f"\nDone: {success}/{len(panoramas)} panoramas downloaded.")
    if success == 0:
        sys.exit(1)


def _run_area(args, output_dir: Path) -> None:
    """Handle --area mode."""
    if len(args.input) != 2:
        print("Error: --area requires exactly 2 inputs (NW corner and SE corner as lat,lon)", file=sys.stderr)
        sys.exit(1)

    try:
        nw = resolve_to_coords(args.input[0])
        se = resolve_to_coords(args.input[1])
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    north = max(nw[0], se[0])
    south = min(nw[0], se[0])
    east = max(nw[1], se[1])
    west = min(nw[1], se[1])

    print(f"Searching area: ({north:.4f}, {west:.4f}) to ({south:.4f}, {east:.4f})...")
    panoramas = find_area_panoramas(north, south, east, west, spacing_m=args.spacing)

    if not panoramas:
        print("No panoramas found in the area.", file=sys.stderr)
        sys.exit(1)

    subfolder = output_dir / f"area_{north:.4f}_{west:.4f}_to_{south:.4f}_{east:.4f}"
    subfolder.mkdir(parents=True, exist_ok=True)
    print(f"\nDownloading {len(panoramas)} panoramas to {subfolder}/...")
    success = 0
    for i, pano in enumerate(panoramas, 1):
        print(f"\n[{i}/{len(panoramas)}] {pano.pano_id} ({pano.lat:.5f}, {pano.lon:.5f})")
        ok = asyncio.run(
            _download_pano_by_id(
                pano_id=pano.pano_id,
                output_dir=subfolder,
                zoom=args.zoom,
                fmt=args.format,
                quality=args.quality,
                crop=not args.no_crop,
                concurrency=args.concurrency,
            )
        )
        if ok:
            success += 1

    print(f"\nDone: {success}/{len(panoramas)} panoramas downloaded.")
    if success == 0:
        sys.exit(1)


def _run_radius(args, output_dir: Path) -> None:
    """Handle --radius mode."""
    if len(args.input) != 1:
        print("Error: --radius requires exactly 1 input (center point as lat,lon or Google Maps URL)", file=sys.stderr)
        sys.exit(1)

    try:
        center = resolve_to_coords(args.input[0])
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    panoramas = find_radius_panoramas(center[0], center[1], radius_m=args.radius, spacing_m=args.spacing)

    if not panoramas:
        print("No panoramas found in the area.", file=sys.stderr)
        sys.exit(1)

    subfolder = output_dir / f"radius_{center[0]:.4f}_{center[1]:.4f}_{args.radius}m"
    subfolder.mkdir(parents=True, exist_ok=True)
    print(f"\nDownloading {len(panoramas)} panoramas to {subfolder}/...")
    success = 0
    for i, pano in enumerate(panoramas, 1):
        print(f"\n[{i}/{len(panoramas)}] {pano.pano_id} ({pano.lat:.5f}, {pano.lon:.5f})")
        ok = asyncio.run(
            _download_pano_by_id(
                pano_id=pano.pano_id,
                output_dir=subfolder,
                zoom=args.zoom,
                fmt=args.format,
                quality=args.quality,
                crop=not args.no_crop,
                concurrency=args.concurrency,
            )
        )
        if ok:
            success += 1

    print(f"\nDone: {success}/{len(panoramas)} panoramas downloaded.")
    if success == 0:
        sys.exit(1)


def _run_batch(args, output_dir: Path) -> None:
    """Handle normal batch mode."""
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
