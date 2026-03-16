# Street View Downloader

Download Google Street View panoramas at native quality (up to 16,384 x 8,192 pixels).

## Features

- Downloads panoramas at full native resolution (zoom level 5)
- Accepts Google Maps URLs, panorama IDs, or lat/lng coordinates
- Async tile downloading with progress bar
- Automatic black border cropping
- Batch mode for multiple panoramas
- Simple GUI for paste-and-download workflow
- No API key required

## Installation

```bash
pip install -e .
```

## Usage

### GUI (recommended for batch downloads)

Double-click `StreetViewDownloader.bat` or run:

```bash
python gui.py
```

Paste URLs, pano IDs, or coordinates (one per line) and click **Download All**.

### Command Line

```bash
# By coordinates
svdownload "48.8584,2.2945"

# By panorama ID
svdownload "TfOtSjhjU3Fd9Z5ZFz2iBQ"

# By Google Maps URL
svdownload "https://www.google.com/maps/@48.858...!1sTfOtSjhjU3Fd9Z5ZFz2iBQ!2e0..."

# Options
svdownload -z 5 -o ./output -f jpeg -q 95 "48.8584,2.2945"

# Batch (multiple inputs)
svdownload "48.8584,2.2945" "40.7484,-73.9857" "51.5007,-0.1246"
```

### CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `-o, --output` | Output directory | Current directory |
| `-z, --zoom` | Zoom level 0-5 | 5 (native) |
| `-f, --format` | jpeg or png | jpeg |
| `-q, --quality` | JPEG quality 1-100 | 95 |
| `--no-crop` | Don't crop black borders | Off |
| `--concurrency` | Max parallel downloads | 10 |
| `-v, --verbose` | Verbose output | Off |

## How It Works

Google Street View panoramas are stored as grids of 512x512 pixel tiles. At zoom level 5 (native quality), a panorama consists of 32x16 = 512 tiles, producing a ~16,384 x 8,192 pixel equirectangular image.

This tool:
1. Resolves your input to a panorama ID
2. Downloads all tiles in parallel using async HTTP
3. Stitches them into a single panorama image
4. Crops any black borders and saves as JPEG or PNG

## Requirements

- Python 3.10+
- Dependencies: `aiohttp`, `Pillow`, `tqdm`, `requests`
