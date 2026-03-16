"""Simple GUI for batch downloading Street View panoramas."""

import asyncio
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

from svdownloader.metadata import get_metadata, search_panoramas
from svdownloader.area import find_area_panoramas, find_radius_panoramas
from svdownloader.route import find_route_panoramas
from svdownloader.stitcher import crop_black_borders, save_panorama, stitch_panorama
from svdownloader.tiles import download_tiles_async
from svdownloader.utils import parse_input, resolve_to_coords, sanitize_filename
from svdownloader.tile_extractor import extract_tiles, get_grid_info
from svdownloader.exif_writer import save_tile_with_exif

_PANO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


class App:
    def __init__(self, root: tk.Tk):
        root.title("Street View Downloader")
        root.geometry("640x720")
        root.resizable(False, False)
        self.root = root

        # --- Tabs ---
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        batch_tab = tk.Frame(notebook)
        route_tab = tk.Frame(notebook)
        area_tab = tk.Frame(notebook)
        splitter_tab = tk.Frame(notebook)
        notebook.add(batch_tab, text="  Batch Download  ")
        notebook.add(route_tab, text="  Route Download  ")
        notebook.add(area_tab, text="  Area Download  ")
        notebook.add(splitter_tab, text="  Pano Splitter  ")

        self._build_batch_tab(batch_tab)
        self._build_route_tab(route_tab)
        self._build_area_tab(area_tab)
        self._build_splitter_tab(splitter_tab)

        # --- Shared options ---
        opts = tk.Frame(root)
        opts.pack(fill="x", padx=10, pady=6)

        tk.Label(opts, text="Output folder:").pack(side="left")
        self.folder_var = tk.StringVar(value=str(Path.home() / "Pictures" / "StreetView"))
        tk.Entry(opts, textvariable=self.folder_var, width=30).pack(side="left", padx=4)
        tk.Button(opts, text="Browse", command=self._browse).pack(side="left")

        tk.Label(opts, text="  Zoom:").pack(side="left")
        self.zoom_var = tk.IntVar(value=5)
        tk.Spinbox(opts, from_=0, to=5, textvariable=self.zoom_var, width=3).pack(side="left", padx=2)

        tk.Label(opts, text="  Format:").pack(side="left")
        self.fmt_var = tk.StringVar(value="jpeg")
        ttk.Combobox(opts, textvariable=self.fmt_var, values=["jpeg", "png"], width=5, state="readonly").pack(side="left", padx=2)

        # --- Progress ---
        self.progress = ttk.Progressbar(root, length=600, mode="determinate")
        self.progress.pack(padx=10, pady=(4, 2))

        # --- Log ---
        self.log = tk.Text(root, height=10, width=76, state="disabled", bg="#f4f4f4")
        self.log.pack(padx=10, pady=(2, 10))

    # ── Batch tab ──

    def _build_batch_tab(self, parent):
        tk.Label(parent, text="Paste URLs, pano IDs, or coordinates (one per line):").pack(
            anchor="w", padx=8, pady=(8, 2)
        )
        self.text = tk.Text(parent, height=10, width=72)
        self.text.pack(padx=8)

        btn_row = tk.Frame(parent)
        btn_row.pack(pady=6)
        self.batch_dl_btn = tk.Button(btn_row, text="Download All", width=16, command=self._start_batch)
        self.batch_dl_btn.pack(side="left", padx=4)
        tk.Button(btn_row, text="Clear", width=8, command=self._clear_batch).pack(side="left", padx=4)

    # ── Route tab ──

    def _build_route_tab(self, parent):
        frm = tk.Frame(parent)
        frm.pack(fill="x", padx=8, pady=(10, 4))

        tk.Label(frm, text="Start (lat,lon or URL):").grid(row=0, column=0, sticky="w", pady=4)
        self.route_start = tk.Entry(frm, width=55)
        self.route_start.grid(row=0, column=1, padx=4, pady=4)

        tk.Label(frm, text="End (lat,lon or URL):").grid(row=1, column=0, sticky="w", pady=4)
        self.route_end = tk.Entry(frm, width=55)
        self.route_end.grid(row=1, column=1, padx=4, pady=4)

        tk.Label(frm, text="Interval (meters):").grid(row=2, column=0, sticky="w", pady=4)
        self.interval_var = tk.IntVar(value=20)
        tk.Spinbox(frm, from_=5, to=200, textvariable=self.interval_var, width=6).grid(row=2, column=1, sticky="w", padx=4, pady=4)

        btn_row = tk.Frame(parent)
        btn_row.pack(pady=6)
        self.route_find_btn = tk.Button(btn_row, text="Find Panoramas", width=16, command=self._start_route_find)
        self.route_find_btn.pack(side="left", padx=4)
        self.route_dl_btn = tk.Button(btn_row, text="Download All", width=16, command=self._start_route_dl, state="disabled")
        self.route_dl_btn.pack(side="left", padx=4)

        # Panorama list display
        self.route_info = tk.Label(parent, text="Enter start and end points, then click Find Panoramas.", anchor="w")
        self.route_info.pack(fill="x", padx=8, pady=(2, 4))

        self._route_panos = []

    # ── Area tab ──

    def _build_area_tab(self, parent):
        # Mode selector
        mode_frm = tk.Frame(parent)
        mode_frm.pack(fill="x", padx=8, pady=(8, 2))
        self.area_mode = tk.StringVar(value="bbox")
        tk.Radiobutton(mode_frm, text="Bounding box (two corners)", variable=self.area_mode, value="bbox", command=self._toggle_area_mode).pack(side="left")
        tk.Radiobutton(mode_frm, text="Radius around point", variable=self.area_mode, value="radius", command=self._toggle_area_mode).pack(side="left", padx=12)

        frm = tk.Frame(parent)
        frm.pack(fill="x", padx=8, pady=(4, 4))

        # Bbox fields
        self.area_nw_lbl = tk.Label(frm, text="NW corner (lat,lon or URL):")
        self.area_nw_lbl.grid(row=0, column=0, sticky="w", pady=4)
        self.area_nw = tk.Entry(frm, width=55)
        self.area_nw.grid(row=0, column=1, padx=4, pady=4)

        self.area_se_lbl = tk.Label(frm, text="SE corner (lat,lon or URL):")
        self.area_se_lbl.grid(row=1, column=0, sticky="w", pady=4)
        self.area_se = tk.Entry(frm, width=55)
        self.area_se.grid(row=1, column=1, padx=4, pady=4)

        # Radius fields (hidden by default)
        self.area_center_lbl = tk.Label(frm, text="Center (lat,lon or URL):")
        self.area_center = tk.Entry(frm, width=55)
        self.area_radius_lbl = tk.Label(frm, text="Radius (meters):")
        self.area_radius_var = tk.IntVar(value=200)
        self.area_radius_spin = tk.Spinbox(frm, from_=50, to=5000, textvariable=self.area_radius_var, width=8)

        tk.Label(frm, text="Grid spacing (meters):").grid(row=4, column=0, sticky="w", pady=4)
        self.spacing_var = tk.IntVar(value=50)
        tk.Spinbox(frm, from_=20, to=200, textvariable=self.spacing_var, width=6).grid(row=4, column=1, sticky="w", padx=4, pady=4)

        self._area_frm = frm

        btn_row = tk.Frame(parent)
        btn_row.pack(pady=6)
        self.area_find_btn = tk.Button(btn_row, text="Find Panoramas", width=16, command=self._start_area_find)
        self.area_find_btn.pack(side="left", padx=4)
        self.area_dl_btn = tk.Button(btn_row, text="Download All", width=16, command=self._start_area_dl, state="disabled")
        self.area_dl_btn.pack(side="left", padx=4)

        self.area_info = tk.Label(parent, text="Choose a mode, enter coordinates, then click Find Panoramas.", anchor="w")
        self.area_info.pack(fill="x", padx=8, pady=(2, 4))

        self._area_panos = []
        self._toggle_area_mode()  # set initial visibility

    def _toggle_area_mode(self):
        if self.area_mode.get() == "bbox":
            self.area_nw_lbl.grid(row=0, column=0, sticky="w", pady=4)
            self.area_nw.grid(row=0, column=1, padx=4, pady=4)
            self.area_se_lbl.grid(row=1, column=0, sticky="w", pady=4)
            self.area_se.grid(row=1, column=1, padx=4, pady=4)
            self.area_center_lbl.grid_forget()
            self.area_center.grid_forget()
            self.area_radius_lbl.grid_forget()
            self.area_radius_spin.grid_forget()
        else:
            self.area_nw_lbl.grid_forget()
            self.area_nw.grid_forget()
            self.area_se_lbl.grid_forget()
            self.area_se.grid_forget()
            self.area_center_lbl.grid(row=0, column=0, sticky="w", pady=4)
            self.area_center.grid(row=0, column=1, padx=4, pady=4)
            self.area_radius_lbl.grid(row=1, column=0, sticky="w", pady=4)
            self.area_radius_spin.grid(row=1, column=1, sticky="w", padx=4, pady=4)

    # ── Shared helpers ──

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.folder_var.get())
        if d:
            self.folder_var.set(d)

    def _clear_batch(self):
        self.text.delete("1.0", "end")
        self._clear_log()

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.progress["value"] = 0

    def _log(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _advance(self):
        self.progress["value"] += 1

    # ── Batch download ──

    def _start_batch(self):
        lines = [l.strip() for l in self.text.get("1.0", "end").splitlines() if l.strip()]
        if not lines:
            self._log("Nothing to download — paste some URLs first.")
            return
        self.batch_dl_btn.config(state="disabled")
        self._clear_log()
        self.progress["maximum"] = len(lines)
        threading.Thread(target=self._run_batch, args=(lines,), daemon=True).start()

    def _run_batch(self, lines: list[str]):
        out = Path(self.folder_var.get())
        out.mkdir(parents=True, exist_ok=True)
        zoom = self.zoom_var.get()
        fmt = self.fmt_var.get()

        ok = 0
        for i, line in enumerate(lines, 1):
            self.root.after(0, self._log, f"[{i}/{len(lines)}] {line}")
            try:
                result = asyncio.run(_download(line, out, zoom, fmt))
                if result:
                    self.root.after(0, self._log, f"  -> {result}")
                    ok += 1
                else:
                    self.root.after(0, self._log, "  -> FAILED")
            except Exception as e:
                self.root.after(0, self._log, f"  -> ERROR: {e}")
            self.root.after(0, self._advance)

        self.root.after(0, self._log, f"\nDone: {ok}/{len(lines)} downloaded to {out}")
        self.root.after(0, lambda: self.batch_dl_btn.config(state="normal"))

    # ── Route find ──

    def _start_route_find(self):
        start_str = self.route_start.get().strip()
        end_str = self.route_end.get().strip()
        if not start_str or not end_str:
            self._log("Please enter both start and end points.")
            return
        self.route_find_btn.config(state="disabled")
        self.route_dl_btn.config(state="disabled")
        self._clear_log()
        self.route_info.config(text="Searching for route and panoramas...")
        threading.Thread(target=self._run_route_find, args=(start_str, end_str), daemon=True).start()

    def _run_route_find(self, start_str: str, end_str: str):
        try:
            start = resolve_to_coords(start_str)
            end = resolve_to_coords(end_str)
        except ValueError as e:
            self.root.after(0, self._log, f"Error: {e}")
            self.root.after(0, lambda: self.route_find_btn.config(state="normal"))
            return

        self.root.after(0, self._log, f"Routing from ({start[0]:.4f}, {start[1]:.4f}) to ({end[0]:.4f}, {end[1]:.4f})...")

        try:
            panos = find_route_panoramas(start, end, interval_m=self.interval_var.get())
        except Exception as e:
            self.root.after(0, self._log, f"Route error: {e}")
            self.root.after(0, lambda: self.route_find_btn.config(state="normal"))
            return

        self._route_panos = panos
        count = len(panos)
        self.root.after(0, self._log, f"Found {count} unique panoramas along route.")
        self.root.after(0, lambda: self.route_info.config(text=f"Found {count} panoramas. Click 'Download All' to save them."))
        self.root.after(0, lambda: self.route_find_btn.config(state="normal"))
        if count > 0:
            self.root.after(0, lambda: self.route_dl_btn.config(state="normal"))

    # ── Route download ──

    def _start_route_dl(self):
        if not self._route_panos:
            return
        self.route_dl_btn.config(state="disabled")
        self.route_find_btn.config(state="disabled")
        self._clear_log()
        self.progress["maximum"] = len(self._route_panos)
        threading.Thread(target=self._run_route_dl, daemon=True).start()

    def _run_route_dl(self):
        base = Path(self.folder_var.get())
        start_str = self.route_start.get().strip().replace(",", "_").replace(" ", "")[:20]
        end_str = self.route_end.get().strip().replace(",", "_").replace(" ", "")[:20]
        out = base / f"route_{start_str}_to_{end_str}"
        out.mkdir(parents=True, exist_ok=True)
        zoom = self.zoom_var.get()
        fmt = self.fmt_var.get()
        panos = self._route_panos

        ok = 0
        for i, pano in enumerate(panos, 1):
            self.root.after(0, self._log, f"[{i}/{len(panos)}] {pano.pano_id}")
            try:
                result = asyncio.run(_download_by_id(pano.pano_id, out, zoom, fmt))
                if result:
                    self.root.after(0, self._log, f"  -> {result}")
                    ok += 1
                else:
                    self.root.after(0, self._log, "  -> FAILED")
            except Exception as e:
                self.root.after(0, self._log, f"  -> ERROR: {e}")
            self.root.after(0, self._advance)

        self.root.after(0, self._log, f"\nDone: {ok}/{len(panos)} route panoramas downloaded to {out}")
        self.root.after(0, lambda: self.route_dl_btn.config(state="normal"))
        self.root.after(0, lambda: self.route_find_btn.config(state="normal"))

    # ── Area find ──

    def _start_area_find(self):
        self.area_find_btn.config(state="disabled")
        self.area_dl_btn.config(state="disabled")
        self._clear_log()
        self.area_info.config(text="Scanning area for panoramas...")

        if self.area_mode.get() == "radius":
            center_str = self.area_center.get().strip()
            if not center_str:
                self._log("Please enter a center point.")
                self.area_find_btn.config(state="normal")
                return
            threading.Thread(target=self._run_radius_find, args=(center_str,), daemon=True).start()
        else:
            nw_str = self.area_nw.get().strip()
            se_str = self.area_se.get().strip()
            if not nw_str or not se_str:
                self._log("Please enter both NW and SE corners.")
                self.area_find_btn.config(state="normal")
                return
            threading.Thread(target=self._run_area_find, args=(nw_str, se_str), daemon=True).start()

    def _run_area_find(self, nw_str: str, se_str: str):
        try:
            nw = resolve_to_coords(nw_str)
            se = resolve_to_coords(se_str)
        except ValueError as e:
            self.root.after(0, self._log, f"Error: {e}")
            self.root.after(0, lambda: self.area_find_btn.config(state="normal"))
            return

        north, south = max(nw[0], se[0]), min(nw[0], se[0])
        east, west = max(nw[1], se[1]), min(nw[1], se[1])

        self.root.after(0, self._log, f"Scanning area ({north:.4f},{west:.4f}) to ({south:.4f},{east:.4f})...")

        try:
            panos = find_area_panoramas(north, south, east, west, spacing_m=self.spacing_var.get())
        except Exception as e:
            self.root.after(0, self._log, f"Area search error: {e}")
            self.root.after(0, lambda: self.area_find_btn.config(state="normal"))
            return

        self._finish_area_find(panos)

    def _run_radius_find(self, center_str: str):
        try:
            center = resolve_to_coords(center_str)
        except ValueError as e:
            self.root.after(0, self._log, f"Error: {e}")
            self.root.after(0, lambda: self.area_find_btn.config(state="normal"))
            return

        try:
            panos = find_radius_panoramas(center[0], center[1], radius_m=self.area_radius_var.get(), spacing_m=self.spacing_var.get())
        except Exception as e:
            self.root.after(0, self._log, f"Radius search error: {e}")
            self.root.after(0, lambda: self.area_find_btn.config(state="normal"))
            return

        self._finish_area_find(panos)

    def _finish_area_find(self, panos):
        self._area_panos = panos
        count = len(panos)
        self.root.after(0, self._log, f"Found {count} unique panoramas in area.")
        self.root.after(0, lambda: self.area_info.config(text=f"Found {count} panoramas. Click 'Download All' to save them."))
        self.root.after(0, lambda: self.area_find_btn.config(state="normal"))
        if count > 0:
            self.root.after(0, lambda: self.area_dl_btn.config(state="normal"))

    # ── Pano Splitter tab ──

    def _build_splitter_tab(self, parent):
        frm = tk.Frame(parent)
        frm.pack(fill="x", padx=8, pady=(8, 4))

        # Input mode
        tk.Label(frm, text="Input:").grid(row=0, column=0, sticky="w", pady=4)
        mode_frm = tk.Frame(frm)
        mode_frm.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self.splitter_input_mode = tk.StringVar(value="folder")
        tk.Radiobutton(mode_frm, text="Folder", variable=self.splitter_input_mode, value="folder").pack(side="left")
        tk.Radiobutton(mode_frm, text="Single file", variable=self.splitter_input_mode, value="file").pack(side="left", padx=8)

        # Input path
        tk.Label(frm, text="Input path:").grid(row=1, column=0, sticky="w", pady=4)
        inp_frm = tk.Frame(frm)
        inp_frm.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        self.splitter_input_var = tk.StringVar()
        tk.Entry(inp_frm, textvariable=self.splitter_input_var, width=42).pack(side="left")
        tk.Button(inp_frm, text="Browse", command=self._splitter_browse_input).pack(side="left", padx=4)

        # Output path
        tk.Label(frm, text="Output folder:").grid(row=2, column=0, sticky="w", pady=4)
        out_frm = tk.Frame(frm)
        out_frm.grid(row=2, column=1, sticky="w", padx=4, pady=4)
        self.splitter_output_var = tk.StringVar()
        tk.Entry(out_frm, textvariable=self.splitter_output_var, width=42).pack(side="left")
        tk.Button(out_frm, text="Browse", command=self._splitter_browse_output).pack(side="left", padx=4)

        # FOV
        tk.Label(frm, text="FOV (degrees):").grid(row=3, column=0, sticky="w", pady=4)
        self.splitter_fov_var = tk.IntVar(value=90)
        tk.Spinbox(frm, from_=30, to=150, textvariable=self.splitter_fov_var, width=6,
                   command=self._update_grid_preview).grid(row=3, column=1, sticky="w", padx=4, pady=4)

        # Overlap
        tk.Label(frm, text="Overlap (%):").grid(row=4, column=0, sticky="w", pady=4)
        self.splitter_overlap_var = tk.IntVar(value=40)
        tk.Spinbox(frm, from_=10, to=80, textvariable=self.splitter_overlap_var, width=6,
                   command=self._update_grid_preview).grid(row=4, column=1, sticky="w", padx=4, pady=4)

        # Tile size
        tk.Label(frm, text="Tile size (px):").grid(row=5, column=0, sticky="w", pady=4)
        self.splitter_size_var = tk.IntVar(value=1024)
        ttk.Combobox(frm, textvariable=self.splitter_size_var, values=[512, 1024, 2048, 4096],
                     width=6, state="readonly").grid(row=5, column=1, sticky="w", padx=4, pady=4)

        # Pitch range
        tk.Label(frm, text="Pitch range:").grid(row=6, column=0, sticky="w", pady=4)
        pitch_frm = tk.Frame(frm)
        pitch_frm.grid(row=6, column=1, sticky="w", padx=4, pady=4)
        self.splitter_pitch_min_var = tk.IntVar(value=-60)
        self.splitter_pitch_max_var = tk.IntVar(value=60)
        tk.Spinbox(pitch_frm, from_=-90, to=0, textvariable=self.splitter_pitch_min_var, width=5,
                   command=self._update_grid_preview).pack(side="left")
        tk.Label(pitch_frm, text=" to ").pack(side="left")
        tk.Spinbox(pitch_frm, from_=0, to=90, textvariable=self.splitter_pitch_max_var, width=5,
                   command=self._update_grid_preview).pack(side="left")
        tk.Label(pitch_frm, text=" degrees").pack(side="left")

        # Grid preview
        self.splitter_grid_info = tk.Label(frm, text="", anchor="w", fg="#555")
        self.splitter_grid_info.grid(row=7, column=0, columnspan=2, sticky="w", padx=4, pady=(6, 2))

        # Process button
        btn_row = tk.Frame(parent)
        btn_row.pack(pady=6)
        self.splitter_btn = tk.Button(btn_row, text="Process", width=16, command=self._start_splitter)
        self.splitter_btn.pack()

        self._update_grid_preview()

    def _splitter_browse_input(self):
        if self.splitter_input_mode.get() == "file":
            p = filedialog.askopenfilename(
                filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp"), ("All files", "*.*")]
            )
        else:
            p = filedialog.askdirectory()
        if p:
            self.splitter_input_var.set(p)
            if not self.splitter_output_var.get():
                self.splitter_output_var.set(str(Path(p if self.splitter_input_mode.get() == "folder" else str(Path(p).parent)) / "tiles"))

    def _splitter_browse_output(self):
        d = filedialog.askdirectory()
        if d:
            self.splitter_output_var.set(d)

    def _update_grid_preview(self):
        try:
            info = get_grid_info(
                fov_deg=float(self.splitter_fov_var.get()),
                overlap=self.splitter_overlap_var.get() / 100,
                pitch_range=(self.splitter_pitch_min_var.get(), self.splitter_pitch_max_var.get()),
            )
            self.splitter_grid_info.config(
                text=f"Grid: {info['rows']} rows x {info['columns']} cols = {info['total_tiles']} tiles per image"
            )
        except Exception:
            self.splitter_grid_info.config(text="Invalid settings")

    def _start_splitter(self):
        input_path = self.splitter_input_var.get().strip()
        output_path = self.splitter_output_var.get().strip()
        if not input_path:
            self._log("Please select an input file or folder.")
            return
        if not output_path:
            self._log("Please select an output folder.")
            return

        input_p = Path(input_path)
        if self.splitter_input_mode.get() == "file":
            if not input_p.is_file():
                self._log(f"File not found: {input_path}")
                return
            images = [input_p]
        else:
            if not input_p.is_dir():
                self._log(f"Folder not found: {input_path}")
                return
            images = [f for f in input_p.iterdir() if f.suffix.lower() in _PANO_EXTENSIONS]
            if not images:
                self._log("No image files found in the folder.")
                return

        self.splitter_btn.config(state="disabled")
        self._clear_log()
        self.progress["maximum"] = len(images)
        threading.Thread(target=self._run_splitter, args=(images, Path(output_path)), daemon=True).start()

    def _run_splitter(self, images: list, output_path: Path):
        output_path.mkdir(parents=True, exist_ok=True)
        fov = float(self.splitter_fov_var.get())
        overlap = self.splitter_overlap_var.get() / 100
        tile_size = int(self.splitter_size_var.get())
        pitch_range = (self.splitter_pitch_min_var.get(), self.splitter_pitch_max_var.get())

        ok = 0
        total_tiles = 0
        for i, img_path in enumerate(images, 1):
            self.root.after(0, self._log, f"[{i}/{len(images)}] {img_path.name}")
            try:
                results = extract_tiles(
                    equirect_path=img_path,
                    output_dir=output_path,
                    fov_deg=fov,
                    overlap=overlap,
                    tile_size=tile_size,
                    pitch_range=pitch_range,
                )
                for tile_path, tile_array, tile_info in results:
                    save_tile_with_exif(
                        tile_array=tile_array,
                        output_path=tile_path,
                        focal_length_mm=tile_info.focal_length_mm,
                        fov_deg=tile_info.fov_deg,
                    )
                total_tiles += len(results)
                self.root.after(0, self._log, f"  -> {len(results)} tiles extracted")
                ok += 1
            except Exception as e:
                self.root.after(0, self._log, f"  -> ERROR: {e}")
            self.root.after(0, self._advance)

        self.root.after(0, self._log, f"\nDone: {total_tiles} tiles from {ok}/{len(images)} images -> {output_path}")
        self.root.after(0, lambda: self.splitter_btn.config(state="normal"))

    # ── Area download ──

    def _start_area_dl(self):
        if not self._area_panos:
            return
        self.area_dl_btn.config(state="disabled")
        self.area_find_btn.config(state="disabled")
        self._clear_log()
        self.progress["maximum"] = len(self._area_panos)
        threading.Thread(target=self._run_area_dl, daemon=True).start()

    def _run_area_dl(self):
        base = Path(self.folder_var.get())
        if self.area_mode.get() == "radius":
            center_str = self.area_center.get().strip().replace(",", "_").replace(" ", "")[:20]
            radius = self.area_radius_var.get()
            out = base / f"radius_{center_str}_{radius}m"
        else:
            nw_str = self.area_nw.get().strip().replace(",", "_").replace(" ", "")[:20]
            se_str = self.area_se.get().strip().replace(",", "_").replace(" ", "")[:20]
            out = base / f"area_{nw_str}_to_{se_str}"
        out.mkdir(parents=True, exist_ok=True)
        zoom = self.zoom_var.get()
        fmt = self.fmt_var.get()
        panos = self._area_panos

        ok = 0
        for i, pano in enumerate(panos, 1):
            self.root.after(0, self._log, f"[{i}/{len(panos)}] {pano.pano_id}")
            try:
                result = asyncio.run(_download_by_id(pano.pano_id, out, zoom, fmt))
                if result:
                    self.root.after(0, self._log, f"  -> {result}")
                    ok += 1
                else:
                    self.root.after(0, self._log, "  -> FAILED")
            except Exception as e:
                self.root.after(0, self._log, f"  -> ERROR: {e}")
            self.root.after(0, self._advance)

        self.root.after(0, self._log, f"\nDone: {ok}/{len(panos)} area panoramas downloaded to {out}")
        self.root.after(0, lambda: self.area_dl_btn.config(state="normal"))
        self.root.after(0, lambda: self.area_find_btn.config(state="normal"))


# ── Download helpers ──

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

    return await _download_by_id(pano_id, out, zoom, fmt)


async def _download_by_id(pano_id: str, out: Path, zoom: int, fmt: str) -> str | None:
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
