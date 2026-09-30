# Changelog / 更新日志

## Unreleased / 未发布

### Added / 新增

- Cancel button and progress bar on both pages. Cancelling discards unfinished outputs and leaves no temporary files behind.
  两个页面新增进度条和取消按钮；取消后未完成的输出会被丢弃，不留临时文件。
- Live X/Y coordinates under the mouse in the Split / Crop preview.
  拆分/裁剪预览中实时显示鼠标所在的 X/Y 坐标。
- Application icon for the window and the executable.
  窗口和 exe 的应用图标。

### Changed / 变更

- Split / Crop toolbar is regrouped: file actions, mode selection, and Cancel/Export on the top row; selection and view controls sit above the preview.
  拆分/裁剪工具栏重新分组：文件操作、模式选择、取消/导出在顶部；选区和视图控件移到预览上方。

## 0.2.0 - 2026-09-30

### Changed / 变更

- The project is now called **CloudTrim** (previously LasTool).
  项目更名为 **CloudTrim**（原名 LasTool）。

### Fixed / 修复

- Voxel downsampling no longer silently drops valid points when a LAS header declares bounds smaller than the real extent. This was verified against a file with a deliberately understated header.
  当 LAS 文件头声明的范围小于实际范围时，体素降采样不再静默丢弃有效点。
- Crop, line split, and grid split now write to temporary files and rename them only after the whole run succeeds. A crash no longer leaves a partial result that later runs would skip as "already exists".
  裁剪、直线分割、格网分割先写临时文件，全部成功后才改名，崩溃不再留下会被后续运行误跳过的残缺结果。
- The Export button no longer drifts when the window is resized.
  修复调整窗口大小时 Export 按钮位置漂移的问题。
- Completion messages now report how many files were written, skipped, failed, or empty instead of always saying everything completed.
  完成提示现在会分别统计写出、跳过、失败和无点的文件数。

### Added / 新增

- Eye Dome Lighting option for the top-view preview.
  顶视图预览新增 Eye Dome Lighting（边缘深度着色）选项。
- Measured performance figures with hardware and caveats in the README.
  README 新增带硬件配置和限定条件的实测性能数据。
