# LAS 批量降采样工具

一个面向 Windows 的轻量桌面工具，用于把多个 `.las` 点云批量做体素降采样。

## 功能

- 支持多个 `.las` 文件加入列表后批量处理
- 支持输入降采样分辨率，例如 `0.2`
- 输出文件自动写回原目录
- 输出文件命名为 `原名_ds_0p2m.las`
- 已存在同名结果时自动跳过
- 默认使用后台线程处理，避免界面卡死
- 安装 `tkinterdnd2` 后支持拖拽导入

## 运行源码

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH=".\src"
python .\main.py
```

如果当前环境尚未安装 `tkinterdnd2`，工具仍可启动，但拖拽会退化为仅支持“添加文件”按钮导入。

## 打包 exe

```powershell
.\build_exe.ps1
```

打包完成后，程序位于 `dist\LasBatchDownsampler\LasBatchDownsampler.exe`。

## 说明

- 第一版只支持 `.las` 输入与输出，不处理 `.laz`
- 体素内保留首个命中的点，不做质心重采样
- 为控制内存占用，读取时按块处理点数据
