"""Gửi cảnh báo sự cố qua Telegram.

Nhận nguyên `Incident` (docs/data-contract.md mục 3c). Có ảnh thì gửi ảnh kèm chú
thích, không có ảnh thì gửi tin chữ — mất ảnh không được làm mất cảnh báo.

Nội dung tin tối thiểu theo hợp đồng: mức độ tiếng Việt, nhãn, camera, giờ địa
phương, ảnh. Kèm thêm link mở sự cố trong Frigate khi biết `frigate_event_id`:
Frigate 0.17 không có đường dẫn /events, trang xem sự cố là /explore?event_id=...
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from safety.contracts import Incident, IncidentLabel

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

# Tên tiếng Việt của từng loại sự cố, để tin nhắn đọc được ngay trên điện thoại.
LABEL_VI: dict[IncidentLabel, str] = {
    IncidentLabel.NO_HELMET: "Không đội mũ bảo hộ",
    IncidentLabel.NO_VEST: "Không mặc áo phản quang",
    IncidentLabel.FIRE: "Phát hiện lửa",
    IncidentLabel.SMOKE: "Phát hiện khói",
    IncidentLabel.FALL: "Người ngã",
    IncidentLabel.DANGER_ZONE: "Người vào vùng nguy hiểm",
}


def format_message(incident: Incident, frigate_ui: str | None = None) -> str:
    """Soạn nội dung tin (HTML của Telegram)."""
    gio = time.strftime("%H:%M:%S %d/%m/%Y", time.localtime(incident.ts))
    dong = [
        f"<b>[{incident.severity.vi}] {LABEL_VI.get(incident.label, incident.label.value)}</b>",
        f"Camera: <code>{incident.camera}</code>",
        f"Thời gian: {gio}",
        f"Độ tin cậy: {incident.score:.2f}",
    ]
    if incident.sub_label:
        dong.append(f"Chi tiết: {incident.sub_label}")
    if frigate_ui and incident.frigate_event_id:
        url = f"{frigate_ui.rstrip('/')}/explore?event_id={incident.frigate_event_id}"
        dong.append(f'<a href="{url}">Xem trong Frigate</a>')
    return "\n".join(dong)


@dataclass
class TelegramNotifier:
    """Gửi `Incident` vào một kênh/nhóm Telegram.

    `token` và `chat_id` lấy từ .env (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).
    Lỗi mạng chỉ ghi log rồi trả về False: cảnh báo hỏng không được làm chết
    vòng chạy của module.
    """

    token: str
    chat_id: str
    frigate_ui: str | None = None
    timeout: float = 10.0
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if not self.token or not self.chat_id:
            raise ValueError("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID")
        self._http = self.session or requests.Session()

    def _url(self, method: str) -> str:
        return f"{TELEGRAM_API}/bot{self.token}/{method}"

    def send(self, incident: Incident) -> bool:
        text = format_message(incident, self.frigate_ui)
        anh = Path(incident.snapshot) if incident.snapshot else None

        if anh is not None and anh.is_file():
            try:
                with anh.open("rb") as f:
                    r = self._http.post(
                        self._url("sendPhoto"),
                        data={"chat_id": self.chat_id, "caption": text, "parse_mode": "HTML"},
                        files={"photo": f},
                        timeout=self.timeout,
                    )
                if r.ok:
                    return True
                log.warning("Telegram từ chối ảnh (%s), gửi lại dạng chữ: %s", r.status_code, r.text[:200])
            except requests.RequestException as e:
                log.warning("Lỗi gửi ảnh Telegram, gửi lại dạng chữ: %s", e)
        elif anh is not None:
            log.warning("Không thấy ảnh %s, gửi tin chữ", anh)

        try:
            r = self._http.post(
                self._url("sendMessage"),
                data={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            log.error("Không gửi được Telegram: %s", e)
            return False

        if not r.ok:
            log.error("Telegram trả lỗi %s: %s", r.status_code, r.text[:200])
            return False
        return True

    def check(self) -> str | None:
        """Gọi getMe để kiểm tra token. Trả về tên bot, hoặc None nếu hỏng."""
        try:
            r = self._http.get(self._url("getMe"), timeout=self.timeout)
            if r.ok:
                return r.json().get("result", {}).get("username")
            log.error("getMe lỗi %s: %s", r.status_code, r.text[:200])
        except requests.RequestException as e:
            log.error("Không gọi được getMe: %s", e)
        return None
