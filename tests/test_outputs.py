"""Kiểm thử thứ tự đầu ra Frigate -> Telegram, không gửi tin thật nào.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import threading
import time

from safety.alerts import TelegramPublisher, notifier_from_env
from safety.contracts import Incident, IncidentLabel, Severity
from safety.frigate import FrigatePublisher
from safety.outputs import Outputs


def incident(label=IncidentLabel.NO_HELMET, severity=Severity.HIGH, track_id=7) -> Incident:
    return Incident(camera="xuong_han", label=label, severity=severity, score=0.87,
                    ts=1789012348.1, sub_label=f"ID {track_id}", track_id=track_id)


class FakeClient:
    """Đứng thay FrigateClient: trả về mã sự cố, hoặc None khi giả làm Frigate sập."""

    def __init__(self, ok=True):
        self.ok = ok

    def create_event(self, inc):
        return f"evt-{inc.track_id}" if self.ok else None


class FakeNotifier:
    """Đứng thay TelegramNotifier: ghi lại sự cố và mã Frigate tại lúc gửi."""

    def __init__(self, gate: threading.Event | None = None):
        self.sent = []
        self.gate = gate

    def send(self, inc):
        if self.gate is not None:
            self.gate.wait(5)
        self.sent.append((inc.track_id, inc.frigate_event_id))
        return True


def outputs(client=None, notifier=None, when=None) -> Outputs:
    tele = TelegramPublisher(notifier) if notifier is not None else None
    out = Outputs(telegram=tele, telegram_when=when)
    if client is not None:
        out.frigate = FrigatePublisher(client, on_done=out.after_frigate)
    return out


def test_frigate_truoc_telegram_sau_nen_tin_co_ma_su_co():
    n = FakeNotifier()
    out = outputs(FakeClient(), n)
    out.submit(incident(track_id=1))
    out.close()
    assert n.sent == [(1, "evt-1")]       # Telegram nhận sự cố đã có mã Frigate để làm đường dẫn


def test_frigate_sap_thi_telegram_van_bao():
    """Hệ thống an toàn: mất Frigate không được kéo theo mất cảnh báo."""
    n = FakeNotifier()
    out = outputs(FakeClient(ok=False), n)
    out.submit(incident(track_id=1))
    out.close()
    assert n.sent == [(1, None)]
    assert out.frigate.failed == 1 and out.telegram.sent == 1


def test_telegram_cham_khong_lam_frigate_cham_theo():
    gate = threading.Event()
    n = FakeNotifier(gate)
    out = outputs(FakeClient(), n)
    for i in range(3):
        out.submit(incident(track_id=i))
    deadline = time.time() + 2
    while out.frigate.sent < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert out.frigate.sent == 3            # cả 3 đã tới Frigate dù Telegram còn đang kẹt
    assert n.sent == []
    gate.set()
    out.close()
    assert [t for t, _ in n.sent] == [0, 1, 2]


def test_khong_co_frigate_thi_gui_thang_telegram():
    n = FakeNotifier()
    out = outputs(None, n)
    out.submit(incident(track_id=1))
    out.close()
    assert n.sent == [(1, None)]


def test_loc_su_co_truoc_khi_gui_telegram():
    n = FakeNotifier()
    out = outputs(FakeClient(), n, when=lambda inc: inc.severity is Severity.CRITICAL)
    out.submit(incident(IncidentLabel.NO_HELMET, Severity.HIGH, track_id=1))
    out.submit(incident(IncidentLabel.FIRE, Severity.CRITICAL, track_id=2))
    out.close()
    assert [t for t, _ in n.sent] == [2]
    assert out.frigate.sent == 2            # Frigate vẫn nhận đủ, chỉ Telegram được lọc


def test_khong_cau_hinh_gi_thi_khong_gui_dau_ca():
    out = outputs(None, None)
    assert out.submit(incident()) is False
    out.close()
    assert out.summary() == "không gửi đi đâu"


def test_thieu_ma_bot_thi_khong_dung_notifier():
    assert notifier_from_env({"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "-1"}) is None
    assert notifier_from_env({"TELEGRAM_BOT_TOKEN": "1:abc"}) is None


def test_du_cau_hinh_thi_kem_dia_chi_frigate():
    n = notifier_from_env({"TELEGRAM_BOT_TOKEN": "1:abc", "TELEGRAM_CHAT_ID": "-5",
                           "FRIGATE_UI": "https://127.0.0.1:8971"})
    assert n.chat_id == "-5" and n.frigate_ui == "https://127.0.0.1:8971"
