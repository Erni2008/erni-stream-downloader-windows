$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$pythonExe = $null
$pythonArgs = @()
try {
  py -3 --version | Out-Null
  $pythonExe = "py"
  $pythonArgs = @("-3")
} catch {
  try {
    python --version | Out-Null
    $pythonExe = "python"
  } catch {
    throw "Python was not found. Install Python 3.11+ and enable 'Add python.exe to PATH'."
  }
}

& $pythonExe @pythonArgs -m pip install -r requirements.txt

$vendorDir = Join-Path $PSScriptRoot "vendor"
New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null

$ytDlpExe = Join-Path $vendorDir "yt-dlp.exe"
if (!(Test-Path $ytDlpExe)) {
  Write-Host "Downloading yt-dlp.exe..."
  Invoke-WebRequest `
    -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" `
    -OutFile $ytDlpExe
}

$ffmpegExe = Join-Path $vendorDir "ffmpeg.exe"
if (!(Test-Path $ffmpegExe)) {
  Write-Host "Downloading ffmpeg..."
  $ffmpegZip = Join-Path $vendorDir "ffmpeg-release-essentials.zip"
  $ffmpegExtract = Join-Path $vendorDir "ffmpeg"
  Invoke-WebRequest `
    -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" `
    -OutFile $ffmpegZip
  if (Test-Path $ffmpegExtract) {
    Remove-Item -Recurse -Force $ffmpegExtract
  }
  Expand-Archive -Path $ffmpegZip -DestinationPath $ffmpegExtract
  $foundFfmpeg = Get-ChildItem -Path $ffmpegExtract -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
  if (!$foundFfmpeg) {
    throw "Could not find ffmpeg.exe in downloaded archive."
  }
  Copy-Item $foundFfmpeg.FullName $ffmpegExe
}

& $pythonExe @pythonArgs -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "ERNI Stream Downloader" `
  --add-binary "$ytDlpExe;." `
  --add-binary "$ffmpegExe;." `
  app.py

Write-Host "Built: dist\\ERNI Stream Downloader.exe"
