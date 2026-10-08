"""Kiểm thử luật cháy và khói bằng dữ liệu giả.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

from safety.contracts import BBox, Detection, DetectClass, FrameResult, IncidentLabel, Severity
from safety.rules import ExcludeZone, FireConfig, FireRule

FLAME = BBox(300, 200, 360, 260)      # giữa khung
LAMP = BBox(560, 20, 620, 70)         # góc trên phải, chỗ đặt đèn báo


def frame(ts: float, *dets: Detection) -> FrameResult:
    return FrameResult(camera="xuong_han", ts=ts, width=640, height=360, detections=dets)


def at(cls: DetectClass, box: BBox, conf: float = 0.8) -> Detection:
    return Detection(cls, box, conf)


def run(rule: FireRule, frames):
    out = []
    for f in frames:
        out.extend(rule.update(f))
    return out


def test_du_6_tren_10_khung_thi_bao():
    rule = FireRule("xuong_han")
    frames = [frame(t / 5, at(DetectClass.FIRE, FLAME)) for t in range(6)]
    incidents = run(rule, frames)
    assert len(incidents) == 1
    assert incidents[0].label is IncidentLabel.FIRE
    assert incidents[0].severity is Severity.CRITICAL


def test_chi_5_tren_10_khung_thi_khong_bao():
    """Hơi nước bay qua vài khung rồi mất: không đủ mật độ."""
    rule = FireRule("xuong_han")
    frames = []
    for t in range(10):
        frames.append(frame(t / 5, at(DetectClass.FIRE, FLAME)) if t < 5 else frame(t / 5))
    assert run(rule, frames) == []


def test_nhap_nhay_ngat_quang_van_tinh():
    """Lửa bị khói che nên có khung mất dấu, nhưng 6/10 khung vẫn đủ."""
    rule = FireRule("xuong_han")
    frames = []
    for t in range(10):
        frames.append(frame(t / 5) if t in (2, 5, 8, 9) else frame(t / 5, at(DetectClass.FIRE, FLAME)))
    assert len(run(rule, frames)) == 1


def test_lua_va_khoi_dem_rieng():
    rule = FireRule("xuong_han")
    frames = []
    for t in range(10):
        dets = [at(DetectClass.FIRE, FLAME)]
        if t < 3:
            dets.append(at(DetectClass.SMOKE, FLAME))
        frames.append(frame(t / 5, *dets))
    incidents = run(rule, frames)
    assert [i.label for i in incidents] == [IncidentLabel.FIRE]


def test_khoi_co_muc_do_thap_hon_lua():
    rule = FireRule("xuong_han")
    frames = [frame(t / 5, at(DetectClass.SMOKE, FLAME)) for t in range(6)]
    incidents = run(rule, frames)
    assert incidents[0].label is IncidentLabel.SMOKE
    assert incidents[0].severity is Severity.HIGH


def test_vung_loai_tru_bo_qua_den_bao():
    """Đèn báo màu vàng ở góc trên hay bị nhận nhầm là lửa."""
    config = FireConfig(exclude=(ExcludeZone(0.85, 0.03, 1.0, 0.25, "den bao"),))
    rule = FireRule("xuong_han", config)
    frames = [frame(t / 5, at(DetectClass.FIRE, LAMP)) for t in range(10)]
    assert run(rule, frames) == []


def test_lua_ngoai_vung_loai_tru_van_bao():
    config = FireConfig(exclude=(ExcludeZone(0.85, 0.03, 1.0, 0.25, "den bao"),))
    rule = FireRule("xuong_han", config)
    frames = [frame(t / 5, at(DetectClass.FIRE, FLAME)) for t in range(6)]
    assert len(run(rule, frames)) == 1


def test_cooldown_chan_bao_lap():
    rule = FireRule("xuong_han")
    frames = [frame(t / 5, at(DetectClass.FIRE, FLAME)) for t in range(100)]
    assert len(run(rule, frames)) == 1


def test_het_cooldown_thi_bao_lai():
    rule = FireRule("xuong_han", FireConfig(cooldown=5.0))
    frames = [frame(t / 5, at(DetectClass.FIRE, FLAME)) for t in range(100)]
    assert len(run(rule, frames)) == 4


def test_score_lay_khung_tin_cay_nhat_trong_cua_so():
    rule = FireRule("xuong_han")
    frames = []
    for t in range(6):
        conf = 0.95 if t == 3 else 0.6
        frames.append(frame(t / 5, at(DetectClass.FIRE, FLAME, conf)))
    incidents = run(rule, frames)
    assert incidents[0].score == 0.95


def test_sub_label_ghi_mat_do():
    rule = FireRule("xuong_han")
    frames = [frame(t / 5, at(DetectClass.FIRE, FLAME)) for t in range(6)]
    incidents = run(rule, frames)
    assert incidents[0].sub_label == "6/6 khung gần nhất"
