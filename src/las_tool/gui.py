from __future__ import annotations

import os
import queue
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import laspy
import numpy as np

from .cancellation import OperationCancelled
from .downsample import DownsampleResult, downsample_las, validate_resolution
from .split_crop import (
    Bounds2D,
    CropResult,
    GridSelection,
    GridSplitResult,
    LineSelection,
    PolygonSelection,
    PreviewData,
    SplitResult,
    combine_preview_data,
    crop_las,
    grid_split_las,
    load_preview_data,
    split_las,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except ImportError:
    DND_FILES = "DND_Files"
    TkinterDnD = None
    HAS_DND = False


@dataclass
class FileItem:
    path: Path
    status: str = "Pending"


@dataclass
class CancelledResult:
    input_path: Path


CANCELLED_MESSAGE = "__cancelled__"


class LogMixin:
    log_text: tk.Text

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


class DownsamplePage(ttk.Frame, LogMixin):
    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent, padding=0)

        self.files: dict[str, FileItem] = {}
        self.processing = False
        self.worker_thread: threading.Thread | None = None
        self.event_queue: "queue.Queue[tuple[str, dict]]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.progress_var = tk.DoubleVar(value=0.0)

        self.resolution_var = tk.StringVar(value="0.2")
        self.status_var = tk.StringVar(value="Ready")
        self.drag_hint_var = tk.StringVar(
            value="Drag .las files into the list"
            if HAS_DND
            else "Drag-and-drop is unavailable; use Add Files instead"
        )

        self._build_layout()
        self._configure_drop()
        self.after(100, self._drain_events)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(5, weight=1)

        ttk.Label(top, text="Resolution (m)").grid(row=0, column=0, sticky="w")
        self.resolution_entry = ttk.Entry(top, textvariable=self.resolution_var, width=12)
        self.resolution_entry.grid(row=0, column=1, padx=(8, 16), sticky="w")

        self.add_button = ttk.Button(top, text="Add Files", command=self.add_files)
        self.add_button.grid(row=0, column=2, padx=(0, 8))

        self.remove_button = ttk.Button(top, text="Remove Selected", command=self.remove_selected)
        self.remove_button.grid(row=0, column=3, padx=(0, 8))

        self.clear_button = ttk.Button(top, text="Clear List", command=self.clear_files)
        self.clear_button.grid(row=0, column=4, padx=(0, 8))

        self.start_button = ttk.Button(
            top, text="Start", command=self.start_processing, style="Primary.TButton"
        )
        self.start_button.grid(row=0, column=5, sticky="e")

        self.cancel_button = ttk.Button(
            top, text="Cancel", command=self.cancel_processing, state="disabled"
        )
        self.cancel_button.grid(row=0, column=6, padx=(8, 0))

        ttk.Label(top, textvariable=self.drag_hint_var, foreground="#4f6b7a").grid(
            row=1,
            column=0,
            columnspan=7,
            sticky="w",
            pady=(8, 0),
        )

        table_frame = ttk.Frame(self, padding=(12, 0, 12, 12))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("name", "folder", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("name", text="File")
        self.tree.heading("folder", text="Folder")
        self.tree.heading("status", text="Status")
        self.tree.column("name", width=260, anchor="w")
        self.tree.column("folder", width=460, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        log_frame = ttk.LabelFrame(self, text="Activity Log", padding=12)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        ttk.Progressbar(self, variable=self.progress_var, maximum=100).grid(
            row=3, column=0, sticky="ew", padx=12, pady=(0, 8)
        )

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="groove", padding=8)
        status_bar.grid(row=4, column=0, sticky="ew")

    def _configure_drop(self) -> None:
        if not HAS_DND:
            self.log("Drag-and-drop is unavailable. Use Add Files to select .las files.")
            return

        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self._on_drop)
        self.log("Drag-and-drop is enabled. Drop one or more .las files into the list.")

    def _on_drop(self, event) -> None:
        paths = [Path(item) for item in self.winfo_toplevel().tk.splitlist(event.data)]
        self._add_paths(paths)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select LAS Files",
            filetypes=[("LAS files", "*.las")],
            parent=self,
        )
        if not paths:
            return
        self._add_paths(Path(item) for item in paths)

    def _add_paths(self, paths) -> None:
        added = 0
        for raw_path in paths:
            path = Path(raw_path)
            if path.suffix.lower() != ".las":
                self.log(f"Ignored non-LAS file: {path}")
                continue

            normalized = str(path.resolve())
            if normalized in self.files:
                continue

            self.files[normalized] = FileItem(path=path)
            self.tree.insert(
                "",
                "end",
                iid=normalized,
                values=(path.name, str(path.parent), "Pending"),
            )
            added += 1

        if added:
            self.status_var.set(f"Added {added} file(s)")
            self.log(f"Added {added} LAS file(s).")

    def remove_selected(self) -> None:
        if self.processing:
            return

        for item_id in self.tree.selection():
            self.tree.delete(item_id)
            self.files.pop(item_id, None)

        self.status_var.set(f"{len(self.files)} file(s) in the list")

    def clear_files(self) -> None:
        if self.processing:
            return

        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.files.clear()
        self.status_var.set("List cleared")

    def start_processing(self) -> None:
        if self.processing:
            return

        if not self.files:
            messagebox.showwarning("No Files", "Add at least one .las file first.", parent=self)
            return

        try:
            resolution = validate_resolution(self.resolution_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid Resolution", str(exc), parent=self)
            return

        self.cancel_event.clear()
        self.progress_var.set(0.0)
        self.processing = True
        self._set_controls_enabled(False)
        self.status_var.set("Processing...")
        self.log(f"Starting batch downsampling at {resolution} m.")

        for item_id in self.tree.get_children():
            self.tree.set(item_id, "status", "Queued")

        file_paths = [item.path for item in self.files.values()]
        self.worker_thread = threading.Thread(
            target=self._worker_run_parallel,
            args=(file_paths, resolution),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel_processing(self) -> None:
        if not self.processing or self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Cancelling... finishing the current chunk.")
        self.log("Cancel requested. Unfinished files will be discarded.")

    def _worker_run(self, file_paths: list[Path], resolution: float) -> None:
        completed = 0
        total_files = len(file_paths)

        for input_path in file_paths:
            item_id = str(input_path.resolve())
            self.event_queue.put(("file_status", {"item_id": item_id, "status": "Processing"}))
            self.event_queue.put(("log", {"message": f"Processing {input_path}"}))

            try:
                result = downsample_las(
                    input_path,
                    resolution,
                    progress_callback=lambda done, total, item_id=item_id: self.event_queue.put(
                        ("progress", {"item_id": item_id, "done": done, "total": total})
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                message = f"{input_path.name} failed: {exc}"
                self.event_queue.put(("file_status", {"item_id": item_id, "status": "Failed"}))
                self.event_queue.put(("log", {"message": message}))
                self.event_queue.put(("log", {"message": traceback.format_exc(limit=3)}))
            else:
                if result.skipped:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "Skipped"}))
                    self.event_queue.put(("log", {"message": f"{input_path.name}: {result.message}"}))
                else:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "Completed"}))
                    self.event_queue.put(("log", {"message": self._format_result_message(result)}))

            completed += 1
            self.event_queue.put(
                ("batch_progress", {"completed": completed, "total_files": total_files})
            )

        self.event_queue.put(("done", {}))

    def _worker_run_parallel(self, file_paths: list[Path], resolution: float) -> None:
        completed = 0
        total_files = len(file_paths)
        max_workers = self._worker_count(total_files)
        progress_lock = threading.Lock()
        point_counts: dict[str, int] = {}
        file_progress: dict[str, int] = {}

        for input_path in file_paths:
            item_id = str(input_path.resolve())
            file_progress[item_id] = 0
            try:
                point_counts[item_id] = self._read_point_count(input_path)
            except Exception:
                point_counts[item_id] = 0

        total_points = sum(point_counts.values())
        self.event_queue.put(
            (
                "parallel_started",
                {"workers": max_workers, "total_files": total_files},
            )
        )

        def make_progress_callback(item_id: str):
            def progress(done: int, total: int) -> None:
                with progress_lock:
                    file_progress[item_id] = done
                    aggregate_done = sum(file_progress.values())
                self.event_queue.put(
                    (
                        "progress",
                        {"item_id": item_id, "done": aggregate_done, "total": total_points or total},
                    )
                )

            return progress

        def process_one(input_path: Path) -> tuple[str, Path, DownsampleResult | None, str | None, str | None]:
            item_id = str(input_path.resolve())
            if self.cancel_event.is_set():
                return item_id, input_path, None, CANCELLED_MESSAGE, None
            self.event_queue.put(("file_status", {"item_id": item_id, "status": "Processing"}))
            self.event_queue.put(("log", {"message": f"Processing {input_path}"}))

            try:
                result = downsample_las(
                    input_path,
                    resolution,
                    progress_callback=make_progress_callback(item_id),
                    cancel_event=self.cancel_event,
                )
            except OperationCancelled:
                return item_id, input_path, None, CANCELLED_MESSAGE, None
            except Exception as exc:  # noqa: BLE001
                message = f"{input_path.name} failed: {exc}"
                return item_id, input_path, None, message, traceback.format_exc(limit=3)

            return item_id, input_path, result, None, None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_one, input_path) for input_path in file_paths]

            for future in as_completed(futures):
                item_id, input_path, result, error_message, error_detail = future.result()
                with progress_lock:
                    if point_counts[item_id]:
                        file_progress[item_id] = point_counts[item_id]
                    aggregate_done = sum(file_progress.values())

                self.event_queue.put(
                    (
                        "progress",
                        {"item_id": item_id, "done": aggregate_done, "total": total_points},
                    )
                )

                if error_message == CANCELLED_MESSAGE:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "Cancelled"}))
                    self.event_queue.put(("log", {"message": f"{input_path.name}: cancelled."}))
                elif result is None:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "Failed"}))
                    self.event_queue.put(("log", {"message": error_message or f"{input_path.name} failed"}))
                    if error_detail:
                        self.event_queue.put(("log", {"message": error_detail}))
                elif result.skipped:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "Skipped"}))
                    self.event_queue.put(("log", {"message": f"{input_path.name}: {result.message}"}))
                else:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "Completed"}))
                    self.event_queue.put(("log", {"message": self._format_result_message(result)}))

                completed += 1
                self.event_queue.put(("batch_progress", {"completed": completed, "total_files": total_files}))

        self.event_queue.put(("done", {}))

    @staticmethod
    def _worker_count(file_count: int) -> int:
        cpu_count = os.cpu_count() or 1
        return max(1, min(file_count, max(1, cpu_count - 1), 8))

    @staticmethod
    def _read_point_count(path: Path) -> int:
        with laspy.open(path) as reader:
            return int(reader.header.point_count)

    @staticmethod
    def _format_result_message(result: DownsampleResult) -> str:
        return (
            f"{result.input_path.name}: {result.input_points:,} -> {result.output_points:,} points, "
            f"saved as {result.output_path.name}"
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.resolution_entry,
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.start_button,
        ):
            widget.configure(state=state)
        self.cancel_button.configure(state="disabled" if enabled else "normal")

    def _drain_events(self) -> None:
        try:
            while True:
                event_name, payload = self.event_queue.get_nowait()
                self._handle_event(event_name, payload)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._drain_events)

    def _handle_event(self, event_name: str, payload: dict) -> None:
        if event_name == "file_status":
            self.tree.set(payload["item_id"], "status", payload["status"])
        elif event_name == "parallel_started":
            self.log(
                f"Parallel downsampling: {payload['workers']} worker(s) for "
                f"{payload['total_files']} file(s)."
            )
        elif event_name == "progress":
            done = payload["done"]
            total = payload["total"]
            if total:
                percent = done / total * 100
                self.progress_var.set(percent)
                if not self.cancel_event.is_set():
                    self.status_var.set(f"Processing {percent:.1f}%")
        elif event_name == "batch_progress":
            self.status_var.set(f"Completed {payload['completed']} / {payload['total_files']} file(s)")
        elif event_name == "log":
            self.log(payload["message"])
        elif event_name == "done":
            self.processing = False
            self._set_controls_enabled(True)
            statuses = [self.tree.set(item_id, "status") for item_id in self.tree.get_children()]
            summary = (
                f"{statuses.count('Completed')} completed, "
                f"{statuses.count('Skipped')} skipped, "
                f"{statuses.count('Failed')} failed"
            )
            if statuses.count("Cancelled"):
                summary += f", {statuses.count('Cancelled')} cancelled"
            if not self.cancel_event.is_set():
                self.progress_var.set(100.0)
            self.status_var.set(f"Finished: {summary}")
            self.log(f"Batch processing finished: {summary}.")


class SplitCropPage(ttk.Frame, LogMixin):
    PREVIEW_LIMIT = 80_000
    PREVIEW_PADDING = 24
    PREVIEW_BACKGROUND = np.array([245, 247, 250], dtype=np.uint8)

    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent, padding=0)

        self.current_paths: list[Path] = []
        self.preview_data: PreviewData | None = None
        self.mode_var = tk.StringVar(value="crop")
        self.file_var = tk.StringVar(value="No files loaded")
        self.hint_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(
            value="Open or drop .las files to preview, crop, or split them."
        )
        self.grid_rows_var = tk.StringVar(value="2")
        self.grid_cols_var = tk.StringVar(value="2")

        self.loading_preview = False
        self.processing = False
        self.event_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.progress_var = tk.DoubleVar(value=0.0)
        self.coord_var = tk.StringVar(value="")

        self.crop_selection: PolygonSelection | None = None
        self.crop_points: list[tuple[float, float]] = []
        self.crop_hover_point: tuple[float, float] | None = None
        self.grid_selection: Bounds2D | None = None
        self.drag_anchor: tuple[float, float] | None = None
        self.drag_point: tuple[float, float] | None = None
        self.drag_mode: str | None = None
        self.split_points: list[tuple[float, float]] = []

        self.preview_photo: tk.PhotoImage | None = None
        self.preview_cache_key: tuple[int, int, int, float, float, float, bool] | None = None
        self.transform: dict[str, float] | None = None

        self.view_zoom: float = 1.0
        self.view_pan_x: float = 0.0
        self.view_pan_y: float = 0.0
        self.pan_start_x: float | None = None
        self.pan_start_y: float | None = None
        self.panning: bool = False
        self.edl_var = tk.BooleanVar(value=True)

        self._build_layout()
        self._configure_drop()
        self._on_mode_change()
        self.after(100, self._drain_events)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(5, weight=1)

        self.open_button = ttk.Button(top, text="Open LAS", command=self.open_file)
        self.open_button.grid(row=0, column=0, padx=(0, 8))

        self.remove_file_button = ttk.Button(
            top, text="Remove Selected", command=self.remove_selected_files
        )
        self.remove_file_button.grid(row=0, column=1, padx=(0, 8))

        self.clear_files_button = ttk.Button(
            top, text="Clear Files", command=self.clear_loaded_files
        )
        self.clear_files_button.grid(row=0, column=2, padx=(0, 8))

        ttk.Separator(top, orient="vertical").grid(row=0, column=3, sticky="ns", padx=8)

        mode_frame = ttk.Frame(top)
        mode_frame.grid(row=0, column=4, sticky="w")

        self.crop_radio = ttk.Radiobutton(
            mode_frame,
            text="Polygon Crop",
            variable=self.mode_var,
            value="crop",
            command=self._on_mode_change,
        )
        self.crop_radio.grid(row=0, column=0, padx=(0, 8))

        self.split_radio = ttk.Radiobutton(
            mode_frame,
            text="Line Split",
            variable=self.mode_var,
            value="split",
            command=self._on_mode_change,
        )
        self.split_radio.grid(row=0, column=1, padx=(0, 8))

        self.grid_radio = ttk.Radiobutton(
            mode_frame,
            text="Grid Split",
            variable=self.mode_var,
            value="grid",
            command=self._on_mode_change,
        )
        self.grid_radio.grid(row=0, column=2)

        self.cancel_button = ttk.Button(
            top, text="Cancel", command=self.cancel_export, state="disabled"
        )
        self.cancel_button.grid(row=0, column=6, padx=(8, 8))

        self.export_button = ttk.Button(
            top, text="Export", command=self.start_export, style="Primary.TButton"
        )
        self.export_button.grid(row=0, column=7)

        ttk.Label(top, textvariable=self.hint_var, foreground="#4f6b7a").grid(
            row=1,
            column=0,
            columnspan=8,
            sticky="w",
            pady=(8, 0),
        )

        self.grid_controls = ttk.Frame(top)
        self.grid_controls.grid(row=2, column=0, columnspan=8, sticky="w", pady=(10, 0))

        ttk.Label(self.grid_controls, text="Rows").grid(row=0, column=0, sticky="w")
        self.grid_rows_entry = ttk.Entry(self.grid_controls, textvariable=self.grid_rows_var, width=6)
        self.grid_rows_entry.grid(row=0, column=1, padx=(6, 12))

        ttk.Label(self.grid_controls, text="Columns").grid(row=0, column=2, sticky="w")
        self.grid_cols_entry = ttk.Entry(self.grid_controls, textvariable=self.grid_cols_var, width=6)
        self.grid_cols_entry.grid(row=0, column=3, padx=(6, 12))

        self.grid_2x2_button = ttk.Button(
            self.grid_controls,
            text="2 x 2",
            command=lambda: self._set_grid_preset(2, 2),
        )
        self.grid_2x2_button.grid(row=0, column=4, padx=(0, 8))

        self.grid_2x4_button = ttk.Button(
            self.grid_controls,
            text="2 x 4",
            command=lambda: self._set_grid_preset(2, 4),
        )
        self.grid_2x4_button.grid(row=0, column=5, padx=(0, 8))

        ttk.Label(
            self.grid_controls,
            text=(
                "Grid mode covers the full point cloud by default. "
                "Drag a rectangle in the preview to limit the area."
            ),
            foreground="#4f6b7a",
        ).grid(row=0, column=6, sticky="w", padx=(8, 0))

        file_frame = ttk.LabelFrame(self, text="Loaded Files", padding=12)
        file_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        file_frame.columnconfigure(0, weight=1)

        columns = ("name", "folder", "status")
        self.file_tree = ttk.Treeview(file_frame, columns=columns, show="headings", selectmode="extended", height=4)
        self.file_tree.heading("name", text="File")
        self.file_tree.heading("folder", text="Folder")
        self.file_tree.heading("status", text="Status")
        self.file_tree.column("name", width=260, anchor="w")
        self.file_tree.column("folder", width=560, anchor="w")
        self.file_tree.column("status", width=100, anchor="center")
        self.file_tree.grid(row=0, column=0, sticky="ew")

        file_scroll = ttk.Scrollbar(file_frame, orient="vertical", command=self.file_tree.yview)
        file_scroll.grid(row=0, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=file_scroll.set)

        ttk.Label(file_frame, textvariable=self.file_var, foreground="#4f6b7a").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        preview_frame = ttk.LabelFrame(self, text="Top View", padding=12)
        preview_frame.grid(row=2, column=0, sticky="nsew", padx=12)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        view_bar = ttk.Frame(preview_frame)
        view_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        view_bar.columnconfigure(3, weight=1)

        self.clear_selection_button = ttk.Button(
            view_bar, text="Clear Selection", command=self.clear_selection
        )
        self.clear_selection_button.grid(row=0, column=0, padx=(0, 8))

        self.reset_view_button = ttk.Button(view_bar, text="Reset View", command=self.reset_view)
        self.reset_view_button.grid(row=0, column=1, padx=(0, 8))

        self.edl_check = ttk.Checkbutton(
            view_bar, text="Eye Dome Lighting", variable=self.edl_var, command=self._on_edl_toggle
        )
        self.edl_check.grid(row=0, column=2, padx=(0, 8))

        ttk.Label(view_bar, textvariable=self.coord_var, foreground="#4f6b7a").grid(
            row=0, column=3, sticky="e"
        )

        self.canvas = tk.Canvas(
            preview_frame,
            background="#f8fafc",
            highlightthickness=1,
            highlightbackground="#d3dde5",
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Leave>", lambda _event: self.coord_var.set(""))
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<MouseWheel>", self._on_canvas_wheel)
        self.canvas.bind("<Button-4>", self._on_canvas_wheel)
        self.canvas.bind("<Button-5>", self._on_canvas_wheel)
        self.canvas.bind("<ButtonPress-2>", self._on_canvas_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_canvas_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._on_canvas_pan_end)
        self.canvas.bind("<ButtonPress-3>", self._on_canvas_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_canvas_pan_move)
        self.canvas.bind("<ButtonRelease-3>", self._on_canvas_pan_end)

        log_frame = ttk.LabelFrame(self, text="Activity Log", padding=12)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=12)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        ttk.Progressbar(self, variable=self.progress_var, maximum=100).grid(
            row=4, column=0, sticky="ew", padx=12, pady=(0, 8)
        )

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="groove", padding=8)
        status_bar.grid(row=5, column=0, sticky="ew")

        self.grid_rows_var.trace_add("write", self._on_grid_value_change)
        self.grid_cols_var.trace_add("write", self._on_grid_value_change)

    def _configure_drop(self) -> None:
        if not HAS_DND:
            self.log("Drag-and-drop is unavailable. Use Open LAS to select files.")
            return

        self.canvas.drop_target_register(DND_FILES)
        self.canvas.dnd_bind("<<Drop>>", self._on_preview_drop)
        self.log("Drag-and-drop is enabled in the preview area.")

    def _on_preview_drop(self, event) -> None:
        paths = [Path(item) for item in self.winfo_toplevel().tk.splitlist(event.data)]
        valid_paths = [path for path in paths if path.suffix.lower() == ".las"]
        ignored_paths = [path for path in paths if path.suffix.lower() != ".las"]

        for path in ignored_paths:
            self.log(f"Ignored non-LAS file: {path}")

        if not valid_paths:
            self.status_var.set("No supported LAS files were found.")
            return

        self._start_preview_load([*self.current_paths, *valid_paths])

    def open_file(self) -> None:
        if self.loading_preview or self.processing:
            return

        paths = filedialog.askopenfilenames(
            title="Select LAS Files",
            filetypes=[("LAS files", "*.las")],
            parent=self,
        )
        if paths:
            self._start_preview_load([Path(path) for path in paths])

    def _start_preview_load(self, paths: list[Path]) -> None:
        normalized_paths = self._normalize_input_paths(paths)
        if not normalized_paths:
            return

        self.loading_preview = True
        self._set_controls_enabled(False)
        self.status_var.set("Loading preview...")
        self.file_var.set(self._format_file_label(normalized_paths))
        self._sync_file_tree(normalized_paths, "Loading")
        self.log(f"Loading a preview for {len(normalized_paths)} LAS file(s).")
        for path in normalized_paths:
            self.log(f"  - {path}")

        thread = threading.Thread(
            target=self._load_preview_worker,
            args=(normalized_paths,),
            daemon=True,
        )
        thread.start()

    def _load_preview_worker(self, paths: list[Path]) -> None:
        try:
            point_counts = [self._read_point_count(path) for path in paths]
            total_points = sum(point_counts)
            per_file_limit = max(1, self.PREVIEW_LIMIT // max(len(paths), 1))
            previews: list[PreviewData] = []
            completed_points = 0

            for path, point_count in zip(paths, point_counts):
                preview = load_preview_data(
                    path,
                    max_points=per_file_limit,
                    progress_callback=lambda done, total, offset=completed_points, grand_total=total_points: self.event_queue.put(
                        ("preview_progress", {"done": offset + done, "total": grand_total or total})
                    ),
                )
                previews.append(preview)
                completed_points += point_count

            preview = combine_preview_data(previews, label_path=paths[0])
        except Exception as exc:  # noqa: BLE001
            self.event_queue.put(("preview_error", (paths, exc, traceback.format_exc(limit=3))))
        else:
            self.event_queue.put(("preview_loaded", {"preview": preview, "paths": paths}))

    @staticmethod
    def _normalize_input_paths(paths: list[Path]) -> list[Path]:
        normalized: list[Path] = []
        seen: set[str] = set()
        for raw_path in paths:
            if raw_path.suffix.lower() != ".las":
                continue
            resolved = str(raw_path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            normalized.append(raw_path)
        return normalized

    @staticmethod
    def _format_file_label(paths: list[Path]) -> str:
        if not paths:
            return "No files loaded"
        if len(paths) == 1:
            return str(paths[0])
        return f"{len(paths)} LAS files (first: {paths[0].name})"

    def _sync_file_tree(self, paths: list[Path], status: str = "Loaded") -> None:
        for item_id in self.file_tree.get_children():
            self.file_tree.delete(item_id)

        for path in paths:
            item_id = str(path.resolve())
            self.file_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(path.name, str(path.parent), status),
            )

    @staticmethod
    def _read_point_count(path: Path) -> int:
        with laspy.open(path) as reader:
            return int(reader.header.point_count)

    def clear_selection(self) -> None:
        if self.loading_preview or self.processing:
            return

        mode = self.mode_var.get()
        self.drag_anchor = None
        self.drag_point = None
        self.drag_mode = None

        if mode == "crop":
            self.crop_selection = None
            self.crop_points = []
            self.crop_hover_point = None
        elif mode == "grid":
            self.grid_selection = None
        else:
            self.split_points = []

        self._update_mode_hint()
        self._draw_preview()

    def remove_selected_files(self) -> None:
        if self.loading_preview or self.processing:
            return

        selected_ids = set(self.file_tree.selection())
        if not selected_ids:
            self.status_var.set("Select one or more files to remove.")
            return

        remaining_paths = [
            path
            for path in self.current_paths
            if str(path.resolve()) not in selected_ids
        ]
        removed_count = len(self.current_paths) - len(remaining_paths)

        if not remaining_paths:
            self.clear_loaded_files()
            self.log(f"Removed {removed_count} file(s). No files remain loaded.")
            self.status_var.set("Selected files removed. No files are loaded.")
            return

        self.log(
            f"Removed {removed_count} file(s). Reloading the remaining "
            f"{len(remaining_paths)} file(s)."
        )
        self._start_preview_load(remaining_paths)

    def clear_loaded_files(self) -> None:
        if self.loading_preview or self.processing:
            return

        had_files = bool(self.current_paths or self.preview_data is not None)
        self.current_paths = []
        self.preview_data = None
        self.crop_selection = None
        self.crop_points = []
        self.crop_hover_point = None
        self.grid_selection = None
        self.split_points = []
        self.drag_anchor = None
        self.drag_point = None
        self.drag_mode = None
        self.view_zoom = 1.0
        self.view_pan_x = 0.0
        self.view_pan_y = 0.0
        self.file_var.set("No files loaded")
        self._sync_file_tree([])
        self._invalidate_preview_cache()
        self._update_mode_hint()
        self._draw_preview()

        if had_files:
            self.status_var.set("Loaded files cleared. Ready for a new batch.")
            self.log("Cleared all files from the split/crop page.")
        else:
            self.status_var.set("No files are currently loaded.")

    def start_export(self) -> None:
        if self.loading_preview or self.processing:
            return

        if self.preview_data is None or not self.current_paths:
            messagebox.showwarning("No Files", "Open or drop at least one .las file first.", parent=self)
            return

        mode = self.mode_var.get()
        if mode == "crop":
            selection = self.crop_selection
            if selection is None or not selection.is_valid():
                messagebox.showwarning(
                    "No Selection", "Draw and close a valid polygon first.", parent=self
                )
                return
        elif mode == "split":
            selection = self._current_line_selection()
            if selection is None or not selection.is_valid():
                messagebox.showwarning(
                    "No Split Line", "Click two points to define a split line first.", parent=self
                )
                return
        else:
            try:
                rows, cols = self._get_grid_shape()
            except ValueError as exc:
                messagebox.showerror("Invalid Grid", str(exc), parent=self)
                return

            bounds = self._grid_bounds_for_export()
            selection = GridSelection(bounds=bounds, rows=rows, cols=cols)

        worker = threading.Thread(
            target=self._export_worker,
            args=(list(self.current_paths), mode, selection),
            daemon=True,
        )

        self.cancel_event.clear()
        self.progress_var.set(0.0)
        self.processing = True
        self._set_controls_enabled(False)
        self.status_var.set("Exporting...")
        self.log(f"Starting {self._mode_label()} for {len(self.current_paths)} file(s).")
        worker.start()

    def cancel_export(self) -> None:
        if not self.processing or self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Cancelling... finishing the current chunk.")
        self.log("Cancel requested. Unfinished outputs will be discarded.")

    def _export_worker(self, paths: list[Path], mode: str, selection: object) -> None:
        try:
            point_counts = [self._read_point_count(path) for path in paths]
            total_points = sum(point_counts)
            max_workers = self._export_worker_count(len(paths))
            progress_lock = threading.Lock()
            file_progress = {str(path.resolve()): 0 for path in paths}
            results_by_index: list[object | None] = [None] * len(paths)
            completed_files = 0

            self.event_queue.put(
                (
                    "export_parallel_started",
                    {"workers": max_workers, "total_files": len(paths)},
                )
            )

            def make_progress_callback(path: Path):
                progress_key = str(path.resolve())

                def progress(done: int, total: int) -> None:
                    with progress_lock:
                        file_progress[progress_key] = done
                        aggregate_done = sum(file_progress.values())
                    self.event_queue.put(
                        (
                            "export_progress",
                            {
                                "done": aggregate_done,
                                "total": total_points or total,
                                "path": str(path),
                            },
                        )
                    )

                return progress

            def export_one(index: int, path: Path) -> tuple[int, object]:
                if self.cancel_event.is_set():
                    return index, CancelledResult(path)
                try:
                    result = self._export_single(
                        path,
                        mode,
                        selection,
                        make_progress_callback(path),
                    )
                except OperationCancelled:
                    return index, CancelledResult(path)
                return index, result

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(export_one, file_index, path)
                    for file_index, path in enumerate(paths)
                ]

                for future in as_completed(futures):
                    file_index, result = future.result()
                    results_by_index[file_index] = result
                    completed_files += 1

                    progress_key = str(paths[file_index].resolve())
                    with progress_lock:
                        file_progress[progress_key] = point_counts[file_index]
                        aggregate_done = sum(file_progress.values())

                    self.event_queue.put(
                        (
                            "export_progress",
                            {
                                "done": aggregate_done,
                                "total": total_points,
                                "path": str(paths[file_index]),
                            },
                        )
                    )
                    self.event_queue.put(
                        (
                            "export_file_complete",
                            {
                                "mode": mode,
                                "result": result,
                                "completed_files": completed_files,
                                "total_files": len(paths),
                            },
                        )
                    )

            results = [result for result in results_by_index if result is not None]
            if len(results) != len(paths):
                raise RuntimeError("Some export tasks did not finish.")
        except Exception as exc:  # noqa: BLE001
            self.event_queue.put(("export_error", (exc, traceback.format_exc(limit=3))))
        else:
            self.event_queue.put(("export_batch_done", {"mode": mode, "results": results}))

    @staticmethod
    def _export_worker_count(file_count: int) -> int:
        cpu_count = os.cpu_count() or 1
        return max(1, min(file_count, max(1, cpu_count - 1), 8))

    def _export_single(
        self,
        path: Path,
        mode: str,
        selection: object,
        progress,
    ) -> object:
        if mode == "crop":
            assert isinstance(selection, PolygonSelection)
            return crop_las(
                path, selection, progress_callback=progress, cancel_event=self.cancel_event
            )
        if mode == "split":
            assert isinstance(selection, LineSelection)
            return split_las(
                path, selection, progress_callback=progress, cancel_event=self.cancel_event
            )
        assert isinstance(selection, GridSelection)
        return grid_split_las(
            path, selection, progress_callback=progress, cancel_event=self.cancel_event
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.open_button,
            self.crop_radio,
            self.split_radio,
            self.grid_radio,
            self.clear_selection_button,
            self.reset_view_button,
            self.edl_check,
            self.remove_file_button,
            self.clear_files_button,
            self.export_button,
            self.grid_rows_entry,
            self.grid_cols_entry,
            self.grid_2x2_button,
            self.grid_2x4_button,
        ):
            widget.configure(state=state)
        self.cancel_button.configure(state="normal" if self.processing else "disabled")

    def _drain_events(self) -> None:
        try:
            while True:
                event_name, payload = self.event_queue.get_nowait()
                self._handle_event(event_name, payload)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._drain_events)

    def _handle_event(self, event_name: str, payload: object) -> None:
        if event_name == "preview_progress":
            assert isinstance(payload, dict)
            total = payload["total"]
            done = payload["done"]
            if total:
                self.progress_var.set(done / total * 100)
                self.status_var.set(f"Loading preview {done / total * 100:.1f}%")
        elif event_name == "preview_loaded":
            assert isinstance(payload, dict)
            preview = payload["preview"]
            paths = payload["paths"]
            assert isinstance(preview, PreviewData)
            assert isinstance(paths, list)
            self.current_paths = paths
            self.preview_data = preview
            self.loading_preview = False
            self.progress_var.set(0.0)
            self._set_controls_enabled(True)
            self.view_zoom = 1.0
            self.view_pan_x = 0.0
            self.view_pan_y = 0.0
            self._invalidate_preview_cache()
            self.crop_selection = None
            self.crop_points = []
            self.crop_hover_point = None
            self.grid_selection = None
            self.split_points = []
            self.drag_anchor = None
            self.drag_point = None
            self.drag_mode = None
            self.file_var.set(self._format_file_label(paths))
            self._sync_file_tree(paths)
            self.status_var.set(
                f"Loaded {len(paths)} file(s) with {preview.total_points:,} total points."
            )
            self.log(
                f"Preview loaded for {len(paths)} file(s): sampled "
                f"{len(preview.preview_points):,} / {preview.total_points:,} points."
            )
            self._update_mode_hint()
            self._draw_preview()
        elif event_name == "preview_error":
            paths, exc, detail = payload
            self.loading_preview = False
            self._set_controls_enabled(True)
            self.status_var.set("Preview failed to load")
            self.file_var.set(self._format_file_label(self.current_paths))
            self._sync_file_tree(self.current_paths)
            self.log(f"Failed to load preview: {paths} ({exc})")
            self.log(detail)
            messagebox.showerror("Preview Error", str(exc), parent=self)
        elif event_name == "export_parallel_started":
            assert isinstance(payload, dict)
            workers = payload["workers"]
            total_files = payload["total_files"]
            self.log(f"Parallel export: {workers} worker(s) for {total_files} file(s).")
        elif event_name == "export_progress":
            assert isinstance(payload, dict)
            done = payload["done"]
            total = payload["total"]
            if total:
                self.progress_var.set(done / total * 100)
                if not self.cancel_event.is_set():
                    self.status_var.set(f"Exporting {done / total * 100:.1f}%")
        elif event_name == "export_file_complete":
            assert isinstance(payload, dict)
            result = payload["result"]
            completed_files = payload["completed_files"]
            total_files = payload["total_files"]
            self._log_export_result(result)
            self.status_var.set(f"Completed {completed_files} / {total_files} file(s)")
        elif event_name == "export_batch_done":
            assert isinstance(payload, dict)
            mode = payload["mode"]
            results = payload["results"]
            self.processing = False
            self._set_controls_enabled(True)
            self.progress_var.set(0.0 if self.cancel_event.is_set() else 100.0)
            summary = self._summarize_results(results)
            self.status_var.set(f"{self._mode_label()} finished: {summary}")
            self.log(f"{self._mode_label()} finished: {summary}.")
            if mode == "grid":
                written = 0
                empty = 0
                for result in results:
                    assert isinstance(result, GridSplitResult)
                    written += sum(1 for part in result.parts if not part.empty)
                    empty += sum(1 for part in result.parts if part.empty)
                self.log(
                    f"Grid export summary: {written} partition file(s) written; "
                    f"{empty} empty partition(s)."
                )
        elif event_name == "export_error":
            exc, detail = payload
            self.processing = False
            self._set_controls_enabled(True)
            self.status_var.set("Export failed")
            self.log(f"Export failed: {exc}")
            self.log(detail)
            messagebox.showerror("Export Error", str(exc), parent=self)

    @staticmethod
    def _summarize_results(results: list) -> str:
        cancelled = sum(1 for result in results if isinstance(result, CancelledResult))
        results = [result for result in results if not isinstance(result, CancelledResult)]
        skipped = sum(1 for result in results if getattr(result, "skipped", False))
        empty = sum(
            1
            for result in results
            if not getattr(result, "skipped", False)
            and (
                getattr(result, "empty", False)
                or (
                    isinstance(result, SplitResult)
                    and result.empty_left
                    and result.empty_right
                )
                or (
                    isinstance(result, GridSplitResult)
                    and all(part.empty for part in result.parts)
                )
            )
        )
        written = len(results) - skipped - empty
        summary = f"{written} written, {skipped} skipped (output exists), {empty} produced no points"
        if cancelled:
            summary += f", {cancelled} cancelled"
        return summary

    def _log_export_result(self, result: object) -> None:
        if isinstance(result, CancelledResult):
            self.log(f"{result.input_path.name}: cancelled.")
            return

        if isinstance(result, CropResult):
            if result.skipped:
                self.log(f"{result.input_path.name}: {result.message}")
            elif result.empty:
                self.log(f"{result.input_path.name}: {result.message}")
            else:
                self.log(
                    f"{result.input_path.name}: {result.input_points:,} -> "
                    f"{result.output_points:,} points, saved as {result.output_path.name}"
                )
            return

        if isinstance(result, SplitResult):
            self.log(
                f"{result.input_path.name}: left={result.left_points:,}, "
                f"right={result.right_points:,}. {result.message}"
            )
            return

        if isinstance(result, GridSplitResult):
            self.log(f"{result.input_path.name}: {result.message}")

    def _on_mode_change(self) -> None:
        self.drag_anchor = None
        self.drag_point = None
        self.drag_mode = None
        self._update_mode_hint()
        self._update_grid_controls()
        self._draw_preview()

    def _update_mode_hint(self) -> None:
        mode = self.mode_var.get()
        if mode == "crop":
            self.hint_var.set(
                "Polygon crop: click to add vertices, double-click or click start to close. "
                "Scroll wheel to zoom, right-drag to pan."
            )
            if self.crop_selection is None:
                if self.crop_points:
                    self.status_var.set(f"Polygon crop: {len(self.crop_points)} vertices added.")
                else:
                    self.status_var.set("Polygon crop: click to add vertices; double-click to close.")
            else:
                self.status_var.set("Polygon selection ready. Click Export to continue.")
        elif mode == "split":
            self.hint_var.set(
                "Line split: click two points to define the line. "
                "Scroll wheel to zoom, right-drag to pan."
            )
            if not self.split_points:
                self.status_var.set("Line split: click the first point.")
            elif len(self.split_points) == 1:
                self.status_var.set("First point added. Click the second point.")
            else:
                self.status_var.set("Split line ready. Click Export to continue.")
        else:
            rows, cols = self._safe_grid_shape()
            label = f"{rows} x {cols}" if rows is not None and cols is not None else "current settings"
            self.hint_var.set(
                "Grid split: full bounds or drag rectangle. "
                "Scroll wheel to zoom, right-drag to pan."
            )
            if self.preview_data is None:
                self.status_var.set("Grid split: load files to preview and export partitions.")
            elif self.grid_selection is None:
                self.status_var.set(f"Grid split: the full bounds will be divided into {label}.")
            else:
                self.status_var.set(f"Grid area ready. Export will create {label} partitions.")

    def _update_grid_controls(self) -> None:
        if self.mode_var.get() == "grid":
            self.grid_controls.grid()
        else:
            self.grid_controls.grid_remove()

    def _set_grid_preset(self, rows: int, cols: int) -> None:
        self.grid_rows_var.set(str(rows))
        self.grid_cols_var.set(str(cols))

    def _on_grid_value_change(self, *_args) -> None:
        if self.mode_var.get() == "grid":
            self._update_mode_hint()
            self._draw_preview()

    def reset_view(self) -> None:
        if self.loading_preview or self.processing:
            return
        self.view_zoom = 1.0
        self.view_pan_x = 0.0
        self.view_pan_y = 0.0
        self._invalidate_preview_cache()
        self._draw_preview()

    def _on_edl_toggle(self) -> None:
        self._invalidate_preview_cache()
        self._draw_preview()

    def _on_canvas_wheel(self, event) -> None:
        if self.preview_data is None or self.loading_preview or self.processing:
            return
        if self.transform is None:
            return

        if hasattr(event, "delta") and event.delta != 0:
            zoom_in = event.delta > 0
        elif getattr(event, "num", None) == 4:
            zoom_in = True
        elif getattr(event, "num", None) == 5:
            zoom_in = False
        else:
            return

        factor = 1.15 if zoom_in else (1.0 / 1.15)
        new_zoom = float(np.clip(self.view_zoom * factor, 0.1, 100.0))
        actual_factor = new_zoom / self.view_zoom
        if abs(actual_factor - 1.0) < 1e-4:
            return

        cx = float(event.x)
        cy = float(event.y)

        eff_left = self.transform["plot_left"]
        eff_top = self.transform["plot_top"]
        base_left = self.transform["base_left"]
        base_top = self.transform["base_top"]

        new_eff_left = cx - (cx - eff_left) * actual_factor
        new_eff_top = cy - (cy - eff_top) * actual_factor

        self.view_zoom = new_zoom
        self.view_pan_x = float(new_eff_left - base_left)
        self.view_pan_y = float(new_eff_top - base_top)

        self._invalidate_preview_cache()
        self._draw_preview()

    def _on_canvas_pan_start(self, event) -> None:
        if self.preview_data is None or self.loading_preview or self.processing:
            return
        self.pan_start_x = float(event.x)
        self.pan_start_y = float(event.y)
        self.panning = True

    def _on_canvas_pan_move(self, event) -> None:
        if not self.panning or self.pan_start_x is None or self.pan_start_y is None:
            return
        dx = float(event.x) - self.pan_start_x
        dy = float(event.y) - self.pan_start_y
        self.pan_start_x = float(event.x)
        self.pan_start_y = float(event.y)
        self.view_pan_x += dx
        self.view_pan_y += dy
        self._invalidate_preview_cache()
        self._draw_preview()

    def _on_canvas_pan_end(self, _event) -> None:
        self.panning = False
        self.pan_start_x = None
        self.pan_start_y = None

    def _on_canvas_configure(self, _event) -> None:
        self._invalidate_preview_cache()
        self._draw_preview()

    def _on_canvas_motion(self, event) -> None:
        if self.preview_data is not None and not self.loading_preview:
            cursor = self._canvas_to_data(event.x, event.y)
            if cursor is not None:
                self.coord_var.set(f"X {cursor[0]:.3f}   Y {cursor[1]:.3f}")

        if (
            self.preview_data is None
            or self.loading_preview
            or self.processing
            or self.mode_var.get() != "crop"
            or self.crop_selection is not None
            or not self.crop_points
        ):
            return

        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        self.crop_hover_point = point
        self._draw_preview()

    def _on_canvas_press(self, event) -> None:
        if self.preview_data is None or self.loading_preview or self.processing:
            return

        mode = self.mode_var.get()

        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        if mode == "crop":
            self._handle_crop_click(event.x, event.y, point)
            return

        if mode != "grid":
            return

        self.drag_anchor = point
        self.drag_point = point
        self.drag_mode = mode
        self.status_var.set("Selecting area...")
        self._draw_preview()

    def _on_canvas_double_click(self, event) -> None:
        if (
            self.preview_data is None
            or self.loading_preview
            or self.processing
            or self.mode_var.get() != "crop"
        ):
            return

        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        if self.crop_selection is not None:
            self.crop_selection = None
            self.crop_points = []
        self._finish_crop_polygon(point)

    def _on_canvas_drag(self, event) -> None:
        if (
            self.preview_data is None
            or self.drag_anchor is None
            or self.drag_mode != "grid"
        ):
            return

        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        self.drag_point = point
        self._draw_preview()

    def _on_canvas_release(self, event) -> None:
        if self.preview_data is None or self.loading_preview or self.processing:
            return

        mode = self.mode_var.get()
        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        if mode == "grid" and self.drag_anchor is not None and self.drag_mode == mode:
            candidate = Bounds2D.from_points(self.drag_anchor, point)
            self.drag_anchor = None
            self.drag_point = None
            self.drag_mode = None

            if candidate.is_valid():
                self.grid_selection = candidate
                self.status_var.set("Grid area ready. Click Export to continue.")
            else:
                self.status_var.set("The selected area is too small. Drag a larger rectangle.")
            self._update_mode_hint()
            self._draw_preview()
            return

        if mode != "split":
            return

        if len(self.split_points) >= 2:
            self.split_points = [point]
            self.status_var.set("Split line reset. Click the second point.")
        else:
            self.split_points.append(point)
            if len(self.split_points) == 1:
                self.status_var.set("First point added. Click the second point.")
            else:
                selection = self._current_line_selection()
                if selection is not None and selection.is_valid():
                    self.status_var.set("Split line ready. Click Export to continue.")
                else:
                    self.split_points = []
                    self.status_var.set("The two points are too close. Try again.")
                    messagebox.showwarning(
                        "Invalid Split Line", "The two points are too close. Try again.", parent=self
                    )
        self._draw_preview()

    def _handle_crop_click(self, canvas_x: float, canvas_y: float, point: tuple[float, float]) -> None:
        if self.crop_selection is not None:
            self.crop_selection = None
            self.crop_points = [point]
            self.crop_hover_point = point
            self.status_var.set("Started a new polygon. Continue adding vertices.")
            self._draw_preview()
            return

        if len(self.crop_points) >= 3 and self._is_near_crop_start(canvas_x, canvas_y):
            self._finish_crop_polygon()
            return

        self.crop_points.append(point)
        self.crop_hover_point = point
        self.status_var.set(f"Added {len(self.crop_points)} polygon vertices.")
        self._draw_preview()

    def _finish_crop_polygon(self, point: tuple[float, float] | None = None) -> None:
        if point is not None and (not self.crop_points or point != self.crop_points[-1]):
            self.crop_points.append(point)

        if len(self.crop_points) < 3:
            self.status_var.set("A polygon needs at least three vertices.")
            self._draw_preview()
            return

        selection = PolygonSelection(points=tuple(self.crop_points))
        if selection.is_valid():
            self.crop_selection = selection
            self.crop_points = list(selection.points)
            self.crop_hover_point = None
            self.status_var.set("Polygon closed. Click Export to continue.")
        else:
            self.crop_selection = None
            self.status_var.set("The polygon is invalid. Draw it again.")
        self._draw_preview()

    def _is_near_crop_start(self, canvas_x: float, canvas_y: float) -> bool:
        if not self.crop_points:
            return False
        start_x, start_y = self._data_to_canvas(*self.crop_points[0])
        return (start_x - canvas_x) ** 2 + (start_y - canvas_y) ** 2 <= 64.0

    def _current_line_selection(self) -> LineSelection | None:
        if len(self.split_points) != 2:
            return None
        return LineSelection(
            x1=self.split_points[0][0],
            y1=self.split_points[0][1],
            x2=self.split_points[1][0],
            y2=self.split_points[1][1],
        )

    def _draw_preview(self) -> None:
        self.canvas.delete("all")

        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)

        if self.preview_data is None:
            self.canvas.create_text(
                width / 2,
                height / 2,
                text="Open or drop .las files to display a top-view preview.",
                fill="#5c7080",
            )
            return

        cache_key = (
            id(self.preview_data),
            width,
            height,
            round(self.view_zoom, 4),
            round(self.view_pan_x, 1),
            round(self.view_pan_y, 1),
            self.edl_var.get(),
        )
        if self.preview_cache_key != cache_key:
            self.transform = self._compute_transform(width, height, self.preview_data.bounds)
            self.preview_photo = self._build_preview_image(width, height)
            self.preview_cache_key = cache_key

        if self.preview_photo is not None:
            self.canvas.create_image(0, 0, anchor="nw", image=self.preview_photo)

        self._draw_overlays()

    def _invalidate_preview_cache(self) -> None:
        self.preview_photo = None
        self.preview_cache_key = None
        self.transform = None

    def _compute_transform(self, width: int, height: int, bounds: Bounds2D) -> dict[str, float]:
        data_width = max(bounds.max_x - bounds.min_x, 1e-9)
        data_height = max(bounds.max_y - bounds.min_y, 1e-9)
        plot_width = max(width - self.PREVIEW_PADDING * 2, 1)
        plot_height = max(height - self.PREVIEW_PADDING * 2, 1)
        base_scale = min(plot_width / data_width, plot_height / data_height)
        used_width = data_width * base_scale
        used_height = data_height * base_scale
        base_left = (width - used_width) / 2
        base_top = (height - used_height) / 2

        scale = base_scale * self.view_zoom
        plot_left = base_left + self.view_pan_x
        plot_top = base_top + self.view_pan_y

        return {
            "min_x": bounds.min_x,
            "max_y": bounds.max_y,
            "scale": scale,
            "plot_left": plot_left,
            "plot_top": plot_top,
            "max_x": bounds.max_x,
            "min_y": bounds.min_y,
            "base_scale": base_scale,
            "base_left": base_left,
            "base_top": base_top,
        }

    def _build_preview_image(self, width: int, height: int) -> tk.PhotoImage:
        assert self.preview_data is not None
        assert self.transform is not None

        image = np.empty((height, width, 3), dtype=np.uint8)
        image[:, :] = self.PREVIEW_BACKGROUND

        points = self.preview_data.preview_points
        colors = self.preview_data.preview_colors
        z_vals = getattr(self.preview_data, "preview_z", None)
        enable_edl = (
            self.edl_var.get()
            and z_vals is not None
            and len(z_vals) == len(points)
            and len(points) > 0
        )

        if points.size:
            xs, ys = self._data_to_canvas_arrays(points[:, 0], points[:, 1])
            visible = (xs >= -1) & (xs < width) & (ys >= -1) & (ys < height)
            if np.any(visible):
                xi = np.rint(xs[visible]).astype(np.int64)
                yi = np.rint(ys[visible]).astype(np.int64)
                cols = colors[visible]

                if enable_edl:
                    zv = z_vals[visible]
                    order = np.argsort(zv)
                    xi = xi[order]
                    yi = yi[order]
                    cols = cols[order]
                    zv = zv[order]
                    z_buffer = np.full((height, width), -1e9, dtype=np.float32)

                for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    cx = xi + dx
                    cy = yi + dy
                    in_bounds = (cx >= 0) & (cx < width) & (cy >= 0) & (cy < height)
                    bx = cx[in_bounds]
                    by = cy[in_bounds]
                    image[by, bx] = cols[in_bounds]
                    if enable_edl:
                        z_buffer[by, bx] = zv[in_bounds]

                if enable_edl:
                    self._apply_edl_shading(image, z_buffer, width, height)

        ppm_header = f"P6 {width} {height} 255\n".encode("ascii")
        ppm_bytes = ppm_header + image.tobytes()
        return tk.PhotoImage(data=ppm_bytes, format="PPM")

    @staticmethod
    def _apply_edl_shading(
        image: np.ndarray,
        z_buffer: np.ndarray,
        width: int,
        height: int,
    ) -> None:
        valid_mask = z_buffer > -1e8
        if not np.any(valid_mask):
            return

        valid_z = z_buffer[valid_mask]
        z_min = float(np.min(valid_z))
        z_max = float(np.max(valid_z))
        z_range = max(z_max - z_min, 1e-6)

        depth = np.ones((height, width), dtype=np.float32)
        depth[valid_mask] = (z_max - valid_z) / z_range

        d_pad = np.pad(depth, 1, mode="edge")
        dc = d_pad[1:-1, 1:-1]

        response = np.zeros((height, width), dtype=np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            dn = d_pad[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
            diff = np.maximum(0.0, dn - dc)
            diff += np.maximum(0.0, dc - dn) * 0.25
            response += diff

        edl_strength = 8.0
        shade = np.exp(-response * edl_strength)
        np.clip(shade, 0.25, 1.0, out=shade)

        shade_u16 = (shade[valid_mask, None] * 256).astype(np.uint16)
        image[valid_mask] = (
            (image[valid_mask].astype(np.uint16) * shade_u16) >> 8
        ).astype(np.uint8)

    def _draw_overlays(self) -> None:
        mode = self.mode_var.get()

        if mode == "crop":
            self._draw_crop_overlay()
        elif mode == "split":
            self._draw_line_overlay()
        else:
            bounds = self._active_grid_bounds()
            if bounds is not None:
                self._draw_bounds_outline(bounds, outline="#2563eb")
                self._draw_grid_overlay(bounds)

    def _draw_bounds_outline(self, bounds: Bounds2D, *, outline: str) -> None:
        left, top = self._data_to_canvas(bounds.min_x, bounds.max_y)
        right, bottom = self._data_to_canvas(bounds.max_x, bounds.min_y)
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline=outline,
            width=2,
            dash=(6, 4),
        )

    def _draw_crop_overlay(self) -> None:
        points = self.crop_points if self.crop_points else []
        if self.crop_selection is not None:
            points = list(self.crop_selection.points)

        if not points:
            return

        canvas_points = [self._data_to_canvas(x, y) for x, y in points]
        flat_points = [value for point in canvas_points for value in point]

        if len(canvas_points) >= 2:
            self.canvas.create_line(*flat_points, fill="#0f766e", width=2)

        if self.crop_selection is not None and len(canvas_points) >= 3:
            self.canvas.create_polygon(
                *flat_points,
                outline="#0f766e",
                fill="",
                width=2,
            )
        elif self.crop_hover_point is not None:
            hover_x, hover_y = self._data_to_canvas(*self.crop_hover_point)
            last_x, last_y = canvas_points[-1]
            self.canvas.create_line(last_x, last_y, hover_x, hover_y, fill="#0f766e", dash=(4, 4), width=1)

        for index, (x, y) in enumerate(canvas_points):
            radius = 4 if index else 5
            color = "#0f766e" if index else "#b45309"
            self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="")

    def _draw_line_overlay(self) -> None:
        if self.split_points:
            x1, y1 = self._data_to_canvas(*self.split_points[0])
            self.canvas.create_oval(x1 - 4, y1 - 4, x1 + 4, y1 + 4, fill="#b45309", outline="")
        if len(self.split_points) == 2:
            x1, y1 = self._data_to_canvas(*self.split_points[0])
            x2, y2 = self._data_to_canvas(*self.split_points[1])
            self.canvas.create_line(x1, y1, x2, y2, fill="#b45309", width=2, dash=(8, 4))
            self.canvas.create_oval(x2 - 4, y2 - 4, x2 + 4, y2 + 4, fill="#b45309", outline="")

    def _draw_grid_overlay(self, bounds: Bounds2D) -> None:
        rows, cols = self._safe_grid_shape()
        if rows is None or cols is None or rows <= 0 or cols <= 0:
            return

        width = bounds.max_x - bounds.min_x
        height = bounds.max_y - bounds.min_y
        if width <= 0 or height <= 0:
            return

        cell_width = width / cols
        cell_height = height / rows
        line_color = "#2563eb"
        label_color = "#0f172a"
        shadow_color = "#f8fafc"

        for col in range(1, cols):
            x = bounds.min_x + cell_width * col
            x1, y1 = self._data_to_canvas(x, bounds.max_y)
            x2, y2 = self._data_to_canvas(x, bounds.min_y)
            self.canvas.create_line(x1, y1, x2, y2, fill=line_color, dash=(4, 4), width=1)

        for row in range(1, rows):
            y = bounds.min_y + cell_height * row
            x1, y1 = self._data_to_canvas(bounds.min_x, y)
            x2, y2 = self._data_to_canvas(bounds.max_x, y)
            self.canvas.create_line(x1, y1, x2, y2, fill=line_color, dash=(4, 4), width=1)

        label_number = 1
        for row in range(rows):
            y_top = bounds.max_y - row * cell_height
            y_bottom = y_top - cell_height
            for col in range(cols):
                x_left = bounds.min_x + col * cell_width
                x_right = x_left + cell_width
                center_x = (x_left + x_right) / 2
                center_y = (y_top + y_bottom) / 2
                canvas_x, canvas_y = self._data_to_canvas(center_x, center_y)
                self._draw_shadow_text(canvas_x, canvas_y, f"p{label_number}", label_color, shadow_color)
                label_number += 1

    def _draw_shadow_text(
        self,
        x: float,
        y: float,
        text: str,
        fill: str,
        shadow_fill: str,
    ) -> None:
        self.canvas.create_text(x + 1, y + 1, text=text, fill=shadow_fill, font=("Segoe UI", 11, "bold"))
        self.canvas.create_text(x, y, text=text, fill=fill, font=("Segoe UI", 11, "bold"))

    def _active_grid_bounds(self) -> Bounds2D | None:
        if self.preview_data is None:
            return None
        if self.drag_mode == "grid" and self.drag_anchor is not None and self.drag_point is not None:
            return Bounds2D.from_points(self.drag_anchor, self.drag_point)
        if self.grid_selection is not None:
            return self.grid_selection
        return self.preview_data.bounds

    def _grid_bounds_for_export(self) -> Bounds2D:
        bounds = self._active_grid_bounds()
        if bounds is None or not bounds.is_valid():
            raise ValueError("The grid area is invalid.")
        return bounds

    def _data_to_canvas_arrays(self, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        assert self.transform is not None
        scale = self.transform["scale"]
        canvas_x = self.transform["plot_left"] + (xs - self.transform["min_x"]) * scale
        canvas_y = self.transform["plot_top"] + (self.transform["max_y"] - ys) * scale
        return canvas_x, canvas_y

    def _data_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        xs, ys = self._data_to_canvas_arrays(np.asarray([x]), np.asarray([y]))
        return float(xs[0]), float(ys[0])

    def _canvas_to_data(self, canvas_x: float, canvas_y: float) -> tuple[float, float] | None:
        if self.transform is None:
            return None

        scale = self.transform["scale"]
        if scale <= 0:
            return None

        x = self.transform["min_x"] + (canvas_x - self.transform["plot_left"]) / scale
        y = self.transform["max_y"] - (canvas_y - self.transform["plot_top"]) / scale
        x = min(max(x, self.transform["min_x"]), self.transform["max_x"])
        y = min(max(y, self.transform["min_y"]), self.transform["max_y"])
        return (x, y)

    def _get_grid_shape(self) -> tuple[int, int]:
        try:
            rows = int(self.grid_rows_var.get())
            cols = int(self.grid_cols_var.get())
        except ValueError as exc:
            raise ValueError("Rows and columns must be integers.") from exc

        if rows <= 0 or cols <= 0:
            raise ValueError("Rows and columns must be greater than 0.")
        if rows * cols > 64:
            raise ValueError("The number of grid partitions cannot exceed 64.")
        return rows, cols

    def _safe_grid_shape(self) -> tuple[int | None, int | None]:
        try:
            return self._get_grid_shape()
        except ValueError:
            return (None, None)

    def _mode_label(self) -> str:
        mode = self.mode_var.get()
        if mode == "crop":
            return "Polygon crop"
        if mode == "split":
            return "Line split"
        return "Grid split"


class CloudTrimApp:
    def __init__(self) -> None:
        root_class = TkinterDnD.Tk if HAS_DND else tk.Tk
        self.root = root_class()
        self.root.title("CloudTrim - Point Cloud Batch Processor")
        icon_path = Path(__file__).resolve().parent / "assets" / "cloudtrim.ico"
        try:
            self.root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass  # The icon is cosmetic; keep running without it.
        self.root.geometry("1180x820")
        self.root.minsize(900, 620)

        style = ttk.Style(self.root)
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 6))

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)

        self.downsample_page = DownsamplePage(notebook)
        self.split_crop_page = SplitCropPage(notebook)

        notebook.add(self.downsample_page, text="Batch Downsample")
        notebook.add(self.split_crop_page, text="Split / Crop")

    def run(self) -> None:
        self.root.mainloop()


def run_app() -> None:
    CloudTrimApp().run()
