from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from .downsample import DownsampleResult, downsample_las, validate_resolution

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


class LasToolApp:
    def __init__(self) -> None:
        root_class = TkinterDnD.Tk if HAS_DND else tk.Tk
        self.root = root_class()
        self.root.title("LAS 批量降采样工具")
        self.root.geometry("920x620")
        self.root.minsize(760, 480)

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
        self.root.after(100, self._drain_events)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)

        top = ttk.Frame(self.root, padding=12)
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

        table_frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
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

        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=12)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        status_bar = ttk.Label(self.root, textvariable=self.status_var, anchor="w", relief="groove", padding=8)
        status_bar.grid(row=3, column=0, sticky="ew")

    def _configure_drop(self) -> None:
        if not HAS_DND:
            self.log("未安装 tkinterdnd2，拖拽暂不可用，可先通过“添加文件”选择 .las 文件。")
            return

        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self._on_drop)
        self.log("拖拽已启用，可将多个 .las 文件直接拖入上方列表。")

    def _on_drop(self, event) -> None:
        paths = [Path(item) for item in self.root.tk.splitlist(event.data)]
        self._add_paths(paths)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择 LAS 文件",
            filetypes=[("LAS files", "*.las")],
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
            messagebox.showwarning("没有文件", "请先加入至少一个 .las 文件。")
            return

        try:
            resolution = validate_resolution(self.resolution_var.get())
        except ValueError as exc:
            messagebox.showerror("分辨率无效", str(exc))
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
            self.event_queue.put(("log", {"message": f"开始处理: {input_path}"}))

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
                self.event_queue.put(
                    (
                        "log",
                        {
                            "message": traceback.format_exc(limit=3),
                        },
                    )
                )
            else:
                if result.skipped:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "跳过"}))
                    self.event_queue.put(("log", {"message": f"{input_path.name}: {result.message}"}))
                else:
                    self.event_queue.put(("file_status", {"item_id": item_id, "status": "成功"}))
                    self.event_queue.put(("log", {"message": self._format_result_message(result)}))

            completed += 1
            self.event_queue.put(
                (
                    "batch_progress",
                    {"completed": completed, "total_files": total_files},
                )
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
            self.root.after(100, self._drain_events)

    def _handle_event(self, event_name: str, payload: dict) -> None:
        if event_name == "file_status":
            self.tree.set(payload["item_id"], "status", payload["status"])
        elif event_name == "progress":
            done = payload["done"]
            total = payload["total"]
            if total:
                percent = done / total * 100
                self.status_var.set(f"处理中: {percent:.1f}%")
        elif event_name == "batch_progress":
            self.status_var.set(f"已完成 {payload['completed']} / {payload['total_files']} 个文件")
        elif event_name == "log":
            self.log(payload["message"])
        elif event_name == "done":
            self.processing = False
            self._set_controls_enabled(True)
            self.status_var.set("全部处理完成")
            self.log("全部任务完成。")

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def run(self) -> None:
        self.root.mainloop()


def run_app() -> None:
    LasToolApp().run()
