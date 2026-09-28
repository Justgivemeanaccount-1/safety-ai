"""Kiểm thử luật PPE bằng dữ liệu giả, chưa cần model của Nam Trường.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

from safety.contracts import BBox, Detection, DetectClass, FrameResult, IncidentLabel
from safety.rules import PPEConfig, PPERule

PERSON = BBox(100, 100, 200, 400)
HEAD = BBox(110, 110, 190, 160)      # nằm trong 25% trên của khung người
BODY = BBox(110, 250, 190, 350)      # dưới vùng đầu


def frame(ts: float, *dets: Detection) -> FrameResult:
    return FrameResult(camera="xuong_han", ts=ts, width=640, height=360, detections=dets)


def person(track_id: int = 1) -> Detection:
    return Detection(DetectClass.PERSON, PERSON, 0.9, track_id=track_id)


def at(cls: DetectClass, box: BBox, conf: float = 0.8) -> Detection:
    return Detection(cls, box, conf)


def run(rule: PPERule, frames):
    out = []
    for f in frames:
        out.extend(rule.update(f))
    return out


def test_bao_sau_du_3_giay():
    rule = PPERule("xuong_han")
    frames = [frame(t / 5, person(), at(DetectClass.NO_HELMET, HEAD)) for t in range(21)]
    incidents = run(rule, frames)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.label is IncidentLabel.NO_HELMET
    assert inc.track_id == 1
    assert inc.sub_label == "ID 1"
    assert inc.ts >= 3.0


def test_chua_du_3_giay_thi_khong_bao():
    rule = PPERule("xuong_han")
    frames = [frame(t / 5, person(), at(DetectClass.NO_HELMET, HEAD)) for t in range(14)]
    assert run(rule, frames) == []


def test_co_mu_thi_khong_bao():
    rule = PPERule("xuong_han")
    frames = [frame(t / 5, person(), at(DetectClass.HELMET, HEAD)) for t in range(30)]
    assert run(rule, frames) == []


def test_mat_dau_ngan_van_tinh_lien_tuc():
    """Người khuất sau kệ 0,6 giây rồi hiện lại: đồng hồ không được đặt lại."""
    rule = PPERule("xuong_han")
    frames = []
    for t in range(21):
        if t in (7, 8, 9):
            frames.append(frame(t / 5, person()))          # chỉ thấy người, không kết luận được
        else:
            frames.append(frame(t / 5, person(), at(DetectClass.NO_HELMET, HEAD)))
    assert len(run(rule, frames)) == 1


def test_deo_mu_lai_thi_dat_lai_dong_ho():
    rule = PPERule("xuong_han")
    frames = []
    for t in range(21):
        acc = at(DetectClass.HELMET, HEAD) if t == 10 else at(DetectClass.NO_HELMET, HEAD)
        frames.append(frame(t / 5, person(), acc))
    assert run(rule, frames) == []


def test_cooldown_chan_bao_lap():
    rule = PPERule("xuong_han", PPEConfig(cooldown=60.0))
    frames = [frame(t / 5, person(), at(DetectClass.NO_HELMET, HEAD)) for t in range(150)]
    assert len(run(rule, frames)) == 1


def test_het_cooldown_thi_bao_lai():
    rule = PPERule("xuong_han", PPEConfig(cooldown=10.0))
    frames = [frame(t / 5, person(), at(DetectClass.NO_HELMET, HEAD)) for t in range(150)]
    assert len(run(rule, frames)) == 3


def test_mu_cua_nguoi_khac_khong_tinh():
    """Mũ nằm ở thân người (hoặc của người bên cạnh) không được coi là đội mũ."""
    rule = PPERule("xuong_han")
    frames = [
        frame(t / 5, person(), at(DetectClass.HELMET, BODY), at(DetectClass.NO_HELMET, HEAD))
        for t in range(21)
    ]
    assert len(run(rule, frames)) == 1


def test_hai_nguoi_dem_rieng():
    rule = PPERule("xuong_han")
    other = BBox(300, 100, 400, 400)
    other_head = BBox(310, 110, 390, 160)
    frames = []
    for t in range(21):
        dets = [person(1), at(DetectClass.NO_HELMET, HEAD),
                Detection(DetectClass.PERSON, other, 0.9, track_id=2)]
        if t >= 10:
            dets.append(at(DetectClass.NO_HELMET, other_head))
        frames.append(frame(t / 5, *dets))
    incidents = run(rule, frames)
    assert [i.track_id for i in incidents] == [1]


def test_thieu_ao_phan_quang():
    rule = PPERule("xuong_han")
    frames = [frame(t / 5, person(), at(DetectClass.NO_VEST, BODY)) for t in range(21)]
    incidents = run(rule, frames)
    assert len(incidents) == 1
    assert incidents[0].label is IncidentLabel.NO_VEST


def test_khong_co_track_id_thi_bo_qua():
    rule = PPERule("xuong_han")
    no_id = Detection(DetectClass.PERSON, PERSON, 0.9)
    frames = [frame(t / 5, no_id, at(DetectClass.NO_HELMET, HEAD)) for t in range(21)]
    assert run(rule, frames) == []
