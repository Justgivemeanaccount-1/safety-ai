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
import queue
import threading
import time
from collections.abc import Callable

import requests

from safety.contracts import Incident

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


_STOP = object()


class FrigatePublisher:
    """Hàng đợi và luồng nền gửi sự cố sang Frigate.

    `submit` không bao giờ chặn: hàng đợi đầy (Frigate sập lâu) thì bỏ sự cố mới và
    đếm vào `dropped`, chứ không bắt vòng lặp camera phải chờ.
    """

    def __init__(
        self,
        client: FrigateClient,
        maxsize: int = 100,
        on_done: Callable[[Incident], None] | None = None,
    ):
        self.client = client
        self.on_done = on_done
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self.unsent = 0
        self._queue: queue.Queue = queue.Queue(maxsize)
        self._thread = threading.Thread(target=self._run, name="frigate-publisher", daemon=True)
        self._thread.start()

    def submit(self, incident: Incident) -> bool:
        try:
            self._queue.put_nowait(incident)
            return True
        except queue.Full:
            self.dropped += 1
            log.error("Hàng đợi gửi Frigate đầy, bỏ sự cố %s/%s",
                      incident.camera, incident.label.value)
            return False

    def close(self, timeout: float = 10.0) -> bool:
        """Gửi nốt các sự cố đang chờ rồi dừng. Trả về False nếu hết giờ mà chưa xong.

        Hết giờ thì số sự cố bị bỏ dở được ghi vào `unsent` và báo lỗi, để chúng không
        biến mất lặng lẽ (Frigate sập thì mỗi sự cố mất vài giây thử lại).
        """
        deadline = time.monotonic() + timeout
        stop_queued = True
        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            stop_queued = False
        self._thread.join(max(0.0, deadline - time.monotonic()))
        if not self._thread.is_alive():
            return True
        # Sự cố đang gửi dở + những sự cố còn trong hàng đợi, không tính dấu dừng.
        self.unsent = 1 + self._queue.qsize() - (1 if stop_queued else 0)
        log.error("Dừng khi còn %d sự cố chưa gửi được sang Frigate", self.unsent)
        return False

    def _run(self) -> None:
        while True:
            incident = self._queue.get()
            if incident is _STOP:
                return
            try:
                incident.frigate_event_id = self.client.create_event(incident)
                if incident.frigate_event_id:
                    self.sent += 1
                else:
                    self.failed += 1
                if self.on_done is not None:
                    self.on_done(incident)
            except Exception:
                # Luồng này chết thì từ đó về sau không sự cố nào tới được Frigate nữa.
                self.failed += 1
                log.exception("Lỗi không lường trước khi gửi sự cố sang Frigate")
