"""Async tile downloading for Street View panoramas."""

import asyncio
import io
from typing import Optional

import aiohttp
from PIL import Image
from tqdm import tqdm

from svdownloader.models import TileResult

_TILE_URL = (
    "https://cbk0.google.com/cbk"
    "?output=tile&panoid={pano_id}&zoom={zoom}&x={x}&y={y}"
)
_TILE_URL_FALLBACK = (
    "https://streetviewpixels-pa.googleapis.com/v1/tile"
    "?cb_client=maps_sv.tactile&panoid={pano_id}&x={x}&y={y}&zoom={zoom}&nbt=1&fover=2"
)

MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]


def _tile_url(pano_id: str, zoom: int, x: int, y: int, fallback: bool = False) -> str:
    template = _TILE_URL_FALLBACK if fallback else _TILE_URL
    return template.format(pano_id=pano_id, zoom=zoom, x=x, y=y)


async def _download_one_tile(
    session: aiohttp.ClientSession,
    pano_id: str,
    zoom: int,
    x: int,
    y: int,
    semaphore: asyncio.Semaphore,
    progress: Optional[tqdm],
) -> Optional[TileResult]:
    """Download a single tile with retries."""
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            use_fallback = attempt >= 2  # try fallback on last attempt
            url = _tile_url(pano_id, zoom, x, y, fallback=use_fallback)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        img = Image.open(io.BytesIO(data))
                        if progress:
                            progress.update(1)
                        return TileResult(x=x, y=y, image=img)
                    elif resp.status == 429:
                        # Rate limited - back off longer
                        await asyncio.sleep(5.0)
                        continue
                    elif resp.status >= 400:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAYS[attempt])
                            continue
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue

    # All retries exhausted
    if progress:
        progress.update(1)
    return None


async def download_tiles_async(
    pano_id: str,
    zoom: int,
    cols: int,
    rows: int,
    max_concurrent: int = 10,
) -> list[Optional[TileResult]]:
    """Download all tiles for a panorama asynchronously."""
    semaphore = asyncio.Semaphore(max_concurrent)
    total = cols * rows

    progress = tqdm(total=total, desc="Downloading tiles", unit="tile")

    async with aiohttp.ClientSession() as session:
        tasks = [
            _download_one_tile(session, pano_id, zoom, x, y, semaphore, progress)
            for y in range(rows)
            for x in range(cols)
        ]
        results = await asyncio.gather(*tasks)

    progress.close()
    return [r for r in results if r is not None]
