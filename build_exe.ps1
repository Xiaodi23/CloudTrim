[CmdletBinding()]
param(
    [switch]$KeepBuildEnvironment
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildEnvironment = Join-Path $ProjectRoot ".build-venv"
$BuildDirectory = Join-Path $ProjectRoot "build"
$DistributionDirectory = Join-Path $ProjectRoot "dist"
$ApplicationDirectory = Join-Path $DistributionDirectory "CloudTrim"
$ExecutablePath = Join-Path $ApplicationDirectory "CloudTrim.exe"
$ArchivePath = Join-Path $DistributionDirectory "CloudTrim-windows-x64.zip"

Set-Location -LiteralPath $ProjectRoot

foreach ($Target in @($BuildDirectory, $DistributionDirectory)) {
    $ResolvedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
    $ResolvedTarget = [System.IO.Path]::GetFullPath($Target)
    if (-not $ResolvedTarget.StartsWith($ResolvedProjectRoot + [System.IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to remove a path outside the project: $ResolvedTarget"
    }
    if (Test-Path -LiteralPath $ResolvedTarget) {
        Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
    }
}

New-Item -ItemType Directory -Path $BuildDirectory | Out-Null

if (-not $KeepBuildEnvironment -and (Test-Path -LiteralPath $BuildEnvironment)) {
    $ResolvedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
    $ResolvedEnvironment = [System.IO.Path]::GetFullPath($BuildEnvironment)
    if (-not $ResolvedEnvironment.StartsWith($ResolvedProjectRoot + [System.IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to remove a path outside the project: $ResolvedEnvironment"
    }
    Remove-Item -LiteralPath $ResolvedEnvironment -Recurse -Force
}

if (-not (Test-Path -LiteralPath $BuildEnvironment)) {
    python -m venv $BuildEnvironment
}

$BuildPython = Join-Path $BuildEnvironment "Scripts\python.exe"
function Invoke-Checked {
    param([scriptblock]$Command, [string]$Description)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked { & $BuildPython -m pip install --upgrade pip } "Upgrading pip"
# Some lazrs releases ship no wheel for older Python versions; never compile it from source.
Invoke-Checked { & $BuildPython -m pip install --only-binary lazrs -r requirements-dev.txt } "Installing dependencies"
Invoke-Checked { & $BuildPython -m unittest discover -s tests -v } "Running tests"

Invoke-Checked { & $BuildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name CloudTrim `
    --icon (Join-Path $ProjectRoot "src\las_tool\assets\cloudtrim.ico") `
    --add-data ((Join-Path $ProjectRoot "src\las_tool\assets") + ";las_tool\assets") `
    --paths (Join-Path $ProjectRoot "src") `
    --specpath $BuildDirectory `
    --collect-all tkinterdnd2 `
    --collect-all lazrs `
    --exclude-module matplotlib `
    --exclude-module pandas `
    --exclude-module scipy `
    --exclude-module sklearn `
    --exclude-module pyproj `
    --exclude-module torch `
    --exclude-module tensorflow `
    main.py } "Building the executable"

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Build did not produce the expected executable: $ExecutablePath"
}

Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination $ApplicationDirectory
Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Destination $ApplicationDirectory
Compress-Archive -LiteralPath $ApplicationDirectory -DestinationPath $ArchivePath -CompressionLevel Optimal

$ArchiveSizeMB = [math]::Round((Get-Item -LiteralPath $ArchivePath).Length / 1MB, 2)

if (-not $KeepBuildEnvironment) {
    foreach ($Target in @($BuildDirectory, $BuildEnvironment)) {
        $ResolvedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
        $ResolvedTarget = [System.IO.Path]::GetFullPath($Target)
        if (-not $ResolvedTarget.StartsWith($ResolvedProjectRoot + [System.IO.Path]::DirectorySeparatorChar)) {
            throw "Refusing to remove a path outside the project: $ResolvedTarget"
        }
        if (Test-Path -LiteralPath $ResolvedTarget) {
            Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
        }
    }
}

Write-Host ""
Write-Host "Portable build completed."
Write-Host "Executable: $ExecutablePath"
Write-Host "Archive: $ArchivePath ($ArchiveSizeMB MB)"
