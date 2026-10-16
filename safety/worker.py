"""Hàng đợi và luồng nền dùng chung cho mọi đầu ra chậm: Frigate, Telegram.

Vòng lặp camera chỉ bỏ sự cố vào hàng đợi rồi đi tiếp. Mỗi đầu ra có luồng riêng,
nên Telegram chậm 10 giây cũng không làm sự cố tới Frigate muộn theo, và ngược lại.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from safety.contracts import Incident

log = logging.getLogger(__name__)

_STOP = object()


class QueueWorker:
    """Lớp con chỉ cần đặt `what` và viết `_handle`, trả về True nếu gửi được.

    `submit` không bao giờ chặn: hàng đợi đầy thì bỏ sự cố mới và đếm vào `dropped`.
    Mọi sự cố không tới được nơi nhận đều được đếm vào `failed`, `dropped` hoặc
    `unsent`, không cái nào biến mất lặng lẽ.
    """

    what = "đầu ra"

    def __init__(self, maxsize: int = 100, on_done: Callable[[Incident], None] | None = None):
        self.on_done = on_done
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self.unsent = 0
        self._queue: queue.Queue = queue.Queue(maxsize)
        self._thread = threading.Thread(target=self._run, name=f"gui-{self.what}", daemon=True)
        self._thread.start()

    def _handle(self, incident: Incident) -> bool:
        raise NotImplementedError

    def submit(self, incident: Incident) -> bool:
        try:
            self._queue.put_nowait(incident)
            return True
        except queue.Full:
            self.dropped += 1
            log.error("Hàng đợi gửi %s đầy, bỏ sự cố %s/%s",
                      self.what, incident.camera, incident.label.value)
            return False

    def close(self, timeout: float = 10.0) -> bool:
        """Gửi nốt các sự cố đang chờ rồi dừng. Trả về False nếu hết giờ mà chưa xong.

        Hết giờ thì số sự cố bị bỏ dở được ghi vào `unsent` và báo lỗi (Frigate sập
        thì mỗi sự cố mất vài giây thử lại, trên Windows mỗi lần nối hụt mất ~2 giây).
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
        log.error("Dừng khi còn %d sự cố chưa gửi được sang %s", self.unsent, self.what)
        return False

    def _run(self) -> None:
        while True:
            incident = self._queue.get()
            if incident is _STOP:
                return
            try:
                ok = self._handle(incident)
            except Exception:
                # Luồng này chết thì từ đó về sau không sự cố nào tới được nơi nhận nữa.
                ok = False
                log.exception("Lỗi không lường trước khi gửi sự cố sang %s", self.what)
            if ok:
                self.sent += 1
            else:
                self.failed += 1
            if self.on_done is not None:
                try:
                    self.on_done(incident)
                except Exception:
                    log.exception("Lỗi trong bước xử lý sau khi gửi %s", self.what)
