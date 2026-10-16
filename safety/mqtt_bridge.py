"""Nghe MQTT của Frigate, chuyển cảnh báo "người vào vùng nguy hiểm" sang Telegram.

Vùng nguy hiểm do Frigate tự phát hiện (docs/data-contract.md mục 4): module không
tự phát hiện, chỉ nhận qua topic `frigate/reviews`, ghi DB và gửi Telegram, để mọi
cảnh báo về chung một kênh.

Hai cái bẫy đã đo thực tế trên Frigate 0.17 và đều có kiểm thử trong tests/:

* Alert **không** đến bằng tin `new`. Review mở ra ở mức `detection`, rồi một tin
  `update` mới nâng lên `alert`. Nghe mỗi `new` là bỏ sót toàn bộ cảnh báo.
* Một review phát ra nhiều tin `update` liên tiếp, nên phải nhớ `after.id` đã gửi,
  nếu không mỗi lần người nhúc nhích là một tin Telegram.

Chạy:

    .venv\\Scripts\\python.exe -m safety.mqtt_bridge           # chạy thật
    .venv\\Scripts\\python.exe -m safety.mqtt_bridge --check   # chỉ kiểm tra kết nối
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import requests

from safety.contracts import DEFAULT_SEVERITY, Incident, IncidentLabel
from safety.notify import TelegramNotifier

log = logging.getLogger(__name__)

TOPIC_REVIEWS = "frigate/reviews"
DEFAULT_ZONE = "vung_nguy_hiem"


@dataclass
class ReviewWatcher:
    """Quyết định một tin `frigate/reviews` có phải cảnh báo mới hay không.

    Tách riêng khỏi phần MQTT để kiểm thử được bằng payload giả.
    """

    zone: str = DEFAULT_ZONE
    nho_toi_da: int = 500
    _da_gui: OrderedDict[str, float] = field(default_factory=OrderedDict, init=False)

    def incident_from(self, payload: dict) -> Incident | None:
        after = payload.get("after") or {}
        before = payload.get("before") or {}

        if after.get("severity") != "alert":
            return None
        # Chỉ bắt lúc vừa chuyển sang alert: tin "new" đã là alert thì before rỗng.
        if before.get("severity") == "alert":
            return None

        zones = (after.get("data") or {}).get("zones") or []
        if self.zone not in zones:
            return None

        review_id = after.get("id")
        if not review_id or review_id in self._da_gui:
            return None

        self._da_gui[review_id] = time.time()
        while len(self._da_gui) > self.nho_toi_da:
            self._da_gui.popitem(last=False)

        # Khoá chống trùng là mã review, nhưng mã lưu vào Incident phải là mã SỰ KIỆN
        # (người bị phát hiện): /explore?event_id=<mã review> cho ra
        # "No Tracked Objects Found". Review không có detections thì đành dùng mã review.
        detections = self.detection_ids(payload)
        event_id = detections[0] if detections else review_id

        return Incident(
            camera=after.get("camera", ""),
            label=IncidentLabel.DANGER_ZONE,
            severity=DEFAULT_SEVERITY[IncidentLabel.DANGER_ZONE],
            # Frigate không trả điểm cho review; 1.0 nghĩa là "chính Frigate khẳng định".
            score=1.0,
            ts=float(after.get("start_time") or time.time()),
            sub_label=f"Frigate: {self.zone}",
            frigate_event_id=event_id,
        )

    def detection_ids(self, payload: dict) -> list[str]:
        """Các event id nằm trong review — dùng để tải ảnh."""
        return list(((payload.get("after") or {}).get("data") or {}).get("detections") or [])


def tai_anh(frigate_api: str, event_id: str, thu_muc: Path, timeout: float = 5.0) -> str | None:
    """Tải ảnh sự kiện từ Frigate về `thu_muc`. Trả về đường dẫn, hoặc None.

    Chạy ngoài Docker thì cổng 5000 không mở (xem docker-compose.yml), lúc đó
    coi như không có ảnh và vẫn gửi cảnh báo dạng chữ.
    """
    url = f"{frigate_api.rstrip('/')}/events/{event_id}/snapshot.jpg"
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("Không tải được ảnh %s: %s", url, e)
        return None

    thu_muc.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc / f"{event_id}.jpg"
    duong_dan.write_bytes(r.content)
    return str(duong_dan)


def ghi_db(db_path: Path, incident: Incident) -> None:
    """Ghi sự cố vào bảng incidents (schemas/incidents.sql)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cot = incident.to_dict()
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS incidents (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   camera TEXT NOT NULL, label TEXT NOT NULL, sub_label TEXT,
                   severity TEXT NOT NULL CHECK (severity IN ('critical','high','medium')),
                   score REAL NOT NULL, ts REAL NOT NULL, snapshot TEXT,
                   track_id INTEGER, frigate_event_id TEXT,
                   false_alarm INTEGER NOT NULL DEFAULT 0,
                   created_at REAL NOT NULL DEFAULT (unixepoch('now')))"""
        )
        con.execute(
            """INSERT INTO incidents
                   (camera, label, sub_label, severity, score, ts, snapshot, track_id, frigate_event_id)
               VALUES (:camera, :label, :sub_label, :severity, :score, :ts, :snapshot, :track_id, :frigate_event_id)""",
            cot,
        )


@dataclass
class Bridge:
    notifier: TelegramNotifier
    frigate_api: str
    snapshot_dir: Path
    db_path: Path
    watcher: ReviewWatcher = field(default_factory=ReviewWatcher)

    def xu_ly(self, payload: dict) -> Incident | None:
        incident = self.watcher.incident_from(payload)
        if incident is None:
            return None

        for event_id in self.watcher.detection_ids(payload):
            anh = tai_anh(self.frigate_api, event_id, self.snapshot_dir)
            if anh:
                incident.snapshot = anh
                break

        if self.notifier.send(incident):
            log.info("Đã gửi Telegram: %s %s", incident.label.value, incident.frigate_event_id)
        try:
            ghi_db(self.db_path, incident)
        except sqlite3.Error as e:
            log.error("Không ghi được DB: %s", e)
        return incident


def _env(ten: str, mac_dinh: str = "") -> str:
    return os.environ.get(ten, mac_dinh).strip()


def main() -> int:
    import paho.mqtt.client as mqtt
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description="Chuyển cảnh báo vùng nguy hiểm sang Telegram")
    parser.add_argument("--check", action="store_true", help="chỉ kiểm tra kết nối rồi thoát")
    parser.add_argument("--zone", default=None, help=f"tên vùng (mặc định {DEFAULT_ZONE})")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()

    notifier = TelegramNotifier(
        token=_env("TELEGRAM_BOT_TOKEN"),
        chat_id=_env("TELEGRAM_CHAT_ID"),
        frigate_ui=_env("FRIGATE_UI") or None,
    )
    bridge = Bridge(
        notifier=notifier,
        frigate_api=_env("FRIGATE_API", "http://127.0.0.1:5000/api"),
        snapshot_dir=Path(_env("SNAPSHOT_DIR", "snapshots")),
        db_path=Path(_env("INCIDENT_DB", "data/incidents.db")),
        watcher=ReviewWatcher(zone=args.zone or DEFAULT_ZONE),
    )

    ten_bot = notifier.check()
    if ten_bot is None:
        log.error("Token Telegram không dùng được — kiểm tra TELEGRAM_BOT_TOKEN trong .env")
        return 1
    log.info("Bot Telegram: @%s", ten_bot)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    user, password = _env("MQTT_USER"), _env("MQTT_PASS")
    if user:
        client.username_pw_set(user, password)

    ket_qua_noi: dict[str, object] = {}

    def on_connect(c, userdata, flags, reason_code, properties=None):
        ket_qua_noi["code"] = reason_code
        if reason_code != 0:
            # Sai mật khẩu rơi vào đây, không phải vào lỗi mạng của connect().
            log.error("MQTT từ chối kết nối: %s", reason_code)
            return
        log.info("Đã nối MQTT, nghe %s", TOPIC_REVIEWS)
        c.subscribe(TOPIC_REVIEWS)

    def on_message(c, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            log.warning("Tin MQTT hỏng: %s", e)
            return
        bridge.xu_ly(payload)

    client.on_connect = on_connect
    client.on_message = on_message

    host = _env("MQTT_HOST", "127.0.0.1")
    port = int(_env("MQTT_PORT", "1883") or 1883)
    client.connect(host, port, keepalive=60)

    if args.check:
        # Broker trả mã từ chối trong on_connect, nên phải chờ có kết quả rồi mới kết luận.
        han = time.monotonic() + 5.0
        while "code" not in ket_qua_noi and time.monotonic() < han:
            client.loop(timeout=0.5)
        client.disconnect()

        code = ket_qua_noi.get("code")
        if code is None:
            log.error("Không nhận được phản hồi từ MQTT %s:%s sau 5 giây", host, port)
            return 1
        if int(code) != 0:
            log.error("MQTT %s:%s từ chối: %s (kiểm tra MQTT_USER/MQTT_PASS)", host, port, code)
            return 1
        log.info("Kết nối MQTT %s:%s và Telegram đều tốt", host, port)
        return 0

    log.info("Đang chạy. Ctrl+C để dừng.")
    try:
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        log.info("Dừng theo yêu cầu")
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
