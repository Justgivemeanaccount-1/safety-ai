"""Kiểm thử nội dung tin Telegram (không gọi mạng thật).

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import time

from safety.contracts import Incident, IncidentLabel, Severity
from safety.notify import TelegramNotifier, format_message

TS = 1790948780.0


def incident(**kwargs) -> Incident:
    mac_dinh = dict(
        camera="xuong_han",
        label=IncidentLabel.DANGER_ZONE,
        severity=Severity.HIGH,
        score=1.0,
        ts=TS,
        sub_label="Frigate: vung_nguy_hiem",
        frigate_event_id="1790948780.082947-qppg7k",
    )
    mac_dinh.update(kwargs)
    return Incident(**mac_dinh)


def test_tin_co_du_field_bat_buoc_theo_hop_dong():
    msg = format_message(incident())
    assert "Cao" in msg                      # severity.vi
    assert "Người vào vùng nguy hiểm" in msg  # label
    assert "xuong_han" in msg                 # camera
    assert time.strftime("%H:%M:%S %d/%m/%Y", time.localtime(TS)) in msg  # giờ địa phương


def test_co_link_explore_khi_biet_frigate_ui():
    msg = format_message(incident(), frigate_ui="https://localhost:8971/")
    # Frigate 0.17 khong co /events, trang xem su co la /explore
    assert "https://localhost:8971/explore?event_id=1790948780.082947-qppg7k" in msg
    assert "/events?" not in msg


def test_khong_co_link_khi_thieu_event_id():
    msg = format_message(incident(frigate_event_id=None), frigate_ui="https://localhost:8971")
    assert "explore" not in msg


def test_nhan_khac_hien_ten_tieng_viet():
    assert "Không đội mũ bảo hộ" in format_message(incident(label=IncidentLabel.NO_HELMET))
    assert "Phát hiện lửa" in format_message(incident(label=IncidentLabel.FIRE, severity=Severity.CRITICAL))


def test_thieu_token_bao_loi_ngay():
    try:
        TelegramNotifier(token="", chat_id="123")
    except ValueError:
        return
    raise AssertionError("phải báo lỗi khi thiếu token")
