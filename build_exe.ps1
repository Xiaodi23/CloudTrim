$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m pip install -r requirements.txt

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name LasBatchDownsampler `
  --paths "$root\src" `
  --collect-all tkinterdnd2 `
  main.py

Write-Host ""
Write-Host "Build completed: $root\dist\LasBatchDownsampler\LasBatchDownsampler.exe"
