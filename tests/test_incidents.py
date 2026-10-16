"""Kiểm thử phần nối luật với đầu ra: luật -> ảnh chụp -> gửi đi.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import numpy as np

from safety.contracts import BBox, Detection, DetectClass, FrameResult, Incident, IncidentLabel, Severity
from safety.incidents import IncidentProcessor, snapshot_name

PERSON = BBox(100, 100, 200, 300)
HEAD = BBox(110, 105, 190, 150)
FLAME = BBox(300, 200, 360, 260)
IMAGE = np.zeros((360, 640, 3), dtype=np.uint8)


class ListPublisher:
    def __init__(self):
        self.items = []

    def submit(self, incident):
        self.items.append(incident)
        return True


def frame(ts, *dets):
    return FrameResult(camera="xuong_han", ts=ts, width=640, height=360, detections=dets)


def no_helmet_frames(n=21):
    return [frame(1789012340 + t / 5,
                  Detection(DetectClass.PERSON, PERSON, 0.9, track_id=1),
                  Detection(DetectClass.NO_HELMET, HEAD, 0.8)) for t in range(n)]


def run(processor, frames):
    out = []
    for f in frames:
        out.extend(processor.handle(IMAGE, f))
    return out


def test_su_co_ppe_duoc_chup_anh_va_gui_di(tmp_path):
    pub = ListPublisher()
    proc = IncidentProcessor("xuong_han", publisher=pub, snapshot_dir=tmp_path)
    incidents = run(proc, no_helmet_frames())
    assert len(incidents) == 1
    inc = incidents[0]
    assert pub.items == [inc]
    assert inc.snapshot.endswith("_id1.jpg")
    assert (tmp_path / inc.snapshot.rsplit("/", 1)[1]).stat().st_size > 0


def test_su_co_chay_cung_di_qua_cung_mot_duong(tmp_path):
    pub = ListPublisher()
    proc = IncidentProcessor("xuong_han", publisher=pub, snapshot_dir=tmp_path)
    frames = [frame(1789012340 + t / 5, Detection(DetectClass.FIRE, FLAME, 0.8)) for t in range(6)]
    incidents = run(proc, frames)
    assert [i.label for i in incidents] == [IncidentLabel.FIRE]
    assert pub.items == incidents
    assert "xuong_han_fire_" in incidents[0].snapshot


def test_khong_co_su_co_thi_khong_gui_gi(tmp_path):
    pub = ListPublisher()
    proc = IncidentProcessor("xuong_han", publisher=pub, snapshot_dir=tmp_path)
    frames = [frame(t / 5, Detection(DetectClass.PERSON, PERSON, 0.9, track_id=1)) for t in range(50)]
    assert run(proc, frames) == []
    assert pub.items == []
    assert list(tmp_path.iterdir()) == []


def test_ten_anh_khong_trung_khi_hai_nguoi_vi_pham_cung_giay():
    a = Incident("xuong_han", IncidentLabel.NO_HELMET, Severity.HIGH, 0.8, 1789012348.1, track_id=1)
    b = Incident("xuong_han", IncidentLabel.NO_HELMET, Severity.HIGH, 0.8, 1789012348.4, track_id=2)
    assert snapshot_name(a) != snapshot_name(b)


def test_luu_anh_loi_van_gui_su_co(tmp_path):
    """Đĩa đầy hay sai thư mục thì vẫn phải báo sự cố, chỉ là không có ảnh."""
    blocker = tmp_path / "khong_phai_thu_muc"
    blocker.write_text("x")
    pub = ListPublisher()
    proc = IncidentProcessor("xuong_han", publisher=pub, snapshot_dir=blocker)
    incidents = run(proc, no_helmet_frames())
    assert len(pub.items) == 1
    assert incidents[0].snapshot is None


def test_khong_co_frigate_van_chay(tmp_path):
    proc = IncidentProcessor("xuong_han", publisher=None, snapshot_dir=tmp_path)
    assert len(run(proc, no_helmet_frames())) == 1
