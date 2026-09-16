# Dựng một luồng RTSP giả lập restream của Frigate, để chạy module khi chưa có
# Frigate hoặc camera IP thật. Cũng dùng để phát bộ video kiểm thử ở bài B1–B4.
#
#   .\scripts\test-stream.ps1 -Video data\samples\webcam.mp4
#   .\scripts\test-stream.ps1 -Stop
#
# Cần mediamtx và ffmpeg trên PATH (winget install bluenviron.mediamtx Gyan.FFmpeg,
# rồi mở lại terminal).

param(
    [string]$Video = "data\samples\webcam.mp4",
    [string]$Path = "xuong_han_sub",
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent

if ($Stop) {
    Get-Process mediamtx, ffmpeg -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "Da dung mediamtx va ffmpeg."
    return
}

foreach ($exe in @("mediamtx", "ffmpeg")) {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        throw "Khong tim thay '$exe' tren PATH. Cai bang winget roi mo lai terminal."
    }
}

$videoPath = Join-Path $repo $Video
if (-not (Test-Path $videoPath)) { throw "Khong thay file video: $videoPath" }

if (-not (Get-Process mediamtx -ErrorAction SilentlyContinue)) {
    Start-Process mediamtx -WorkingDirectory $repo -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

$ffArgs = @(
    "-re", "-stream_loop", "-1", "-i", $videoPath,
    "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
    "-an", "-f", "rtsp", "rtsp://localhost:8554/$Path"
)
Start-Process ffmpeg -ArgumentList $ffArgs -WindowStyle Hidden
Start-Sleep -Seconds 3

Write-Host "Luong san sang: rtsp://localhost:8554/$Path"
Write-Host "Chay thu:  .\.venv\Scripts\python.exe -m safety.cli --source rtsp://localhost:8554/$Path"
