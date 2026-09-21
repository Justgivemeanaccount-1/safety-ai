# Định dạng dữ liệu — chốt tuần 1

Tài liệu này chốt dữ liệu truyền giữa các phần. Nguồn sự thật trong code là
[`safety/contracts.py`](../safety/contracts.py); tài liệu này giải thích cho người đọc.

Ai cũng phải code theo đây: sai một tên field là hai người ghép không chạy.

## 0. Quy ước chung

| Thứ | Chốt | Lý do |
|---|---|---|
| Thời gian | `ts` — epoch giây UTC, kiểu `float` | Frigate dùng epoch, khỏi lệch múi giờ. Trong file kế hoạch gọi là `time`. |
| Toạ độ bbox | `[x1, y1, x2, y2]` pixel, gốc góc trên trái | Trùng định dạng `xyxy` của Ultralytics, không phải chuẩn hoá 0–1 |
| Khung tham chiếu | Đúng khung hình đưa vào pipeline; `width`/`height` trong `FrameResult` ghi lại kích thước khung đó | Ultralytics đã quy đổi bbox về kích thước ảnh đầu vào, nên hai thứ luôn cùng hệ. Ai cần chuẩn hoá thì chia cho `width`/`height`, đừng đoán |
| `conf` / `score` | `float` 0.0–1.0 | |
| Tên file | `snake_case`, không dấu tiếng Việt | Tránh lỗi đường dẫn trên Docker/Linux |

## 1. Bảng nhãn thống nhất

Hai nhóm nhãn khác nhau, đừng lẫn:

**`DetectClass`** — model YOLO trả về:

| Giá trị | Model | Ghi chú |
|---|---|---|
| `person` | PPE | cũng dùng cho pose |
| `helmet` / `no_helmet` | PPE | |
| `vest` / `no_vest` | PPE | |
| `fire` / `smoke` | Cháy | |

**`IncidentLabel`** — sự cố sau khi qua luật:

`no_helmet` · `no_vest` · `fire` · `smoke` · `fall`

> Giá trị `IncidentLabel` đi thẳng vào URL `POST /api/events/<camera>/<label>/create`,
> nên **phải trùng đúng chữ** với label khai trong Frigate. Đổi ở đây là phải đổi cả config Frigate.

**`Severity`**: `critical` (Nghiêm trọng) · `high` (Cao) · `medium` (Trung bình).
Dùng mã ASCII trong DB/JSON, hiển thị tiếng Việt qua `Severity.vi`.

Mức mặc định mỗi loại (luật có thể nâng lên, xem `DEFAULT_SEVERITY`):

| Sự cố | Mức mặc định |
|---|---|
| `fall`, `fire` | `critical` |
| `smoke`, `no_helmet` | `high` |
| `no_vest` | `medium` |

## 2. AI → luật

Model chạy xong một khung hình thì trả về một `FrameResult`.

```python
FrameResult(
    camera="xuong_han",     # trùng tên camera trong Frigate
    ts=1789012345.67,
    width=640, height=480,
    detections=(
        Detection(
            cls=DetectClass.PERSON,
            bbox=BBox(120, 60, 260, 430),
            conf=0.92,
            track_id=7,             # None nếu chưa qua tracker
            keypoints=None,         # 17 điểm COCO, chỉ model pose mới có
        ),
    ),
)
```

`Detection` chính là `{track_id, class, bbox, conf, keypoints}` trong file kế hoạch.
Bọc thêm `FrameResult` để luật biết khung hình thuộc camera nào, lúc nào, kích thước bao nhiêu —
luật PPE cần "kéo dài ≥ 3 giây" nên bắt buộc phải có `ts`.

`keypoints` là tuple 17 `Keypoint(x, y, conf)` theo thứ tự COCO
(xem `COCO_KEYPOINTS`), khớp output `yolo26n-pose`.

Dạng JSON (khi log ra file hoặc gửi qua tiến trình khác):

```json
{
  "camera": "xuong_han",
  "ts": 1789012345.67,
  "width": 640, "height": 480,
  "detections": [
    {"track_id": 7, "cls": "person", "bbox": [120, 60, 260, 430], "conf": 0.92, "keypoints": null}
  ]
}
```

## 3. Luật → Frigate / Telegram / DB

Luật bắn ra `Incident` — cùng một object đi cả ba hướng.

```python
Incident(
    camera="xuong_han",
    label=IncidentLabel.NO_HELMET,
    severity=Severity.HIGH,
    score=0.87,
    ts=1789012348.10,
    sub_label="ID 7 - khu hàn",    # mô tả ngắn cho người xem
    snapshot="snapshots/xuong_han_no_helmet_1789012348.jpg",
    track_id=7,
    frigate_event_id=None,          # điền sau khi Frigate trả về
)
```

### 3a. Đẩy vào Frigate

```
POST http://frigate:5000/api/events/{camera}/{label}/create
{"sub_label": "ID 7 - khu hàn", "score": 0.87, "duration": 20, "include_recording": true}
```

Dùng `incident.frigate_path` và `incident.to_frigate_payload()` để khỏi gõ tay.
Frigate trả về `event_id` → gán vào `incident.frigate_event_id` rồi mới ghi DB.

Cổng 5000 chỉ dùng trong mạng Docker nội bộ, không mở ra ngoài.

### 3b. Ghi DB

`incident.to_dict()` khớp đúng tên cột bảng `incidents`
(xem [`schemas/incidents.sql`](../schemas/incidents.sql)). Dashboard Streamlit đọc thẳng bảng này.

### 3c. Telegram

Nhận nguyên `Incident`. Nội dung tin nhắn do người làm cảnh báo tự định dạng,
nhưng phải có tối thiểu: `severity.vi`, `label`, `camera`, giờ địa phương, và ảnh `snapshot`.

## 4. Frigate → module (MQTT)

Sự cố tạo qua API **không** phát ra MQTT, nên module tự gửi Telegram cho sự cố của mình.
Chiều ngược lại, module nghe topic `frigate/reviews` để bắt sự kiện "người vào vùng nguy hiểm"
do Frigate tự phát hiện, rồi gửi Telegram chung một kênh.

Các field module dùng từ payload của Frigate:

| Field | Dùng làm gì |
|---|---|
| `type` | `new` / `update` / `end` — xem cảnh báo bên dưới |
| `before.severity`, `after.severity` | bắt thời điểm chuyển **sang** `alert` |
| `after.camera` | → `Incident.camera` |
| `after.data.zones` | chỉ xử lý khi có `vung_nguy_hiem` |
| `after.start_time` | → `Incident.ts` |
| `after.id` | → `Incident.frigate_event_id`, và là khoá chống gửi trùng |

> **Alert không đến bằng tin `new`.** (Long Uy đo thực tế trên Frigate 0.17.)
> Một review thường mở ra bằng tin `new` với `severity: detection`, rồi một tin `update`
> sau đó mới nâng lên `alert` khi người đứng trong vùng đủ `loitering_time`.
> Chỉ nghe tin `new` là **bỏ sót toàn bộ cảnh báo vùng nguy hiểm**.
>
> Luật đúng: kích hoạt khi `after.severity == "alert"` **và** `before.severity != "alert"`
> (tức vừa chuyển sang alert; với tin `new` đã là `alert` ngay thì cũng tính).
> Một review phát ra nhiều tin `update` liên tiếp, nên phải nhớ các `after.id` đã gửi
> để mỗi review chỉ báo Telegram **một lần**.

Quy đổi sang `Incident` với `label` = `IncidentLabel` tương ứng vùng nguy hiểm —
vùng nguy hiểm **do Frigate lo**, module chỉ chuyển tiếp cảnh báo, không tự phát hiện.

## 5. Tên camera và vùng

Tên camera là khoá nối mọi thứ: config Frigate, đường dẫn restream, DB, dashboard.

| Chỗ | Giá trị |
|---|---|
| Camera mẫu | `xuong_han` |
| Restream module đọc | `rtsp://<frigate_host>:8554/xuong_han_sub` |
| Vùng nguy hiểm mẫu | `vung_nguy_hiem` |

Đặt tên camera: `snake_case`, không dấu. Thêm camera mới thì khai trong
`frigate/config.example.yml` trước, rồi báo cả nhóm.

## 6. Đổi contract thế nào

1. Sửa `safety/contracts.py` + tài liệu này trong **cùng một commit**.
2. Mở PR, gắn tag `contract`, báo vào nhóm chat.
3. Không đổi im lặng — hai người còn lại đang code dựa vào đây.
