"""Gửi sự cố của module (đồ bảo hộ, cháy/khói) vào nhóm Telegram chung.

Dùng nguyên TelegramNotifier của Uy (safety/notify.py) nên tin của module và tin
vùng nguy hiểm cùng một kiểu, người trực đọc quen. Gửi ở luồng riêng, tách khỏi
luồng gửi Frigate: Telegram chậm thì sự cố vẫn tới Frigate đúng lúc.

Thứ tự đúng là Frigate trước, Telegram sau, để tin nhắn có sẵn đường dẫn mở sự
cố trong Frigate. Frigate lỗi thì Telegram vẫn gửi, chỉ là không kèm đường dẫn.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from safety.contracts import Incident
from safety.notify import TelegramNotifier
from safety.worker import QueueWorker

log = logging.getLogger(__name__)


class TelegramPublisher(QueueWorker):
    what = "Telegram"

    def __init__(self, notifier: TelegramNotifier, maxsize: int = 100, on_done=None):
        self.notifier = notifier
        super().__init__(maxsize=maxsize, on_done=on_done)

    def _handle(self, incident: Incident) -> bool:
        return self.notifier.send(incident)


def notifier_from_env(env: Mapping[str, str] | None = None) -> TelegramNotifier | None:
    """Dựng notifier từ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / FRIGATE_UI trong .env.

    Thiếu mã bot hoặc chat id thì trả về None và báo rõ, không ném lỗi.
    """
    env = os.environ if env is None else env
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        log.error("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong .env, không gửi Telegram")
        return None
    return TelegramNotifier(token=token, chat_id=chat_id,
                            frigate_ui=(env.get("FRIGATE_UI") or "").strip() or None)
