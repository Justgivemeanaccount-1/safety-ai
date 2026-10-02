# Cài và cấu hình Frigate (tuần 1–2)

Người phụ trách: Long Uy. Mục tiêu: đạt mốc **M1 — Frigate chạy + module đọc được luồng**.

Frigate bản **0.17.2**, cả nhóm dùng chung, không tự nâng cấp.
Tên camera, tên vùng theo [data-contract.md](data-contract.md) mục 5.

## Sơ đồ khi chạy giả lập

```
data/samples/xuong_han.mp4
        │ (lặp vô hạn)
        ▼
┌──────────────┐  rtsp://rtsp-sim:8554/xuong_han       (720p, ghi hình)
│  rtsp-sim    │  rtsp://rtsp-sim:8554/xuong_han_sub   (360p 10fps, detect)
│  (mediamtx)  │
└──────┬───────┘
       ▼
┌──────────────────────────┐     ┌───────────┐
│ frigate                  │────►│ mosquitto │  127.0.0.1:1883
│  go2rtc restream  :8554 ─┼──► module trên host: rtsp://127.0.0.1:8554/xuong_han_sub
│  web + đăng nhập  :8971  │
│  API nội bộ       :5000  │  (không mở ra host)
└──────────────────────────┘
```

`rtsp-sim` đóng vai camera IP có 2 luồng. Đổi sang camera thật (tuần 8) chỉ cần sửa
`go2rtc.streams` trong `frigate/config.yml`; module không phải sửa gì vì vẫn đọc
`rtsp://<frigate_host>:8554/xuong_han_sub`.

| File | Việc |
|---|---|
| `docker-compose.yml` | frigate + mosquitto + rtsp-sim |
| `frigate/config.example.yml` | Config Frigate mẫu (copy thành `config.yml`) |
| `sim/mediamtx.yml` | Camera giả lập |
| `mosquitto/mosquitto.conf` | Broker MQTT |
| `scripts/frigate-check.ps1` | Kiểm tra mốc M1 |
| `scripts/make-sim-video.ps1` | Chuẩn bị video cho camera giả lập |

---

## Tuần 1 — Cài Docker + Frigate, giả lập RTSP

### 1. Cài Docker Desktop (WSL2)

1. Mở PowerShell **quyền Administrator**: `wsl --install --web-download`, khởi động lại máy.
   (`--web-download` tải từ GitHub; bản thường tải qua Microsoft Store và có máy báo
   `Forbidden (403)`.)
2. Cùng cửa sổ đó: `winget install -e --id Docker.DockerDesktop`, rồi khởi động lại.
3. Mở Docker Desktop, chờ biểu tượng cá voi báo *Engine running*.
4. Kiểm tra trong PowerShell thường:

```powershell
docker version
docker compose version
```

Nên vào *Settings → Resources → WSL integration* / file `%UserProfile%\.wslconfig`
cho WSL2 tối thiểu 4 GB RAM.

### 2. Chuẩn bị video giả lập

Camera giả lập phát `data/samples/xuong_han.mp4` lặp vô hạn. `data/` và `*.mp4` đã
gitignore — **không commit video**, nhất là video có người thật.

Video phải giống camera giám sát thật, nếu không Frigate **không detect gì cả**
(`detection_fps=0`, không lỗi, không cảnh báo):

- **Camera đứng yên.** Frigate khởi động ở chế độ "hiệu chỉnh chuyển động" và chỉ thoát
  ra khi chuyển động < 5% khung hình (`frigate/motion/improved_motion.py`). Hầu hết video
  stock quay tay, cả khung trôi → hiệu chỉnh mãi.
- **Có lúc vắng.** Clip ngắn lặp lại mà lúc nào cũng có người đi thì cũng không bao giờ
  đủ yên để thoát hiệu chỉnh.

Tốt nhất là tự quay bằng điện thoại kê cố định trên cao. Có sẵn video tay thì dùng
script (chạy ffmpeg trong Docker, không cần cài):

```powershell
.\scripts\make-sim-video.ps1 -Source data\samples\goc.mp4 -Stabilize
```

`-Stabilize` khoá khung hình về khung đầu (vidstab tripod) và cắt 10% viền; script luôn
thêm 5 giây đứng yên ở cuối (`-QuietSeconds`). Ra `data/samples/xuong_han.mp4`.

Video nhóm đang dùng: [Pexels 4280746](https://www.pexels.com/video/men-talking-while-walking-in-the-warehouse-4280746/)
(bản 1080p, miễn phí) — nhà kho nhìn từ trên cao, chạy qua script trên với `-Stabilize`.

### 3. Chạy

Từ thư mục gốc repo:

```powershell
Copy-Item .env.example .env                               # nếu chưa có
Copy-Item frigate\config.example.yml frigate\config.yml
.\scripts\test-stream.ps1 -Stop                           # nhường cổng 8554 nếu đang chạy
docker compose up -d
docker compose ps
```

Lần đầu tải image khá lâu (Frigate chiếm ~7.5 GB ổ đĩa). Frigate cần ~1 phút để khởi
động. Vài dòng lỗi `404 Not Found` / `Ffmpeg process crashed` ngay lúc khởi động là bình
thường: luồng phụ lên trước luồng chính, cả rtsp-sim và Frigate tự thử lại.

> `.env` phải có `COMPOSE_PROFILES=sim` thì `rtsp-sim` mới chạy. Không có `.env` thì
> dùng `docker compose --profile sim up -d`.

### 4. Đăng nhập lần đầu

Lần khởi động đầu, Frigate tạo tài khoản `admin` và in mật khẩu ra log:

```powershell
docker compose logs frigate | Select-String -Pattern "Password"
```

Mở <https://localhost:8971> (chứng chỉ tự ký → trình duyệt cảnh báo, chọn *Advanced →
Proceed*). Đăng nhập rồi đổi mật khẩu ngay. Quên mật khẩu: thêm vào `config.yml`
`auth: {reset_admin_password: true}`, restart, lấy mật khẩu mới trong log, rồi xoá dòng đó.

### 5. Kiểm tra

```powershell
.\scripts\frigate-check.ps1
```

Script kiểm tra container, API, camera có hình và có detect, tốc độ detector, restream
`xuong_han_sub` và cổng 8554 trên host. Tất cả `[ OK ]` là xong tuần 1.

Lưu ý: config sai thì Frigate vẫn chạy và báo *healthy*, nhưng ở chế độ an toàn không
có camera nào. Script sẽ báo "Frigate khong co camera"; lỗi cụ thể nằm trong log, tìm
chữ `Config Validation`.

### 6. Chọn detector

Mặc định `cpu` — chỉ để thử. Nếu `frigate-check` báo detector chậm (> 100 ms/lần),
đổi sang OpenVINO chạy trên CPU (chạy được cả chip Intel lẫn AMD, model có sẵn trong image):

```yaml
detectors:
  ov:
    type: openvino
    device: CPU
```

Docker Desktop trên Windows không chuyển được GPU tích hợp Intel vào container, nên
`device: GPU` chỉ dùng khi chạy Frigate trên Linux.

Card NVIDIA: dùng image `ghcr.io/blakeblackshear/frigate:0.17.2-tensorrt` + detector `onnx`,
nhưng phải tự export model YOLOv9/YOLO-NAS sang ONNX. Để sau, làm cùng Nam Trường khi
đo tài nguyên B4; M1 chỉ cần OpenVINO/CPU.

Ghi số `inference_speed` của máy mình vào bảng đo của nhóm. Máy Uy (i5-13400F, không có
GPU tích hợp): detector `cpu` ~13 ms/lần, 1 camera — chưa cần đổi.

---

## Tuần 2 — Camera, ghi hình, vùng nguy hiểm

### 1. Camera

Đã khai sẵn camera `xuong_han` trong `config.example.yml`:
- `xuong_han` (luồng chính) → vai trò `record`
- `xuong_han_sub` (luồng phụ) → vai trò `detect`, 5 FPS

Frigate đọc lại restream go2rtc của chính nó (`rtsp://127.0.0.1:8554/...`), nên camera
thật chỉ bị kết nối 1 lần dù Frigate, module và người xem cùng dùng.

Kiểm tra trên giao diện: *Live* thấy hình; *Settings → Debug* bật *Bounding boxes* thấy khung người.

### 2. Ghi hình

| Loại | Giữ | Ghi chú |
|---|---|---|
| Liên tục | 1 ngày | `record.continuous.days` |
| Alert (vào vùng nguy hiểm, sự cố module) | 14 ngày | `record.alerts.retain` |
| Detection (người bình thường) | 3 ngày | `record.detections.retain` |
| Ảnh snapshot | 14 ngày | `snapshots.retain` |

Giữ ngắn vì hình người lao động là dữ liệu cá nhân — đưa bảng này vào báo cáo.

Dung lượng: luồng chính 720p ~2 Mbps → ghi liên tục **~21,6 GB/ngày/camera** (đo thật trên
đoạn ghi 10 giây). 8 camera × 1 ngày ≈ 170 GB — tính trước ổ đĩa khi làm bài B4.
Kiểm tra: sau vài phút, mục *Review* và thanh thời gian trong *History* có đoạn ghi.

### 3. Vùng nguy hiểm `vung_nguy_hiem`

Toạ độ trong file mẫu khớp video giả lập (lối đi giữa hai dãy kệ). Đổi video hoặc
camera thì vẽ lại:

1. *Settings → Masks / Zones*, chọn camera `xuong_han`.
2. Sửa zone `vung_nguy_hiem` (giữ **đúng tên** — module lọc theo tên này).
3. Vẽ theo **mặt sàn**: Frigate xét người trong vùng bằng điểm giữa cạnh dưới bbox (chân).
4. *Save* → Frigate ghi vào `frigate/config.yml` và restart.
5. Chép dòng `coordinates` mới vào `frigate/config.example.yml` rồi commit, để cả nhóm dùng chung.

Sửa tay trong file thì toạ độ phải **nhỏ hơn 1** (`0.99`, không phải `1.00`) — `1.00` làm
Frigate báo lỗi config và chạy không camera nào.

Cấu hình đang dùng:
- `objects: [person]`, `inertia: 3` (3 khung liên tiếp), `loitering_time: 2` (≥ 2 giây).
  Người chỉ lướt qua vùng dưới 2 giây **không** tính — vẽ vùng đủ rộng theo lối đi thật.
- `review.alerts.required_zones: [vung_nguy_hiem]` → người trong vùng thành **Alert**,
  ngoài vùng chỉ là Detection.

Kiểm tra: chọn đoạn video có người bước vào vùng → *Review → Alerts* có mục mới.
Xem MQTT (chuẩn bị tuần 3):

```powershell
docker exec mosquitto mosquitto_sub -t "frigate/reviews" -W 120
```

Đã chạy thử, ra đúng các field data-contract mục 4 (`after.camera`, `after.severity`,
`after.data.zones`, `after.start_time`, `after.id`). **Lưu ý cho module (tuần 5):** Alert
thường **không** đến bằng tin `type: new`. Đợt review mở ra là `detection`, rồi được nâng
lên `alert` trong một tin `type: update` cùng `id` khi người vào vùng:

```
new     detection  zones=[]
update  alert      zones=['vung_nguy_hiem']
```

Nên module phải xét cả `update`, và nhớ `id` đã báo để không gửi Telegram hai lần.

### 4. Mốc M1 — cùng Đạt

```powershell
.\scripts\frigate-check.ps1
.\.venv\Scripts\python.exe -m safety.cli --source rtsp://127.0.0.1:8554/xuong_han_sub
```

Module in ra `FrameResult` liên tục là đạt M1 (Đạt đã chạy được trên máy Đạt).

**Dùng `127.0.0.1`, không dùng `localhost`.** Trên Windows `localhost` ra IPv6 (`::1`) trước,
mà Docker chỉ mở cổng 8554 cho IPv4 → module treo ~30 giây mỗi lần kết nối rồi khựng liên
tục. `frigate-check` có cảnh báo riêng cho trường hợp này.

Module chạy trên máy khác trong LAN thì
đổi `127.0.0.1:8554:8554` thành `8554:8554` trong `docker-compose.yml` — nhớ là luồng này
không có mật khẩu.

---

## Sự cố đẩy qua API KHÔNG hiện ở Review

Kế hoạch (Bước 5) viết rằng sự cố module đẩy vào Frigate sẽ hiện trong mục *Review* dưới
dạng Alert. **Điều đó sai với Frigate 0.17.2.** Đạt phát hiện, Uy đã kiểm chứng lại:

```
POST /api/events/xuong_han/no_helmet/create
{"sub_label":"ID 7 - khu han","score":0.87,"duration":20,"include_recording":true}
→ {"success":true,"event_id":"1790948969.650282-spqyo8"}
```

Sau đó:

| Kiểm tra | Kết quả |
|---|---|
| `GET /api/events/<id>` | Có, `data.type = "api"`, `has_clip = true`, `has_snapshot = true` |
| Danh sách Events / trang **Explore** | Có |
| Số mục trong `GET /api/review` | **Không đổi** (2 trước, 2 sau) |
| `GET /api/review/<id>` | **404** |
| MQTT `frigate/reviews` | **Không có tin nào** trong 45 giây |
| MQTT `frigate/events` | Không có tin nào mang `id` này |

Bỏ `required_zones` cũng vẫn vậy, nên không phải do cấu hình vùng.

**Hệ quả cho báo cáo và thiết kế:** không hứa "mọi sự cố đều hiện chung ở mục Review".
Sự cố của module xem ở **Explore**, còn đường cho người vận hành là **Telegram + bảng
thống kê Streamlit**, mỗi dòng kèm link mở sự cố trong Frigate:

```
https://<frigate_host>:8971/explore?event_id=<event_id>
```

Lưu ý: Frigate 0.17 **không có** đường dẫn `/events` — giao diện chỉ có `/review` và
`/explore`, và trang Explore đọc tham số `event_id` (xem `web/src/App.tsx`).

## Tuần 3 — Mosquitto có mật khẩu

Từ tuần 3 broker **không cho kết nối ẩn danh** nữa. Tài khoản nằm trong `.env`:

```
MQTT_USER=safety
MQTT_PASS=<tự đặt, đừng để trống>
```

Cách hoạt động: `docker compose` đưa 2 biến này vào container Mosquitto, container tự
tạo `/mosquitto/config/passwd` lúc khởi động, và đưa cùng tài khoản đó cho Frigate qua
`{FRIGATE_MQTT_USER}` / `{FRIGATE_MQTT_PASSWORD}` trong `frigate/config.yml`. Repo không
chứa mật khẩu lẫn file băm. Đổi mật khẩu = sửa `.env` rồi `docker compose up -d`.

Thiếu `MQTT_USER`/`MQTT_PASS` thì `docker compose` dừng ngay và báo tên biến còn thiếu,
thay vì chạy lên rồi im lặng không kết nối được.

Kiểm tra (hoặc chạy `frigate-check.ps1`, đã có sẵn 2 bước này):

```powershell
docker exec mosquitto mosquitto_sub -t frigate/available -C 1 -W 3          # phải bị từ chối
docker exec mosquitto mosquitto_sub -u safety -P '<mat khau>' -t frigate/available -C 1 -W 5   # phải ra "online"
```

Module chạy ngoài Docker thì dùng `MQTT_HOST=127.0.0.1` (xem lưu ý IPv6 ở mục M1).

## Lệnh hay dùng

```powershell
docker compose up -d                 # chạy
docker compose restart frigate       # sau khi sửa frigate\config.yml bằng tay
docker compose logs -f frigate       # xem log
docker compose down                  # dừng (giữ ghi hình)
docker compose down -v               # dừng và XOÁ DB + ghi hình của Frigate
```

## Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `port is already allocated` 8554 | `.\scripts\test-stream.ps1 -Stop` (mediamtx trên host đang chiếm cổng) |
| Camera đen, `camera_fps=0` | `docker compose logs rtsp-sim` — thường do thiếu `data/samples/xuong_han.mp4` |
| Module đọc luồng treo ~30 giây rồi khựng liên tục | Đang dùng `rtsp://localhost:...` → đổi thành `rtsp://127.0.0.1:...` (localhost ra IPv6) |
| Log rtsp-sim báo `RTP packets lost`, ghi hình hỏng khung | ffmpeg đẩy luồng bằng UDP → phải có `-rtsp_transport tcp` trước `-f rtsp` trong `sim/mediamtx.yml` |
| Có hình nhưng `detection_fps=0` | Video rung hoặc không có lúc vắng — xem Tuần 1 mục 2, chạy `make-sim-video.ps1` |
| Có người vào vùng nhưng không có Alert | Người ở trong vùng < `loitering_time` — mở rộng vùng |
| `frigate-check` báo không có camera | Config lỗi, Frigate chạy chế độ an toàn — `docker compose logs frigate \| Select-String Validation -Context 0,3` |
| `make-sim-video.ps1` báo `No such file or directory` | Docker Desktop khoá file khi rtsp-sim đang đọc; script đã tự dừng rtsp-sim, chạy lại |
| Frigate thoát với `Bus error` | Tăng `shm_size` trong compose. Mỗi camera cần `(w*h*1.5*20 + 270480)/1048576` MB theo độ phân giải detect, cộng 40 MB log |
| Sửa `config.yml` không ăn | `docker compose restart frigate`; lỗi cú pháp thì xem `docker compose logs frigate` |
| Máy nóng, giật | Đổi sang OpenVINO; giảm `detect.fps`; đóng bớt tab Live |
| Dùng điện thoại làm camera | App *IP Webcam* (Android) → *Start server*, dùng mẫu dòng IP Webcam trong `config.example.yml` |
