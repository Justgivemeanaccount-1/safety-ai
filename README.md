# Hệ thống phát hiện sự cố an toàn lao động bằng camera AI

Đồ án 12 tuần, nhóm 3 người. Frigate làm nền VMS, nhóm làm **Module AI an toàn** gắn vào Frigate.

| Khối | Ai làm | Việc |
|---|---|---|
| Frigate (nền VMS) | Cài & cấu hình | Camera, xem trực tiếp, ghi hình, xem lại, phát hiện người, vùng nguy hiểm, phân quyền |
| Module AI an toàn | Nhóm tự làm | Thiếu mũ / áo phản quang, cháy / khói, người ngã; áp luật; đẩy sự cố vào Frigate |
| Cảnh báo & thống kê | Nhóm tự làm | Telegram, bảng thống kê Streamlit |

## Đọc trước khi code

**[docs/data-contract.md](docs/data-contract.md)** — định dạng dữ liệu giữa các phần, đã chốt tuần 1.
Nguồn sự thật trong code là [`safety/contracts.py`](safety/contracts.py).

Tóm tắt:

- AI → luật: `FrameResult` chứa các `Detection{track_id, cls, bbox, conf, keypoints}`
- Luật → Frigate / Telegram / DB: `Incident{camera, label, sub_label, severity, score, ts, snapshot}`
- Nhãn sự cố module đẩy vào Frigate: `no_helmet`, `no_vest`, `fire`, `smoke`, `fall`; riêng `danger_zone` do Frigate tự sinh, module chỉ chuyển tiếp

## Cài môi trường

Cần Python 3.12 (3.13+ chưa có bánh xe PyTorch CUDA ổn định), Git, và card NVIDIA nếu muốn chạy GPU.

```powershell
git clone https://github.com/Justgivemeanaccount-1/safety-ai.git
cd safety-ai
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

Kiểm tra GPU đã được nhận:

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Phải ra `True` kèm tên card.

Chạy thử webcam:

```powershell
yolo predict model=yolo26n.pt source=0 show=True device=0
```

Nếu báo `running scripts is disabled` khi activate venv:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Chạy module

Đọc một luồng và chạy tracking, in ra `FrameResult`:

```powershell
.venv\Scripts\python.exe -m safety.cli --source 0                      # webcam
.venv\Scripts\python.exe -m safety.cli --source rtsp://127.0.0.1:8554/xuong_han_sub
.venv\Scripts\python.exe -m safety.cli --source video.mp4 --json       # file, in JSON
```

Khi chưa có Frigate, tự dựng một luồng RTSP để thử (cần `mediamtx` và `ffmpeg` trên PATH):

```powershell
.\scripts\test-stream.ps1 -Video data\samples\webcam.mp4
.\scripts\test-stream.ps1 -Stop
```

Khi Frigate của Uy chạy, chỉ đổi URL sang `rtsp://<frigate_host>:8554/<camera>_sub`, không phải sửa code.

## Chạy Frigate

Cần Docker Desktop (WSL2) và một video mẫu ở `data/samples/xuong_han.mp4`. Chi tiết: [docs/frigate-setup.md](docs/frigate-setup.md).

```powershell
Copy-Item .env.example .env
Copy-Item frigate\config.example.yml frigate\config.yml
docker compose up -d
.\scripts\frigate-check.ps1
```

Giao diện: <https://localhost:8971>. Module đọc `rtsp://127.0.0.1:8554/xuong_han_sub`.

## Cấu trúc

```
safety/          Module AI
  contracts.py     Định dạng dữ liệu dùng chung
  stream.py        Đọc luồng RTSP/webcam/file, tự kết nối lại, giới hạn FPS
  pipeline.py      YOLO + tracking -> FrameResult
  cli.py           Chạy thử
docs/            Tài liệu chốt
schemas/         DDL SQLite cho lịch sử sự cố
frigate/         Config mẫu cho Frigate (copy thành config.yml, không commit)
sim/             Camera giả lập chạy trong Docker cho Frigate
mosquitto/       Config broker MQTT
scripts/         Dựng luồng RTSP thử nghiệm, kiểm tra Frigate
mediamtx.yml     Config máy chủ RTSP thử nghiệm (chạy trên host, không cần Frigate)
docker-compose.yml  Frigate + Mosquitto + camera giả lập
```

## Phân công

| Thành viên | Vai trò |
|---|---|
| Kỳ Đạt | Kiến trúc & Module AI — pipeline, tracking, luật, tích hợp Frigate API + MQTT, Docker Compose |
| Nam Trường | Dữ liệu & mô hình — dataset, gán nhãn, train PPE + cháy, logic ngã (pose), TensorRT, đo độ chính xác |
| Long Uy | Quản trị Frigate & cảnh báo — cài Frigate, Mosquitto, Telegram, Streamlit, video kiểm thử |

## Lưu ý

- Repo public: không commit `.env`, ảnh người lao động, hay `config.yml` có mật khẩu camera.
- Hình ảnh người lao động là dữ liệu cá nhân theo Luật Bảo vệ dữ liệu cá nhân (hiệu lực 01/01/2026).
- Hệ thống chỉ hỗ trợ, không thay thế hệ thống báo cháy đạt chuẩn PCCC.
- Frigate: giấy phép MIT. Ultralytics YOLO: AGPL-3.0 — dùng cho đồ án thoải mái, thương mại hoá cần giấy phép riêng.
