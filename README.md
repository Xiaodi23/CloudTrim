[简体中文](README.md) | [English](README_EN.md)

# CloudTrim

[![Tests and release](https://github.com/Xiaodi23/CloudTrim/actions/workflows/windows-release.yml/badge.svg)](https://github.com/Xiaodi23/CloudTrim/actions/workflows/windows-release.yml)
[![Latest release](https://img.shields.io/github/v/release/Xiaodi23/CloudTrim)](https://github.com/Xiaodi23/CloudTrim/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

CloudTrim 是一个轻量的 Windows 桌面工具，用于批量处理 `.las` 和 `.laz` 点云：体素降采样、多边形裁剪、直线分割、格网分割。输出保留原始点格式与全部属性，所有处理均在本地完成。

**[下载 Windows 便携版](https://github.com/Xiaodi23/CloudTrim/releases/latest)**

## 功能

- **体素降采样**：每个三维体素保留第一个命中的点。
- **多边形裁剪**：在 XY 顶视预览中画多边形，导出范围内的全部原始点。
- **直线分割**：画一条有方向的线，分别导出左右两侧。
- **格网分割**：按行列数切分整幅点云，也可先框选矩形范围。
- **LAS / LAZ**：输出沿用输入格式。
- **批量处理**：多个文件共用同一个选区，后台并行，带进度条和取消按钮。
- **安全输出**：不覆盖已有文件；失败或取消时清理未完成的输出。

## 性能

按块流式读写，内存不随文件大小线性增长。测试环境：i9-11900K、64 GB 内存、固态硬盘，单个 2000 万点（680 MB）随机点云：

| 操作 | 耗时 | 吞吐量 |
| --- | --- | --- |
| 裁剪（保留一半范围） | 2.4 秒 | 约 850 万点/秒 |
| 直线分割 | 2.2 秒 | 约 910 万点/秒 |
| 体素降采样（0.2 m，几乎不去重） | 8.2 秒 | 约 250 万点/秒 |
| 体素降采样（1.0 m，保留 35%） | 5.1 秒 | 约 390 万点/秒 |

结果因硬件和点云分布而异。随机点云很少共享体素，属于降采样较慢的情形。作为对照，用 `laspy` 全量读入再 `numpy.unique` 去重需要 27.1 秒。未与其他软件对比。

## 使用

### 便携版

1. 下载 [CloudTrim-windows-x64.zip](https://github.com/Xiaodi23/CloudTrim/releases/latest) 并完整解压。
2. 双击 `CloudTrim\CloudTrim.exe`（不需要 Python，请勿单独移动 exe）。

程序未做代码签名，SmartScreen 可能提示风险，可选择 **More info > Run anyway**。

### 从源码运行

需要 Python 3.9+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\cloudtrim.exe
```

## 输出文件

结果写入输入文件所在目录，同名文件已存在时跳过。

| 操作 | 输出文件名 |
| --- | --- |
| 0.2 m 降采样 | `source_ds_0p2m.las` |
| 多边形裁剪 | `source_crop.las` |
| 直线分割 | `source_split_left.las`、`source_split_right.las` |
| 2 x 4 格网分割 | `source_grid_2x4_p1.las` … `p8.las`（从左上角按行编号） |

## 开发

```powershell
python -m unittest discover -s tests -v          # 测试
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1   # 构建便携版
```

构建脚本使用独立虚拟环境，产物为 `dist\CloudTrim-windows-x64.zip`。推送 `v*` 标签时，GitHub Actions 会自动测试、构建并发布。

## 限制

- 选区基于 XY 顶视图，不支持三维框选。
- 降采样保留体素内第一个点，不计算质心。
- 已保留体素的索引随数据增长（约每体素 8 字节），超大或极稀疏的点云内存占用较高。
- `.laz` 依赖 `lazrs`（便携版已内置）；吞吐量约比 `.las` 低三分之一。
- 输出目录固定为输入文件所在目录。

## 隐私

CloudTrim 不联网、不收集遥测、不上传点云。

## 许可证

[MIT](LICENSE)
