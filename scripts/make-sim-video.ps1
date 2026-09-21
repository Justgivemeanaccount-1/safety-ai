# Chuan bi video cho camera gia lap rtsp-sim (data\samples\<camera>.mp4).
#
#   .\scripts\make-sim-video.ps1 -Source data\samples\goc.mp4 -Stabilize
#   .\scripts\make-sim-video.ps1 -Source data\samples\goc.mp4 -Name xuong_han -QuietSeconds 5
#
# Vi sao can: Frigate khoi dong o che do "hieu chinh chuyen dong" va chi thoat ra
# khi chuyen dong < 5% khung hinh (frigate/motion/improved_motion.py). Video stock
# quay tay (camera troi) hoac clip ngan lap lai ma luc nao cung co nguoi di thi
# Frigate hieu chinh mai, KHONG BAO GIO detect. Camera that khong bi vi co luc vang.
#
#   -Stabilize     khoa khung hinh ve khung dau (vidstab tripod), cat 10% vien
#   -QuietSeconds  giu yen khung cuoi N giay de Frigate kip hieu chinh moi vong lap
#
# Chay ffmpeg trong image mediamtx cua docker-compose, khong can cai ffmpeg.

param(
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$Name = "xuong_han",
    [switch]$Stabilize,
    [int]$QuietSeconds = 5
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$samples = Join-Path $repo "data\samples"
$image = "bluenviron/mediamtx:1.21.1-ffmpeg"

$src = (Resolve-Path $Source).Path
New-Item -ItemType Directory -Force $samples | Out-Null
if ((Split-Path $src -Parent) -ne (Resolve-Path $samples).Path) {
    Copy-Item $src $samples -Force
}
$srcName = Split-Path $src -Leaf
$outName = "$Name.mp4"
if ($srcName -eq $outName) { throw "Source trung ten voi file ra ($outName). Doi ten file goc truoc." }

$filters = @()
if ($Stabilize) {
    $filters += "vidstabtransform=tripod=1:input=/tmp/t.trf:optzoom=0:crop=black"
    $filters += "crop=iw*0.8:ih*0.8"
}
$filters += "scale=-2:720", "setsar=1"
if ($QuietSeconds -gt 0) { $filters += "tpad=stop_mode=clone:stop_duration=$QuietSeconds" }
$vf = $filters -join ","

$cmd = ""
if ($Stabilize) {
    $cmd += "ffmpeg -v error -i '/w/$srcName' -vf vidstabdetect=tripod=1:shakiness=8:result=/tmp/t.trf -f null - && "
}
$cmd += "ffmpeg -v error -y -i '/w/$srcName' -vf '$vf' -an -r 25 -c:v libx264 -preset veryfast -crf 23 -g 25 '/w/$outName'"

# rtsp-sim dang mo thu muc nay thi Docker Desktop tren Windows hay bao
# "No such file or directory" khi ghi de file -> dung no truoc.
docker compose -f (Join-Path $repo "docker-compose.yml") stop rtsp-sim 2>$null | Out-Null

Write-Host "Dang xu ly $srcName -> data\samples\$outName ..."
docker run --rm --entrypoint sh -v "${samples}:/w" $image -c $cmd
if ($LASTEXITCODE -ne 0) { throw "ffmpeg loi (ma $LASTEXITCODE)." }

Write-Host "Xong: data\samples\$outName"
Write-Host "Bat lai camera gia lap:  docker compose up -d; docker compose restart frigate"
