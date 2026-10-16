"""Kiểm thử luật đọc tin frigate/reviews bằng payload giả.

Payload mô phỏng đúng những tin đã bắt được trên Frigate 0.17.2 (xem
docs/frigate-setup.md): review mở ra ở mức detection rồi mới nâng lên alert.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

from safety.contracts import IncidentLabel, Severity
from safety.mqtt_bridge import DEFAULT_ZONE, ReviewWatcher

REVIEW_ID = "1790948780.082947-qppg7k"


def tin(loai: str, severity: str, *, truoc: str | None = None, zones=(DEFAULT_ZONE,), review_id=REVIEW_ID):
    before = {} if truoc is None else {"severity": truoc}
    return {
        "type": loai,
        "before": before,
        "after": {
            "id": review_id,
            "camera": "xuong_han",
            "severity": severity,
            "start_time": 1790948780.082947,
            "data": {"zones": list(zones), "objects": ["person"], "detections": ["ev1", "ev2"]},
        },
    }


def test_tin_new_muc_detection_khong_canh_bao():
    assert ReviewWatcher().incident_from(tin("new", "detection")) is None


def test_tin_update_nang_len_alert_thi_canh_bao():
    # Đây là trường hợp thật: alert không đến bằng tin "new".
    w = ReviewWatcher()
    assert w.incident_from(tin("new", "detection")) is None
    incident = w.incident_from(tin("update", "alert", truoc="detection"))
    assert incident is not None
    assert incident.label is IncidentLabel.DANGER_ZONE
    assert incident.severity is Severity.HIGH
    assert incident.camera == "xuong_han"
    assert incident.frigate_event_id == REVIEW_ID
    assert incident.ts == 1790948780.082947


def test_tin_new_da_la_alert_cung_canh_bao():
    assert ReviewWatcher().incident_from(tin("new", "alert")) is not None


def test_nhieu_tin_update_chi_canh_bao_mot_lan():
    w = ReviewWatcher()
    assert w.incident_from(tin("update", "alert", truoc="detection")) is not None
    for _ in range(5):
        assert w.incident_from(tin("update", "alert", truoc="alert")) is None
        assert w.incident_from(tin("end", "alert", truoc="alert")) is None


def test_review_khac_van_canh_bao():
    w = ReviewWatcher()
    assert w.incident_from(tin("update", "alert", truoc="detection")) is not None
    khac = tin("update", "alert", truoc="detection", review_id="1790949999.1-abcdef")
    assert w.incident_from(khac) is not None


def test_alert_ngoai_vung_nguy_hiem_thi_bo_qua():
    w = ReviewWatcher()
    assert w.incident_from(tin("update", "alert", truoc="detection", zones=())) is None
    assert w.incident_from(tin("update", "alert", truoc="detection", zones=("loi_di",))) is None


def test_khong_nho_qua_nhieu_id():
    w = ReviewWatcher(nho_toi_da=10)
    for i in range(50):
        w.incident_from(tin("update", "alert", truoc="detection", review_id=f"id-{i}"))
    assert len(w._da_gui) == 10


def test_detection_ids_de_tai_anh():
    assert ReviewWatcher().detection_ids(tin("update", "alert", truoc="detection")) == ["ev1", "ev2"]
