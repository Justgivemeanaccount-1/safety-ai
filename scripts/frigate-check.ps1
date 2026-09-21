# Kiem tra Frigate da san sang cho moc M1: Frigate chay + module doc duoc luong.
#
#   .\scripts\frigate-check.ps1
#   .\scripts\frigate-check.ps1 -Camera xuong_han
#
# Goi API Frigate qua cong noi bo 5000 ben trong container (khong can mo cong ra
# host, khong can dang nhap), roi thu mo restream tu phia host nhu module se lam.

param(
    [string]$Camera = "xuong_han"
)

$repo = Split-Path $PSScriptRoot -Parent
$failed = 0

function Ok($msg)   { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; $script:failed++ }

function Frigate-Api($path) {
    $out = docker exec frigate curl -fsS "http://127.0.0.1:5000/api/$path"
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($out -join "`n")
}

# 1. Cong cu va file can thiet
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Khong thay 'docker'. Cai Docker Desktop (xem docs/frigate-setup.md)."
    exit 1
}
if (Test-Path (Join-Path $repo "frigate\config.yml")) { Ok "Co frigate\config.yml" }
else { Fail "Chua co frigate\config.yml. Chay: Copy-Item frigate\config.example.yml frigate\config.yml" }

$simRunning = (docker ps --filter "name=^rtsp-sim$" --format "{{.Names}}") -eq "rtsp-sim"
if ($simRunning) {
    $video = Join-Path $repo "data\samples\$Camera.mp4"
    if (Test-Path $video) { Ok "Co video gia lap $video" }
    else { Fail "rtsp-sim dang chay nhung thieu $video" }
}

# 2. Container
foreach ($name in @("frigate", "mosquitto")) {
    $status = docker inspect -f "{{.State.Status}}" $name 2>$null
    if ($status -eq "running") { Ok "Container $name dang chay" }
    else { Fail "Container $name khong chay (trang thai: '$status'). Xem: docker compose logs $name" }
}
if ($failed -gt 0) { exit 1 }

# 3. API
$version = Frigate-Api "version"
if ($version) { Ok "Frigate API tra loi, phien ban $version" }
else { Fail "Frigate API khong tra loi. Frigate mat ~1 phut de khoi dong; xem: docker compose logs frigate"; exit 1 }

# 4. Camera co nhan hinh va dang detect
$statsRaw = Frigate-Api "stats"
if ($statsRaw) {
    $stats = $statsRaw | ConvertFrom-Json
    $cam = $stats.cameras.$Camera
    if ($null -eq $cam) {
        # Config sai thi Frigate chay "safe mode" khong camera nao nhung van bao healthy.
        Fail "Frigate khong co camera '$Camera'. Sai ten, hoac config loi: docker compose logs frigate | Select-String 'Validation' -Context 0,3"
    } elseif ($cam.camera_fps -gt 0) {
        Ok ("Camera {0}: camera_fps={1} process_fps={2} detection_fps={3}" -f $Camera, $cam.camera_fps, $cam.process_fps, $cam.detection_fps)
        if ($cam.detection_fps -eq 0) {
            Warn "detection_fps=0: chua detect lan nao. Neu video gia lap co camera rung/khong co luc vang thi Frigate hieu chinh mai - xem scripts\make-sim-video.ps1"
        }
    } else {
        Fail "Camera '$Camera' chua co hinh (camera_fps=0). Xem: docker compose logs frigate rtsp-sim"
    }
    foreach ($d in $stats.detectors.PSObject.Properties) {
        $ms = $d.Value.inference_speed
        $line = "Detector {0}: {1} ms/lan" -f $d.Name, $ms
        if ($ms -gt 100) { Warn "$line (cham - can nhac OpenVINO, xem docs/frigate-setup.md)" } else { Ok $line }
    }
}

# 5. Restream luong phu (cai module doc)
$probeRaw = Frigate-Api "ffprobe?paths=rtsp://127.0.0.1:8554/${Camera}_sub"
$probe = if ($probeRaw) { @($probeRaw | ConvertFrom-Json)[0] } else { $null }
# Frigate 0.17 chi tra codec_long_name/width/height/avg_frame_rate, khong co codec_type.
$v = if ($probe -and $probe.return_code -eq 0) {
    $probe.stdout.streams | Where-Object { $_.width -gt 0 } | Select-Object -First 1
}
if ($v) {
    Ok ("Restream ${Camera}_sub: {0}x{1} @ {2} fps, {3}" -f $v.width, $v.height, $v.avg_frame_rate, $v.codec_long_name)
} else {
    Fail "Khong doc duoc restream ${Camera}_sub. Kiem tra go2rtc.streams trong frigate\config.yml"
}

# 6. Cong 8554 mo tren host (module chay ngoai Docker doc qua day)
$tcp = New-Object Net.Sockets.TcpClient
try {
    $tcp.Connect("127.0.0.1", 8554)
    Ok "Cong 8554 mo tren localhost"
} catch {
    Fail "Khong ket noi duoc localhost:8554. Co the scripts\test-stream.ps1 dang chiem cong, chay: .\scripts\test-stream.ps1 -Stop"
} finally {
    $tcp.Close()
}

Write-Host ""
if ($failed -gt 0) {
    Write-Host "$failed muc loi." -ForegroundColor Red
    exit 1
}
Write-Host "Frigate san sang. Giao dien: https://localhost:8971" -ForegroundColor Green
Write-Host "Thu module (moc M1):"
Write-Host "  .\.venv\Scripts\python.exe -m safety.cli --source rtsp://localhost:8554/${Camera}_sub"
