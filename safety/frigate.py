"""Đẩy sự cố sang Frigate qua API.

Gọi POST /api/events/<camera>/<label>/create để sự cố của module nằm chung chỗ với
ghi hình của Frigate: người vận hành mở Frigate là xem được đoạn video quanh lúc
xảy ra. Sự cố tạo bằng API không vào mục Review mà nằm ở mục Explore (đã thử trên
Frigate 0.17.2, xem docs/data-contract.md mục 3a).

Gửi ở luồng riêng: Frigate chậm hay sập thì phần nhận diện vẫn chạy đều, sự cố chỉ
bị trễ hoặc bỏ, không bao giờ làm khựng camera.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import requests

from safety.contracts import Incident
from safety.worker import QueueWorker

log = logging.getLogger(__name__)


class FrigateClient:
    """Gọi API không đăng nhập của Frigate (cổng 5000, chỉ mở trong máy hoặc mạng Docker)."""

    def __init__(
        self,
        api: str,
        timeout: float = 3.0,
        retries: int = 2,
        backoff: float = 1.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api = api.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.sleep = sleep

    def cameras(self) -> set[str] | None:
        """Tên các camera Frigate đang chạy, hoặc None nếu không gọi được Frigate."""
        try:
            r = self.session.get(f"{self.api}/config", timeout=self.timeout)
            r.raise_for_status()
            return set(r.json().get("cameras", {}))
        except (requests.RequestException, ValueError) as e:
            log.warning("Không đọc được cấu hình Frigate ở %s: %s", self.api, e)
            return None

    def create_event(self, incident: Incident, duration: int = 20) -> str | None:
        """Tạo sự cố trong Frigate, trả về event_id; không tạo được thì trả về None.

        Chỉ thử lại khi chưa kết nối được tới Frigate hoặc Frigate báo lỗi 5xx. Hết giờ
        chờ phản hồi thì KHÔNG thử lại: yêu cầu có thể đã tới nơi và Frigate đã tạo sự
        cố, gửi lần nữa sẽ thành hai sự cố trùng nhau.
        """
        try:
            url = self.api + incident.frigate_path
        except ValueError as e:
            log.error("Bỏ qua sự cố: %s", e)
            return None
        name = f"{incident.camera}/{incident.label.value}"
        payload = incident.to_frigate_payload(duration)

        for attempt in range(self.retries + 1):
            try:
                r = self.session.post(url, json=payload, timeout=self.timeout)
            except requests.ConnectionError as e:
                reason = f"không kết nối được ({e.__class__.__name__})"
            except requests.Timeout:
                log.error("Frigate không trả lời sự cố %s sau %.0fs; không gửi lại "
                          "để tránh tạo trùng", name, self.timeout)
                return None
            except requests.RequestException as e:
                log.error("Gửi sự cố %s lỗi: %s", name, e)
                return None
            else:
                if r.status_code < 500:
                    return self._event_id(r, name)
                reason = f"Frigate trả về {r.status_code}"

            if attempt < self.retries:
                wait = self.backoff * 2**attempt
                log.warning("Gửi sự cố %s thất bại: %s; thử lại sau %.0fs", name, reason, wait)
                self.sleep(wait)
            else:
                log.error("Bỏ sự cố %s sau %d lần thử: %s", name, attempt + 1, reason)
        return None

    @staticmethod
    def _event_id(r: requests.Response, name: str) -> str | None:
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.ok and body.get("success") and body.get("event_id"):
            return body["event_id"]
        log.error("Frigate từ chối sự cố %s: %s %s", name, r.status_code,
                  body.get("message") or r.text[:200])
        return None


class FrigatePublisher(QueueWorker):
    """Gửi sự cố sang Frigate ở luồng nền; gửi xong gán mã sự cố Frigate trả về.

    `on_done` được gọi cả khi Frigate lỗi (lúc đó `frigate_event_id` là None), để các
    bước sau như Telegram vẫn báo được dù Frigate đang sập.
    """

    what = "Frigate"

    def __init__(
        self,
        client: FrigateClient,
        maxsize: int = 100,
        on_done: Callable[[Incident], None] | None = None,
    ):
        self.client = client
        super().__init__(maxsize=maxsize, on_done=on_done)

    def _handle(self, incident: Incident) -> bool:
        incident.frigate_event_id = self.client.create_event(incident)
        return incident.frigate_event_id is not None
