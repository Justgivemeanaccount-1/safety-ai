"""Đọc luồng video (RTSP restream của Frigate, webcam, hoặc file).

Module không kết nối thẳng vào camera mà đọc restream của Frigate, nên camera
không bị quá tải kết nối. Đổi camera thật chỉ là đổi URL, không phải sửa code.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator

import cv2
import numpy as np

log = logging.getLogger(__name__)

DEFAULT_FPS = 5.0

# Frigate restream cũng dùng TCP; UDP hay mất gói và vỡ hình trên mạng nhà máy.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


def is_live(url: str | int) -> bool:
    if isinstance(url, int):
        return True
    return "://" in url


class FrameSource:
    """Sinh ra (ts, frame) ở nhịp target_fps.

    Luồng trực tiếp (RTSP, webcam): một thread đọc liên tục và chỉ giữ khung mới
    nhất, vòng chính lấy khung theo nhịp của nó. Nếu đọc và suy luận nằm chung
    một vòng, thời gian suy luận cộng thẳng vào chu kỳ và FPS tụt hẳn xuống dưới
    mức đặt ra; tách thread thì suy luận chậm chỉ làm bỏ khung, không làm chậm nhịp.

    File video: đọc tuần tự và lấy mỗi N khung, không bỏ khung theo đồng hồ —
    bộ video kiểm thử phải cho ra kết quả giống nhau ở mọi lần chạy.
    """

    def __init__(
        self,
        url: str | int,
        target_fps: float = DEFAULT_FPS,
        reconnect_delay: float = 3.0,
        max_retries: int | None = None,
    ):
        self.url = url
        self.target_fps = target_fps
        self.interval = 1.0 / target_fps if target_fps > 0 else 0.0
        self.reconnect_delay = reconnect_delay
        self.max_retries = max_retries

        self._latest: tuple[float, np.ndarray] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._dead = threading.Event()

    def __iter__(self) -> Iterator[tuple[float, np.ndarray]]:
        if is_live(self.url):
            return self._iter_live()
        return self._iter_file()

    def close(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=5.0)
            self._reader = None

    def __enter__(self) -> FrameSource:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _open(self) -> cv2.VideoCapture | None:
        cap = cv2.VideoCapture(self.url)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _read_loop(self) -> None:
        retries = 0
        cap: cv2.VideoCapture | None = None
        try:
            while not self._stop.is_set():
                if cap is None:
                    cap = self._open()
                    if cap is None:
                        retries += 1
                        if self.max_retries is not None and retries > self.max_retries:
                            log.error("Không mở được %s sau %d lần thử", self.url, retries)
                            return
                        log.warning(
                            "Không mở được %s, thử lại sau %.1fs", self.url, self.reconnect_delay
                        )
                        self._stop.wait(self.reconnect_delay)
                        continue
                    retries = 0
                    log.info("Đã kết nối %s", self.url)

                ok, frame = cap.read()
                if not ok:
                    log.warning("Mất luồng %s, kết nối lại", self.url)
                    cap.release()
                    cap = None
                    self._stop.wait(self.reconnect_delay)
                    continue

                with self._lock:
                    self._latest = (time.time(), frame)
        finally:
            if cap is not None:
                cap.release()
            self._dead.set()

    def _iter_live(self) -> Iterator[tuple[float, np.ndarray]]:
        self._stop.clear()
        self._dead.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        last_ts = 0.0
        next_due = 0.0
        try:
            while not self._dead.is_set():
                now = time.time()
                if now < next_due:
                    # Ngủ một lần cho hết quãng còn lại. Ngủ nhiều nhát ngắn thì
                    # mỗi nhát bị làm tròn lên ~15ms theo đồng hồ Windows, cộng
                    # dồn lại đủ kéo FPS xuống thấy rõ.
                    time.sleep(next_due - now)
                    continue
                with self._lock:
                    item = self._latest
                if item is None or item[0] == last_ts:
                    time.sleep(0.005)
                    continue
                last_ts = item[0]
                # Mốc tính từ lúc phát khung chứ không phải sau khi xử lý xong,
                # để thời gian suy luận chạy song song với lúc chờ khung kế tiếp.
                next_due = now + self.interval
                yield item
        finally:
            self.close()

    def _iter_file(self) -> Iterator[tuple[float, np.ndarray]]:
        cap = self._open()
        if cap is None:
            log.error("Không mở được file %s", self.url)
            return
        src_fps = cap.get(cv2.CAP_PROP_FPS) or self.target_fps
        step = max(1, round(src_fps / self.target_fps)) if self.target_fps > 0 else 1
        try:
            idx = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    return
                if idx % step == 0:
                    yield time.time(), frame
                idx += 1
        finally:
            cap.release()
