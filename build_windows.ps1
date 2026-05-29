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
$ffprobeExe = Join-Path $vendorDir "ffprobe.exe"
if (!(Test-Path $ffmpegExe) -or !(Test-Path $ffprobeExe)) {
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
  $foundFfprobe = Get-ChildItem -Path $ffmpegExtract -Filter "ffprobe.exe" -Recurse | Select-Object -First 1
  if (!$foundFfprobe) {
    throw "Could not find ffprobe.exe in downloaded archive."
  }
  Copy-Item $foundFfmpeg.FullName $ffmpegExe
  Copy-Item $foundFfprobe.FullName $ffprobeExe
}

& $pythonExe @pythonArgs -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "ERNI Stream Downloader" `
  --icon "assets\erni-icon.ico" `
  --add-binary "$ytDlpExe;." `
  --add-binary "$ffmpegExe;." `
  --add-binary "$ffprobeExe;." `
  app.py

Write-Host "Built: dist\\ERNI Stream Downloader.exe"

$iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($iscc) {
  Write-Host "Building branded installer with Inno Setup..."
  & $iscc.Source "installer\ERNIStreamDownloader.iss"
  Write-Host "Built installer: installer-output\\ERNI Stream Downloader Setup.exe"
} else {
  Write-Host "Inno Setup was not found. EXE is ready; install Inno Setup to build installer:"
  Write-Host "winget install JRSoftware.InnoSetup"
}
