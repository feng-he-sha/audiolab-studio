# AudioLab Studio setup for Windows
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -ComfySite "D:\ComfyUI\...\site-packages"
param(
    [string]$ComfySite = $env:AUDIOLAB_COMFY_SITE,
    [string]$PipIndex = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not $PipIndex) {
    $PipIndex = "https://pypi.tuna.tsinghua.edu.cn/simple"
}

Write-Host "== AudioLab Studio setup ==" -ForegroundColor Cyan

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating Python 3.13 virtual environment..."
    py -3.13 -m venv .venv
}
$Py = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "Upgrading pip/wheel/setuptools..."
& $Py -m pip install --upgrade pip wheel setuptools --index-url $PipIndex

# Optional: reuse an existing CUDA-enabled torch from a ComfyUI portable Python
# instead of downloading a multi-GB wheel. Pass -ComfySite or set
# AUDIOLAB_COMFY_SITE to the ComfyUI ...\python_embeded\Lib\site-packages path.
$candidates = @()
if ($ComfySite) { $candidates += $ComfySite }
$candidates += @(
    (Join-Path $env:USERPROFILE "ComfyUI\ComfyUI_windows_portable\python_embeded\Lib\site-packages"),
    (Join-Path $env:USERPROFILE "Documents\ComfyUI\ComfyUI_windows_portable\python_embeded\Lib\site-packages"),
    (Join-Path $env:USERPROFILE "Desktop\ComfyUI\ComfyUI_windows_portable\python_embeded\Lib\site-packages")
)
$resolvedComfy = $null
foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path (Join-Path $candidate "torch"))) {
        $resolvedComfy = $candidate
        break
    }
}
if ($resolvedComfy) {
    Write-Host "Reusing CUDA torch from: $resolvedComfy" -ForegroundColor Green
    $Pth = Join-Path $Root ".venv\Lib\site-packages\comfy_site.pth"
    Set-Content -Path $Pth -Value $resolvedComfy -Encoding ASCII
} else {
    Write-Host "Installing PyTorch CUDA 13.0 (Windows/Linux wheel index)..."
    & $Py -m pip install torch==2.14.1+cu130 --index-url https://download.pytorch.org/whl/cu130
}

Write-Host "Installing Python dependencies..."
& $Py -m pip install -r requirements.txt --index-url $PipIndex

Write-Host "Installing AudioLab package (editable)..."
& $Py -m pip install -e . --no-deps

Write-Host "Installing frontend dependencies..."
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Host "pnpm not found, falling back to npm" -ForegroundColor Yellow
    & npm --prefix web install
    & npm --prefix web run build
} else {
    & pnpm --dir web install
    & pnpm --dir web build
}

Write-Host "Downloading recommended models (MDX HQ4 + timbre + VAD, ~80MB)..."
Write-Host "SenseVoice / BS-Roformer / AST can be downloaded later in the Models page." -ForegroundColor Yellow
Write-Host "Existing local SenseVoice is auto-detected (no copy needed)." -ForegroundColor Yellow
& $Py scripts\fetch_models.py --recommended

Write-Host "Running doctor..."
& $Py -m audiolab doctor

Write-Host "Done. Start with run_workbench.bat" -ForegroundColor Green
