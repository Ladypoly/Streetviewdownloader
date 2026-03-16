"""Simple GUI for batch downloading Street View panoramas."""

import asyncio
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

from svdownloader.metadata import get_metadata, search_panoramas
from svdownloader.stitcher import crop_black_borders, save_panorama, stitch_panorama
from svdownloader.tiles import download_tiles_async
from svdownloader.utils import parse_input, sanitize_filename


class App:
    def __init__(self, root: tk.Tk):
        root.title("Street View Downloader")
        root.geometry("620x520")
        root.resizable(False, False)

        # --- Input area ---
        tk.Label(root, text="Paste URLs, pano IDs, or coordinates (one per line):").pack(
            anchor="w", padx=10, pady=(10, 2)
        )
        self.text = tk.Text(root, height=12, width=72)
        self.text.pack(padx=10)

        # --- Options row ---
        opts = tk.Frame(root)
        opts.pack(fill="x", padx=10, pady=8)

        tk.Label(opts, text="Output folder:").pack(side="left")
        self.folder_var = tk.StringVar(value=str(Path.home() / "Pictures" / "StreetView"))
        tk.Entry(opts, textvariable=self.folder_var, width=35).pack(side="left", padx=4)
        tk.Button(opts, text="Browse", command=self._browse).pack(side="left")

        tk.Label(opts, text="  Zoom:").pack(side="left")
        self.zoom_var = tk.IntVar(value=5)
        zoom_spin = tk.Spinbox(opts, from_=0, to=5, textvariable=self.zoom_var, width=3)
        zoom_spin.pack(side="left", padx=2)

        tk.Label(opts, text="  Format:").pack(side="left")
        self.fmt_var = tk.StringVar(value="jpeg")
        ttk.Combobox(opts, textvariable=self.fmt_var, values=["jpeg", "png"], width=5, state="readonly").pack(side="left", padx=2)

        # --- Buttons ---
        btn_row = tk.Frame(root)
        btn_row.pack(pady=6)
        self.dl_btn = tk.Button(btn_row, text="Download All", width=16, command=self._start)
        self.dl_btn.pack(side="left", padx=4)
        tk.Button(btn_row, text="Clear", width=8, command=self._clear).pack(side="left", padx=4)

        # --- Progress ---
        self.progress = ttk.Progressbar(root, length=580, mode="determinate")
        self.progress.pack(padx=10, pady=(4, 2))

        # --- Log ---
        self.log = tk.Text(root, height=8, width=72, state="disabled", bg="#f4f4f4")
        self.log.pack(padx=10, pady=(2, 10))

        self.root = root

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.folder_var.get())
        if d:
            self.folder_var.set(d)

    def _clear(self):
        self.text.delete("1.0", "end")
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.progress["value"] = 0

    def _log(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _start(self):
        lines = [l.strip() for l in self.text.get("1.0", "end").splitlines() if l.strip()]
        if not lines:
            self._log("Nothing to download — paste some URLs first.")
            return
        self.dl_btn.config(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = len(lines)
        threading.Thread(target=self._run, args=(lines,), daemon=True).start()

    def _run(self, lines: list[str]):
        out = Path(self.folder_var.get())
        out.mkdir(parents=True, exist_ok=True)
        zoom = self.zoom_var.get()
        fmt = self.fmt_var.get()

        ok = 0
        for i, line in enumerate(lines, 1):
            self.root.after(0, self._log, f"[{i}/{len(lines)}] {line}")
            try:
                result = asyncio.run(
                    _download(line, out, zoom, fmt)
                )
                if result:
                    self.root.after(0, self._log, f"  -> {result}")
                    ok += 1
                else:
                    self.root.after(0, self._log, "  -> FAILED")
            except Exception as e:
                self.root.after(0, self._log, f"  -> ERROR: {e}")
            self.root.after(0, self._advance)

        self.root.after(0, self._log, f"\nDone: {ok}/{len(lines)} downloaded to {out}")
        self.root.after(0, lambda: self.dl_btn.config(state="normal"))

    def _advance(self):
        self.progress["value"] += 1


async def _download(input_str: str, out: Path, zoom: int, fmt: str) -> str | None:
    parsed = parse_input(input_str)

    if parsed.type == "coords":
        results = search_panoramas(parsed.lat, parsed.lon)
        if not results:
            return None
        pano_id = results[0].pano_id
    elif parsed.type == "url":
        pano_id = parsed.value
    else:
        pano_id = parsed.value

    info = get_metadata(pano_id)
    z = min(zoom, info.max_zoom)
    cols, rows = info.grid_size(z)
    tw, th = info.tile_size

    tiles = await download_tiles_async(pano_id, z, cols, rows, max_concurrent=10)
    if not tiles:
        return None

    panorama = stitch_panorama(tiles, cols * tw, rows * th, tw, th)
    panorama = crop_black_borders(panorama)

    ext = "jpg" if fmt == "jpeg" else "png"
    path = out / f"{sanitize_filename(pano_id)}.{ext}"
    save_panorama(panorama, path, fmt=fmt.upper(), quality=95)
    w, h = panorama.size
    mb = path.stat().st_size / (1024 * 1024)
    return f"{path.name} ({w}x{h}, {mb:.1f} MB)"


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
