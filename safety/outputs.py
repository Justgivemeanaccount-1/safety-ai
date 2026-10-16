"""Nối các đầu ra của sự cố theo đúng thứ tự: Frigate trước, Telegram sau.

IncidentProcessor chỉ gọi `submit`. Có Frigate thì sự cố tới Frigate trước, lấy mã
sự cố về rồi mới chuyển sang Telegram để tin nhắn kèm đường dẫn mở sự cố. Không
có Frigate thì sự cố đi thẳng sang Telegram.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from safety.alerts import TelegramPublisher, notifier_from_env
from safety.contracts import Incident
from safety.frigate import FrigateClient, FrigatePublisher

log = logging.getLogger(__name__)


class Outputs:
    def __init__(
        self,
        telegram: TelegramPublisher | None = None,
        telegram_when: Callable[[Incident], bool] | None = None,
    ):
        self.frigate: FrigatePublisher | None = None
        self.telegram = telegram
        # Chọn sự cố nào được gửi Telegram, ví dụ chỉ mức cao trở lên. None = gửi hết.
        self.telegram_when = telegram_when

    def submit(self, incident: Incident) -> bool:
        if self.frigate is not None:
            return self.frigate.submit(incident)
        return self._to_telegram(incident)

    def after_frigate(self, incident: Incident) -> None:
        """Gọi ở luồng Frigate sau mỗi lần gửi, kể cả khi Frigate lỗi."""
        if incident.frigate_event_id:
            log.info("Đã tạo sự cố trong Frigate: /explore?event_id=%s", incident.frigate_event_id)
        self._to_telegram(incident)

    def _to_telegram(self, incident: Incident) -> bool:
        if self.telegram is None:
            return False
        if self.telegram_when is not None and not self.telegram_when(incident):
            return False
        return self.telegram.submit(incident)

    def close(self, timeout: float = 10.0) -> None:
        # Dừng Frigate trước: nó còn đẩy nốt sự cố sang Telegram trong lúc dừng.
        for worker in (self.frigate, self.telegram):
            if worker is not None:
                worker.close(timeout)

    def summary(self) -> str:
        parts = []
        for worker in (self.frigate, self.telegram):
            if worker is not None:
                parts.append(f"{worker.what}: {worker.sent} thành công, {worker.failed} lỗi, "
                             f"{worker.dropped} bỏ do hàng đợi đầy, {worker.unsent} chưa gửi kịp lúc dừng")
        return "; ".join(parts) if parts else "không gửi đi đâu"


def build_outputs(
    frigate_api: str | None,
    camera: str,
    telegram: bool = False,
    telegram_when: Callable[[Incident], bool] | None = None,
    env: Mapping[str, str] | None = None,
) -> Outputs:
    """Dựng các đầu ra theo tuỳ chọn. Thiếu cấu hình thì báo rõ và bỏ qua đầu ra đó."""
    tele = None
    if telegram:
        if env is None:
            from dotenv import load_dotenv

            load_dotenv()
        notifier = notifier_from_env(env)
        if notifier is not None:
            name = notifier.check()
            if name is None:
                log.error("Mã bot Telegram không dùng được, không gửi Telegram")
            else:
                log.info("Gửi Telegram qua bot @%s", name)
                tele = TelegramPublisher(notifier)

    out = Outputs(telegram=tele, telegram_when=telegram_when)

    if frigate_api:
        client = FrigateClient(frigate_api)
        cameras = client.cameras()
        if cameras is None:
            log.warning("Chưa gọi được Frigate; vẫn chạy, sự cố sẽ được thử gửi khi có")
        elif camera not in cameras:
            # Sai tên camera thì Frigate từ chối mọi sự cố, nên báo ngay từ đầu.
            log.error("Frigate không có camera '%s' (đang có: %s)", camera, ", ".join(sorted(cameras)))
        out.frigate = FrigatePublisher(client, on_done=out.after_frigate)
    else:
        log.info("Không có --frigate: sự cố không gửi sang Frigate")
    return out
