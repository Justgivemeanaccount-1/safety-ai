# Cảnh báo Telegram (tuần 4–5)

Người phụ trách: Long Uy. Hai phần:

| Phần | Tệp | Việc |
|---|---|---|
| Gửi Telegram | `safety/notify.py` | Nhận `Incident`, soạn tin và gửi (ảnh nếu có) |
| Cầu nối MQTT | `safety/mqtt_bridge.py` | Nghe `frigate/reviews`, lọc cảnh báo vùng nguy hiểm, gửi Telegram + ghi DB |

Luật chuyển `frigate/reviews` thành `Incident` theo [data-contract.md](data-contract.md) mục 4.
Sự cố do module tự phát hiện (PPE, cháy, ngã) thì phần của Đạt gọi thẳng `TelegramNotifier`,
không đi qua cầu nối này.

## 1. Tạo bot và lấy chat id

1. Mở Telegram, tìm **@BotFather**, gửi `/newbot`, đặt tên và username kết thúc bằng `bot`.
   BotFather trả về **token** dạng `123456789:AA...`.
2. Tạo một nhóm cho nhóm đồ án (hoặc dùng chat riêng), **thêm bot vào nhóm**.
   Bot không nhắn được vào nhóm chưa có nó.
3. Gửi một tin bất kỳ vào nhóm, rồi mở đường dẫn sau trên trình duyệt, thay `<token>`:

   ```
   https://api.telegram.org/bot<token>/getUpdates
   ```

   Tìm `"chat":{"id":-1001234567890` — số đó là **chat id** (nhóm thì có dấu trừ ở đầu).
4. Điền vào `.env` (tệp này đã nằm trong `.gitignore`, **đừng commit token**):

   ```
   TELEGRAM_BOT_TOKEN=123456789:AA...
   TELEGRAM_CHAT_ID=-1001234567890
   ```

Token lộ thì vào BotFather gửi `/revoke` để cấp token mới.

**Dùng chung một bot cho cả nhóm:** cảnh báo nên đổ vào **nhóm** chứ không phải chat riêng,
nếu không ai cầm chat id thì chỉ người đó nhận được. Nhóm của nhóm đồ án:
*Canh bao an toan - Nhom do an* (chat id âm, bắt đầu bằng `-`).

Hai lưu ý khi lấy chat id của nhóm:

* Bot trong nhóm **không nhận được tin thường** (privacy mode). Muốn nhóm hiện ra trong
  `getUpdates` thì gửi một lệnh có đuôi tên bot, ví dụ `/start@safety_ai_xuonghan_bot`.
* Nhóm thường nâng lên *supergroup* (khi thêm nhiều người, bật lịch sử công khai...) là
  **chat id đổi** sang dạng `-100...`. Lúc đó phải lấy lại chat id và sửa `.env`, nếu không
  cảnh báo im lặng biến mất.

## 2. Chạy

```powershell
.\.venv\Scripts\python.exe -m safety.mqtt_bridge --check   # kiểm tra token + MQTT rồi thoát
.\.venv\Scripts\python.exe -m safety.mqtt_bridge           # chạy thật, Ctrl+C để dừng
```

Khi có người đứng trong `vung_nguy_hiem` đủ `loitering_time`, Frigate nâng review lên
`alert`, cầu nối gửi một tin Telegram và ghi một dòng vào bảng `incidents`.

Đã chạy thật trên máy Uy (16/10): một cảnh báo `danger_zone` gửi kèm ảnh, một dòng trong
`incidents`, và trong 5 phút sau đó không có tin trùng dù Frigate vẫn phát tiếp tin `update`.

`MQTT_HOST` phải là `127.0.0.1` khi chạy ngoài Docker — để `mosquitto` thì module báo
`getaddrinfo failed`, vì đó là tên chỉ có trong mạng Docker.

Nội dung tin theo hợp đồng mục 3c: mức độ tiếng Việt, loại sự cố, camera, giờ địa phương,
độ tin cậy, ảnh, kèm link `.../explore?event_id=<id>`.

## 3. Hai cái bẫy đã đo thực tế (đều có kiểm thử)

* **Alert không đến bằng tin `new`.** Review mở ra ở mức `detection`, một tin `update`
  sau đó mới nâng lên `alert`. Chỉ nghe `new` là bỏ sót toàn bộ cảnh báo vùng nguy hiểm.
* **Một review phát ra nhiều tin `update`.** Phải nhớ `after.id` đã gửi, nếu không mỗi
  lần người nhúc nhích lại là một tin Telegram.

`tests/test_mqtt_bridge.py` khoá cả hai hành vi này bằng payload giả, chạy không cần Frigate:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## 4. Ảnh kèm theo tin

Cầu nối tải ảnh từ `FRIGATE_API` (`/events/<id>/snapshot.jpg`). Chạy **ngoài Docker** thì
cổng 5000 không mở, nên không có ảnh — cảnh báo vẫn gửi dạng chữ, chỉ thiếu ảnh. Khi module
chạy trong Docker (tuần 8) thì dùng `FRIGATE_API=http://frigate:5000/api` và luôn có ảnh.

Muốn thử có ảnh ngay trên máy mình thì tạo `docker-compose.override.yml` (đã gitignore,
không ảnh hưởng cấu hình chung của nhóm):

```yaml
services:
  frigate:
    ports:
      - "8971:8971"
      - "127.0.0.1:8554:8554"
      - "127.0.0.1:5050:5000"   # 5000 trên máy Uy đã bị tiến trình khác chiếm
```

rồi đặt `FRIGATE_API=http://127.0.0.1:5050/api` trong `.env` và `docker compose up -d frigate`.

## 5. Tài khoản xem trên Frigate (tuần 4)

Ngoài `admin`, hệ thống có tài khoản `viewer` chỉ xem, phục vụ yêu cầu phân quyền của
Luật Bảo vệ dữ liệu cá nhân: người trực xem camera không cần quyền sửa cấu hình.

```powershell
docker exec frigate curl -fsS http://127.0.0.1:5000/api/users   # liệt kê tài khoản và vai trò
```

Mật khẩu tài khoản này nằm trong `.env` (`FRIGATE_VIEWER_USER` / `FRIGATE_VIEWER_PASS`),
chỉ dùng để nhóm đăng nhập thử; khi bàn giao thật thì đổi mật khẩu trên giao diện.
