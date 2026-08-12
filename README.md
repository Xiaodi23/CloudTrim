[简体中文](README.md) | [English](README_EN.md)

# LasTool

[![Windows tests and release](https://github.com/xya-0143/lasTool/actions/workflows/windows-release.yml/badge.svg)](https://github.com/xya-0143/lasTool/actions/workflows/windows-release.yml)
[![Latest release](https://img.shields.io/github/v/release/xya-0143/lasTool)](https://github.com/xya-0143/lasTool/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4.svg)](https://github.com/xya-0143/lasTool/releases/latest)

LasTool 是一个轻量级 Windows 桌面工具，用于批量处理 `.las` 点云。它支持体素降采样、多边形裁剪、直线分割和格网分割，并保留原始 LAS 点格式与属性。所有处理都在本地完成，界面语言为英文。

> [直接下载 Windows 便携版 v0.1.0](https://github.com/xya-0143/lasTool/releases/download/v0.1.0/LasTool-windows-x64.zip) · [查看全部版本](https://github.com/xya-0143/lasTool/releases)

## 功能

- 批量体素降采样：每个三维体素保留第一个命中的点。
- 多边形裁剪：在抽样生成的 XY 顶视图中勾画多边形，再按全量点云导出范围内的点。
- 直线分割：画一条有方向的切分线，分别导出左右两侧的点云。
- 格网分割：按指定行列数划分整幅点云，也可以先框定一个矩形范围。
- 多文件处理：预览多个 LAS 文件，并对它们应用同一个裁剪或分割选区。
- 后台并行处理：耗时任务在后台运行，多个互不依赖的文件可以并行处理。
- 安全输出：不覆盖已有结果；任务失败时会清理未完成的输出文件。

## 下载并使用便携版

1. 下载 [LasTool-windows-x64.zip](https://github.com/xya-0143/lasTool/releases/download/v0.1.0/LasTool-windows-x64.zip)。
2. 将 ZIP 完整解压到一个可写目录。
3. 打开解压后的 `LasTool` 文件夹，双击 `LasTool.exe`。

便携版不需要安装 Python。请不要单独移动 `LasTool.exe`，旁边的 `_internal` 文件夹包含程序运行所需的组件。

程序目前没有代码签名，Windows SmartScreen 可能会显示安全提示。你可以先核对源码和 Release 页面，再选择 **More info > Run anyway**。

## 从源码运行

需要 Python 3.9 或更高版本。Windows PowerShell 命令如下：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\lastool.exe
```

也可以直接运行仓库入口：

```powershell
$env:PYTHONPATH = ".\src"
python .\main.py
```

## 输出文件

结果默认写入输入文件所在目录。若同名结果已经存在，程序会跳过该文件，不会覆盖。

| 操作 | 输出文件名 |
| --- | --- |
| 以 0.2 m 分辨率降采样 | `source_ds_0p2m.las` |
| 多边形裁剪 | `source_crop.las` |
| 直线分割 | `source_split_left.las`、`source_split_right.las` |
| 2 x 4 格网分割 | `source_grid_2x4_p1.las` 至 `source_grid_2x4_p8.las` |

格网编号从左上角开始，按行排列到右下角。

## 构建便携版

构建脚本会创建独立虚拟环境，避免把全局 Python 或 Anaconda 中无关的库打进程序：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

输出文件：

- `dist\LasTool\LasTool.exe`
- `dist\LasTool-windows-x64.zip`

构建成功后，脚本会删除临时虚拟环境和 PyInstaller 中间文件。需要反复调试构建时，可以传入 `-KeepBuildEnvironment` 保留环境。

GitHub Actions 会在推送和 Pull Request 时运行测试。推送名称符合 `v*` 的标签时，还会自动构建并发布 Windows 便携版。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖降采样一致性和失败清理、输出路径、参数校验、预览抽样与着色、多文件预览、多边形裁剪、直线分割、格网分割，以及应用源码的界面语言检查。

## 当前限制

- 只支持未压缩的 `.las` 文件，暂不支持 `.laz`。
- 选区基于 XY 顶视图，不支持三维盒选或自由旋转。
- 降采样在每个体素内保留第一个点，不计算质心。
- 文件按块读取，但已占用体素的索引集合仍会随数据增长。超大或非常稀疏的点云可能占用较多内存。
- 任务开始后暂时不能取消。
- 输出目录固定为输入文件所在目录，已有文件一律跳过。

## 隐私

LasTool 不会发起网络请求，不收集遥测数据，也不会上传点云或要求用户提供凭据。生成的 LAS 文件、构建目录、虚拟环境、压缩包、缓存和包含本机路径的 PyInstaller 配置文件均已排除在 Git 版本控制之外。

公开自己的分支前，可以按照 [`docs/release-checklist.md`](docs/release-checklist.md) 检查 Git 历史中的姓名、邮箱、凭据、数据文件和本机绝对路径。

## 许可证

LasTool 使用 [MIT License](LICENSE) 发布。
