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
    Ok "Cong 8554 mo tren 127.0.0.1"
} catch {
    Fail "Khong ket noi duoc 127.0.0.1:8554. Co the scripts\test-stream.ps1 dang chiem cong, chay: .\scripts\test-stream.ps1 -Stop"
} finally {
    $tcp.Close()
}

# 7. "localhost" tren Windows ra IPv6 (::1) truoc, ma Docker chi mo cong IPv4.
# Module dung rtsp://localhost:... se treo ~30s moi lan ket noi roi khung lien tuc,
# nen phai dung 127.0.0.1. Buoc 6 test bang 127.0.0.1 nen khong bat duoc loi nay.
$v6 = New-Object Net.Sockets.TcpClient([Net.Sockets.AddressFamily]::InterNetworkV6)
try {
    $okV6 = $v6.ConnectAsync([Net.IPAddress]::IPv6Loopback, 8554).Wait(1000) -and $v6.Connected
} catch { $okV6 = $false } finally { $v6.Close() }
$localhostFirst = @([Net.Dns]::GetHostAddresses("localhost"))[0]
if (-not $okV6 -and $localhostFirst.AddressFamily -eq "InterNetworkV6") {
    Warn "localhost -> ::1 (IPv6) nhung cong 8554 chi mo IPv4: KHONG dung rtsp://localhost, dung rtsp://127.0.0.1"
}

# 8. MQTT: broker phai tu choi khach khong mat khau, va Frigate phai dang nhap duoc.
$envFile = Join-Path $repo ".env"
$creds = @{}
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match "^\s*(MQTT_USER|MQTT_PASS)\s*=" } | ForEach-Object {
        $k, $v = $_ -split "=", 2
        $creds[$k.Trim()] = $v.Trim()
    }
}
if (-not $creds["MQTT_USER"] -or -not $creds["MQTT_PASS"]) {
    Fail "Thieu MQTT_USER/MQTT_PASS trong .env (xem .env.example)"
} else {
    # Lenh day qua stdin cho "sh -s": mat khau khong nam tren dong lenh (khong lo
    # trong danh sach tien trinh), va PowerShell 5.1 khong lam hong dau nhay.
    # PowerShell 5.1 luon chen BOM vao dau luong stdin (doi $OutputEncoding hay
    # [Console]::OutputEncoding deu khong bo duoc), lam sh doc dong dau thanh
    # "<BOM>mosquitto_sub: not found". Cho dong dau la "#" de BOM roi vao do.
    $anon = "#`nmosquitto_sub -t frigate/available -C 1 -W 3" | docker exec -i mosquitto sh -s 2>&1
    if ($LASTEXITCODE -eq 0) { Fail "Broker van cho ket noi khong mat khau - kiem tra allow_anonymous" }
    else { Ok "Broker tu choi ket noi khong mat khau" }

    $cmd = "#`nmosquitto_sub -u '{0}' -P '{1}' -t frigate/available -C 1 -W 5" -f $creds["MQTT_USER"], $creds["MQTT_PASS"]
    $msg = $cmd | docker exec -i mosquitto sh -s 2>&1
    if ($LASTEXITCODE -eq 0 -and ($msg -join "") -match "online") {
        Ok "Frigate dang online tren MQTT (dang nhap bang tai khoan trong .env)"
    } else {
        Fail "Khong nhan duoc frigate/available = online. Xem: docker compose logs frigate | Select-String MQTT"
    }
}

Write-Host ""
if ($failed -gt 0) {
    Write-Host "$failed muc loi." -ForegroundColor Red
    exit 1
}
Write-Host "Frigate san sang. Giao dien: https://localhost:8971" -ForegroundColor Green
Write-Host "Thu module (moc M1):"
Write-Host "  .\.venv\Scripts\python.exe -m safety.cli --source rtsp://127.0.0.1:8554/${Camera}_sub"
