from __future__ import annotations

import base64
import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import numpy as np

from .downsample import DownsampleResult, downsample_las, validate_resolution
from .split_crop import (
    Bounds2D,
    CropResult,
    LineSelection,
    PreviewData,
    SplitResult,
    crop_las,
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
    status: str = "待处理"


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

        self.resolution_var = tk.StringVar(value="0.2")
        self.status_var = tk.StringVar(value="准备就绪")
        self.drag_hint_var = tk.StringVar(
            value="可将 .las 文件拖入列表" if HAS_DND else "未检测到拖拽依赖，可用“添加文件”导入"
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

        ttk.Label(top, text="分辨率 (m)").grid(row=0, column=0, sticky="w")
        self.resolution_entry = ttk.Entry(top, textvariable=self.resolution_var, width=12)
        self.resolution_entry.grid(row=0, column=1, padx=(8, 16), sticky="w")

        self.add_button = ttk.Button(top, text="添加文件", command=self.add_files)
        self.add_button.grid(row=0, column=2, padx=(0, 8))

        self.remove_button = ttk.Button(top, text="移除选中", command=self.remove_selected)
        self.remove_button.grid(row=0, column=3, padx=(0, 8))

        self.clear_button = ttk.Button(top, text="清空列表", command=self.clear_files)
        self.clear_button.grid(row=0, column=4, padx=(0, 8))

        self.start_button = ttk.Button(top, text="开始处理", command=self.start_processing)
        self.start_button.grid(row=0, column=5, sticky="e")

        ttk.Label(top, textvariable=self.drag_hint_var, foreground="#4f6b7a").grid(
            row=1, column=0, columnspan=6, sticky="w", pady=(8, 0)
        )

        table_frame = ttk.Frame(self, padding=(12, 0, 12, 12))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("name", "folder", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("name", text="文件名")
        self.tree.heading("folder", text="所在目录")
        self.tree.heading("status", text="状态")
        self.tree.column("name", width=260, anchor="w")
        self.tree.column("folder", width=460, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        log_frame = ttk.LabelFrame(self, text="运行日志", padding=12)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="groove", padding=8)
        status_bar.grid(row=3, column=0, sticky="ew")

    def _configure_drop(self) -> None:
        if not HAS_DND:
            self.log("未安装 tkinterdnd2，拖拽暂不可用，可通过“添加文件”选择 .las 文件。")
            return

        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self._on_drop)
        self.log("拖拽已启用，可将多个 .las 文件直接拖入列表。")

    def _on_drop(self, event) -> None:
        paths = [Path(item) for item in self.winfo_toplevel().tk.splitlist(event.data)]
        self._add_paths(paths)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择 LAS 文件",
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
                self.log(f"已忽略非 LAS 文件: {path}")
                continue

            normalized = str(path.resolve())
            if normalized in self.files:
                continue

            self.files[normalized] = FileItem(path=path)
            self.tree.insert(
                "",
                "end",
                iid=normalized,
                values=(path.name, str(path.parent), "待处理"),
            )
            added += 1

        if added:
            self.status_var.set(f"已加入 {added} 个文件")
            self.log(f"已加入 {added} 个 LAS 文件。")

    def remove_selected(self) -> None:
        if self.processing:
            return

        for item_id in self.tree.selection():
            self.tree.delete(item_id)
            self.files.pop(item_id, None)

        self.status_var.set(f"当前列表 {len(self.files)} 个文件")

    def clear_files(self) -> None:
        if self.processing:
            return

        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.files.clear()
        self.status_var.set("列表已清空")

    def start_processing(self) -> None:
        if self.processing:
            return

        if not self.files:
            messagebox.showwarning("没有文件", "请先加入至少一个 .las 文件。", parent=self)
            return

        try:
            resolution = validate_resolution(self.resolution_var.get())
        except ValueError as exc:
            messagebox.showerror("分辨率无效", str(exc), parent=self)
            return

        self.processing = True
        self._set_controls_enabled(False)
        self.status_var.set("处理中...")
        self.log(f"开始批量降采样，分辨率 {resolution} m。")

        for item_id in self.tree.get_children():
            self.tree.set(item_id, "status", "排队中")

        file_paths = [item.path for item in self.files.values()]
        self.worker_thread = threading.Thread(
            target=self._worker_run,
            args=(file_paths, resolution),
            daemon=True,
        )
        self.worker_thread.start()

    def _worker_run(self, file_paths: list[Path], resolution: float) -> None:
        completed = 0
        total_files = len(file_paths)

        for input_path in file_paths:
            item_id = str(input_path.resolve())
            self.event_queue.put(("file_status", {"item_id": item_id, "status": "处理中"}))
            self.event_queue.put(("log", {"message": f"开始处理 {input_path}"}))

            try:
                result = downsample_las(
                    input_path,
                    resolution,
                    progress_callback=lambda done, total, item_id=item_id: self.event_queue.put(
                        ("progress", {"item_id": item_id, "done": done, "total": total})
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                message = f"{input_path.name} 失败: {exc}"
                self.event_queue.put(("file_status", {"item_id": item_id, "status": "失败"}))
                self.event_queue.put(("log", {"message": message}))
                self.event_queue.put(("log", {"message": traceback.format_exc(limit=3)}))
            else:
                if result.skipped:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "跳过"}))
                    self.event_queue.put(("log", {"message": f"{input_path.name}: {result.message}"}))
                else:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "成功"}))
                    self.event_queue.put(("log", {"message": self._format_result_message(result)}))

            completed += 1
            self.event_queue.put(
                ("batch_progress", {"completed": completed, "total_files": total_files})
            )

        self.event_queue.put(("done", {}))

    @staticmethod
    def _format_result_message(result: DownsampleResult) -> str:
        return (
            f"{result.input_path.name}: {result.input_points:,} -> {result.output_points:,} 点，"
            f"输出 {result.output_path.name}"
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
        elif event_name == "progress":
            done = payload["done"]
            total = payload["total"]
            if total:
                percent = done / total * 100
                self.status_var.set(f"处理中 {percent:.1f}%")
        elif event_name == "batch_progress":
            self.status_var.set(f"已完成 {payload['completed']} / {payload['total_files']} 个文件")
        elif event_name == "log":
            self.log(payload["message"])
        elif event_name == "done":
            self.processing = False
            self._set_controls_enabled(True)
            self.status_var.set("全部处理完成")
            self.log("全部任务完成。")


class SplitCropPage(ttk.Frame, LogMixin):
    PREVIEW_LIMIT = 100_000
    PREVIEW_PADDING = 24
    PREVIEW_BACKGROUND = np.array([248, 250, 252], dtype=np.uint8)
    PREVIEW_POINT_COLOR = np.array([38, 57, 77], dtype=np.uint8)

    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent, padding=0)

        self.current_path: Path | None = None
        self.preview_data: PreviewData | None = None
        self.mode_var = tk.StringVar(value="crop")
        self.file_var = tk.StringVar(value="未加载文件")
        self.hint_var = tk.StringVar(value="框选模式：在预览中拖拽一个矩形区域。")
        self.status_var = tk.StringVar(value="打开一个 .las 文件后，就可以在顶视图中框选或划线。")

        self.loading_preview = False
        self.processing = False
        self.event_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self.crop_selection: Bounds2D | None = None
        self.crop_anchor: tuple[float, float] | None = None
        self.crop_drag_point: tuple[float, float] | None = None
        self.split_points: list[tuple[float, float]] = []

        self.preview_photo: tk.PhotoImage | None = None
        self.preview_cache_key: tuple[int, int, int] | None = None
        self.transform: dict[str, float] | None = None

        self._build_layout()
        self.after(100, self._drain_events)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(7, weight=1)

        self.open_button = ttk.Button(top, text="打开 LAS", command=self.open_file)
        self.open_button.grid(row=0, column=0, padx=(0, 8))

        self.crop_radio = ttk.Radiobutton(
            top,
            text="框选裁剪",
            variable=self.mode_var,
            value="crop",
            command=self._on_mode_change,
        )
        self.crop_radio.grid(row=0, column=1, padx=(0, 8))

        self.split_radio = ttk.Radiobutton(
            top,
            text="直线分割",
            variable=self.mode_var,
            value="split",
            command=self._on_mode_change,
        )
        self.split_radio.grid(row=0, column=2, padx=(0, 8))

        self.clear_selection_button = ttk.Button(top, text="清除选区", command=self.clear_selection)
        self.clear_selection_button.grid(row=0, column=3, padx=(0, 8))

        self.export_button = ttk.Button(top, text="执行导出", command=self.start_export)
        self.export_button.grid(row=0, column=4, padx=(0, 8))

        ttk.Label(top, text="当前文件:").grid(row=0, column=5, padx=(16, 8), sticky="w")
        ttk.Label(top, textvariable=self.file_var).grid(row=0, column=6, columnspan=2, sticky="w")

        ttk.Label(top, textvariable=self.hint_var, foreground="#4f6b7a").grid(
            row=1, column=0, columnspan=8, sticky="w", pady=(8, 0)
        )

        preview_frame = ttk.LabelFrame(self, text="俯视预览", padding=12)
        preview_frame.grid(row=1, column=0, sticky="nsew", padx=12)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            preview_frame,
            background="#f8fafc",
            highlightthickness=1,
            highlightbackground="#d3dde5",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

        log_frame = ttk.LabelFrame(self, text="运行日志", padding=12)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=12)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="groove", padding=8)
        status_bar.grid(row=3, column=0, sticky="ew")

    def open_file(self) -> None:
        if self.loading_preview or self.processing:
            return

        path = filedialog.askopenfilename(
            title="选择 LAS 文件",
            filetypes=[("LAS files", "*.las")],
            parent=self,
        )
        if path:
            self._start_preview_load(Path(path))

    def _start_preview_load(self, path: Path) -> None:
        self.loading_preview = True
        self._set_controls_enabled(False)
        self.status_var.set("正在加载预览...")
        self.file_var.set(str(path))
        self.log(f"开始加载预览: {path}")

        thread = threading.Thread(target=self._load_preview_worker, args=(path,), daemon=True)
        thread.start()

    def _load_preview_worker(self, path: Path) -> None:
        try:
            preview = load_preview_data(path, max_points=self.PREVIEW_LIMIT)
        except Exception as exc:  # noqa: BLE001
            self.event_queue.put(("preview_error", (path, exc, traceback.format_exc(limit=3))))
        else:
            self.event_queue.put(("preview_loaded", preview))

    def clear_selection(self) -> None:
        if self.loading_preview or self.processing:
            return

        self.crop_selection = None
        self.crop_anchor = None
        self.crop_drag_point = None
        self.split_points = []
        self._update_mode_hint()
        self._draw_preview()

    def start_export(self) -> None:
        if self.loading_preview or self.processing:
            return

        if self.preview_data is None or self.current_path is None:
            messagebox.showwarning("没有文件", "请先打开一个 .las 文件。", parent=self)
            return

        if self.mode_var.get() == "crop":
            selection = self.crop_selection
            if selection is None or not selection.is_valid():
                messagebox.showwarning("缺少选区", "请先拖拽一个有效矩形。", parent=self)
                return
            worker = threading.Thread(target=self._crop_worker, args=(self.current_path, selection), daemon=True)
        else:
            selection = self._current_line_selection()
            if selection is None or not selection.is_valid():
                messagebox.showwarning("缺少切分线", "请先点击两个点形成切分线。", parent=self)
                return
            worker = threading.Thread(target=self._split_worker, args=(self.current_path, selection), daemon=True)

        self.processing = True
        self._set_controls_enabled(False)
        self.status_var.set("正在导出...")
        self.log(f"开始执行 {self._mode_label()}。")
        worker.start()

    def _crop_worker(self, path: Path, selection: Bounds2D) -> None:
        try:
            result = crop_las(
                path,
                selection,
                progress_callback=lambda done, total: self.event_queue.put(
                    ("export_progress", {"done": done, "total": total})
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.event_queue.put(("export_error", (exc, traceback.format_exc(limit=3))))
        else:
            self.event_queue.put(("crop_done", result))

    def _split_worker(self, path: Path, selection: LineSelection) -> None:
        try:
            result = split_las(
                path,
                selection,
                progress_callback=lambda done, total: self.event_queue.put(
                    ("export_progress", {"done": done, "total": total})
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.event_queue.put(("export_error", (exc, traceback.format_exc(limit=3))))
        else:
            self.event_queue.put(("split_done", result))

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.open_button,
            self.crop_radio,
            self.split_radio,
            self.clear_selection_button,
            self.export_button,
        ):
            widget.configure(state=state)

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
        if event_name == "preview_loaded":
            preview = payload
            assert isinstance(preview, PreviewData)
            self.current_path = preview.input_path
            self.preview_data = preview
            self.loading_preview = False
            self._set_controls_enabled(True)
            self._invalidate_preview_cache()
            self.clear_selection()
            self.status_var.set(
                f"已加载 {preview.input_path.name}，原始点数 {preview.total_points:,}，可以开始操作。"
            )
            self.log(
                f"预览已加载: {preview.input_path.name}，预览采样 {len(preview.preview_points):,} / {preview.total_points:,} 点。"
            )
            self._draw_preview()
        elif event_name == "preview_error":
            path, exc, detail = payload
            self.loading_preview = False
            self._set_controls_enabled(True)
            self.status_var.set("预览加载失败")
            self.log(f"加载预览失败: {path} ({exc})")
            self.log(detail)
            messagebox.showerror("加载失败", str(exc), parent=self)
        elif event_name == "export_progress":
            assert isinstance(payload, dict)
            done = payload["done"]
            total = payload["total"]
            if total:
                self.status_var.set(f"正在导出 {done / total * 100:.1f}%")
        elif event_name == "crop_done":
            result = payload
            assert isinstance(result, CropResult)
            self.processing = False
            self._set_controls_enabled(True)
            if result.skipped:
                self.status_var.set("输出已存在，已跳过")
                self.log(result.message)
            elif result.empty:
                self.status_var.set("选区内没有点")
                self.log(result.message)
                messagebox.showinfo("空选区", result.message, parent=self)
            else:
                self.status_var.set("裁剪导出完成")
                self.log(
                    f"{result.input_path.name}: {result.input_points:,} -> {result.output_points:,} 点，输出 {result.output_path.name}"
                )
        elif event_name == "split_done":
            result = payload
            assert isinstance(result, SplitResult)
            self.processing = False
            self._set_controls_enabled(True)
            if result.skipped:
                self.status_var.set("输出已存在，已跳过")
                self.log(result.message)
            else:
                self.status_var.set("分割导出完成")
                self.log(
                    f"{result.input_path.name}: left={result.left_points:,}, right={result.right_points:,}。{result.message}"
                )
                if result.empty_left or result.empty_right:
                    messagebox.showinfo("分割结果", result.message, parent=self)
        elif event_name == "export_error":
            exc, detail = payload
            self.processing = False
            self._set_controls_enabled(True)
            self.status_var.set("导出失败")
            self.log(f"导出失败: {exc}")
            self.log(detail)
            messagebox.showerror("导出失败", str(exc), parent=self)

    def _on_mode_change(self) -> None:
        self.clear_selection()

    def _update_mode_hint(self) -> None:
        if self.mode_var.get() == "crop":
            self.hint_var.set("框选模式：在预览中拖拽一个矩形区域。")
            if self.crop_selection is None:
                self.status_var.set("框选模式：拖拽矩形后导出框内点云。")
            else:
                self.status_var.set("矩形选区已就绪，可执行导出。")
        else:
            self.hint_var.set("直线分割模式：点击两个点，按第一点到第二点的方向区分左右侧。")
            if not self.split_points:
                self.status_var.set("直线分割模式：点击第一个点。")
            elif len(self.split_points) == 1:
                self.status_var.set("已记录第一个点，请点击第二个点。")
            else:
                self.status_var.set("切分线已就绪，可执行导出。")

    def _on_canvas_configure(self, _event) -> None:
        self._invalidate_preview_cache()
        self._draw_preview()

    def _on_canvas_press(self, event) -> None:
        if self.preview_data is None or self.loading_preview or self.processing:
            return
        if self.mode_var.get() != "crop":
            return

        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        self.crop_anchor = point
        self.crop_drag_point = point
        self.crop_selection = None
        self.status_var.set("正在框选...")
        self._draw_preview()

    def _on_canvas_drag(self, event) -> None:
        if self.preview_data is None or self.mode_var.get() != "crop" or self.crop_anchor is None:
            return

        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        self.crop_drag_point = point
        self._draw_preview()

    def _on_canvas_release(self, event) -> None:
        if self.preview_data is None or self.loading_preview or self.processing:
            return

        point = self._canvas_to_data(event.x, event.y)
        if point is None:
            return

        if self.mode_var.get() == "crop":
            if self.crop_anchor is None:
                return
            candidate = Bounds2D.from_points(self.crop_anchor, point)
            self.crop_anchor = None
            self.crop_drag_point = None
            if candidate.is_valid():
                self.crop_selection = candidate
                self.status_var.set("矩形选区已就绪，可执行导出。")
            else:
                self.crop_selection = None
                self.status_var.set("选区太小，请重新拖拽一个矩形。")
            self._draw_preview()
            return

        if len(self.split_points) >= 2:
            self.split_points = [point]
            self.status_var.set("已重置切分线，请点击第二个点。")
        else:
            self.split_points.append(point)
            if len(self.split_points) == 1:
                self.status_var.set("已记录第一个点，请点击第二个点。")
            else:
                selection = self._current_line_selection()
                if selection is not None and selection.is_valid():
                    self.status_var.set("切分线已就绪，可执行导出。")
                else:
                    self.split_points = []
                    self.status_var.set("两个点过于接近，请重新选择。")
                    messagebox.showwarning("切分线无效", "两个点过于接近，请重新选择。", parent=self)
        self._draw_preview()

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
                text="打开一个 .las 文件后，这里会显示俯视预览。",
                fill="#5c7080",
            )
            return

        cache_key = (id(self.preview_data), width, height)
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
        scale = min(plot_width / data_width, plot_height / data_height)
        used_width = data_width * scale
        used_height = data_height * scale
        plot_left = (width - used_width) / 2
        plot_top = (height - used_height) / 2

        return {
            "min_x": bounds.min_x,
            "max_y": bounds.max_y,
            "scale": scale,
            "plot_left": plot_left,
            "plot_top": plot_top,
            "max_x": bounds.max_x,
            "min_y": bounds.min_y,
        }

    def _build_preview_image(self, width: int, height: int) -> tk.PhotoImage:
        assert self.preview_data is not None
        assert self.transform is not None

        image = np.empty((height, width, 3), dtype=np.uint8)
        image[:, :] = self.PREVIEW_BACKGROUND

        points = self.preview_data.preview_points
        if points.size:
            xs, ys = self._data_to_canvas_arrays(points[:, 0], points[:, 1])
            xi = np.clip(np.rint(xs).astype(np.int64), 0, width - 1)
            yi = np.clip(np.rint(ys).astype(np.int64), 0, height - 1)
            image[yi, xi] = self.PREVIEW_POINT_COLOR

            for dx, dy in ((1, 0), (0, 1)):
                nx = np.clip(xi + dx, 0, width - 1)
                ny = np.clip(yi + dy, 0, height - 1)
                image[ny, nx] = self.PREVIEW_POINT_COLOR

        ppm_header = f"P6 {width} {height} 255\n".encode("ascii")
        ppm_bytes = ppm_header + image.tobytes()
        encoded = base64.b64encode(ppm_bytes).decode("ascii")
        return tk.PhotoImage(data=encoded, format="PPM")

    def _draw_overlays(self) -> None:
        preview_bounds = self._active_crop_bounds()
        if preview_bounds is not None:
            left, top = self._data_to_canvas(preview_bounds.min_x, preview_bounds.max_y)
            right, bottom = self._data_to_canvas(preview_bounds.max_x, preview_bounds.min_y)
            self.canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline="#0f766e",
                width=2,
                dash=(6, 4),
            )

        if self.mode_var.get() == "split":
            if self.split_points:
                x1, y1 = self._data_to_canvas(*self.split_points[0])
                self.canvas.create_oval(x1 - 4, y1 - 4, x1 + 4, y1 + 4, fill="#b45309", outline="")
            if len(self.split_points) == 2:
                x1, y1 = self._data_to_canvas(*self.split_points[0])
                x2, y2 = self._data_to_canvas(*self.split_points[1])
                self.canvas.create_line(x1, y1, x2, y2, fill="#b45309", width=2, dash=(8, 4))
                self.canvas.create_oval(x2 - 4, y2 - 4, x2 + 4, y2 + 4, fill="#b45309", outline="")

    def _active_crop_bounds(self) -> Bounds2D | None:
        if self.crop_anchor is not None and self.crop_drag_point is not None:
            return Bounds2D.from_points(self.crop_anchor, self.crop_drag_point)
        return self.crop_selection

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

    def _mode_label(self) -> str:
        return "框选裁剪" if self.mode_var.get() == "crop" else "直线分割"


class LasToolApp:
    def __init__(self) -> None:
        root_class = TkinterDnD.Tk if HAS_DND else tk.Tk
        self.root = root_class()
        self.root.title("LAS 点云预处理工具")
        self.root.geometry("1100x760")
        self.root.minsize(860, 600)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)

        self.downsample_page = DownsamplePage(notebook)
        self.split_crop_page = SplitCropPage(notebook)

        notebook.add(self.downsample_page, text="批量降采样")
        notebook.add(self.split_crop_page, text="分割 / 裁剪")

    def run(self) -> None:
        self.root.mainloop()


def run_app() -> None:
    LasToolApp().run()
