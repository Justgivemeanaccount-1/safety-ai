"""Kiểm thử ghép hai mô hình (người/PPE có bám vết + cháy/khói không bám vết).

Dùng mô hình giả nên không cần GPU hay tệp .pt thật.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import numpy as np
import pytest

import safety.pipeline as pipeline_mod
from safety.contracts import DetectClass
from safety.pipeline import SafetyPipeline, _map_classes

FRAME = np.zeros((360, 640, 3), dtype=np.uint8)


class T:
    """Đứng thay tensor của ultralytics: .cpu().numpy() trả về mảng."""

    def __init__(self, a):
        self.a = np.array(a)

    def cpu(self):
        return self

    def numpy(self):
        return self.a


class Boxes:
    def __init__(self, rows, ids=None):
        self.xyxy = T([r[1] for r in rows])
        self.conf = T([r[2] for r in rows])
        self.cls = T([r[0] for r in rows])
        self.id = T(ids) if ids is not None else None
        self._n = len(rows)

    def __len__(self):
        return self._n


class Result:
    def __init__(self, rows, ids=None):
        self.boxes = Boxes(rows, ids) if rows else None
        self.keypoints = None


class FakeModel:
    def __init__(self, names, rows, ids=None):
        self.names = names
        self.rows, self.ids = rows, ids
        self.track_calls = self.predict_calls = 0

    def track(self, frame, **kw):
        self.track_calls += 1
        return [Result(self.rows, self.ids)]

    def predict(self, frame, **kw):
        self.predict_calls += 1
        return [Result(self.rows)]


PERSON_BOX = [100, 100, 200, 300]
FIRE_BOX = [300, 200, 360, 260]


@pytest.fixture
def models(monkeypatch):
    zoo = {}
    monkeypatch.setattr(pipeline_mod, "YOLO", lambda path: zoo[path])
    return zoo


def test_gop_nguoi_co_ma_dinh_danh_va_lua_khong_ma(models):
    models["coco.pt"] = FakeModel({0: "person", 1: "car"}, [(0, PERSON_BOX, 0.9)], ids=[7])
    models["fire.pt"] = FakeModel({0: "fire", 1: "smoke"}, [(0, FIRE_BOX, 0.8)])
    p = SafetyPipeline("coco.pt", "xuong_han", extra_models=["fire.pt"])
    r = p.process(1.0, FRAME)
    got = {(d.cls, d.track_id) for d in r.detections}
    assert got == {(DetectClass.PERSON, 7), (DetectClass.FIRE, None)}
    assert models["fire.pt"].track_calls == 0       # mô hình cháy không bám vết
    assert models["fire.pt"].predict_calls == 1


def test_lop_trung_o_mo_hinh_phu_bi_bo_de_khong_dem_hai_lan(models):
    models["ppe.pt"] = FakeModel({0: "person", 1: "helmet"}, [(0, PERSON_BOX, 0.9)], ids=[1])
    models["fire.pt"] = FakeModel({0: "person", 1: "fire"}, [(0, PERSON_BOX, 0.7), (1, FIRE_BOX, 0.8)])
    p = SafetyPipeline("ppe.pt", "xuong_han", extra_models=["fire.pt"])
    classes = [d.cls for d in p.process(1.0, FRAME).detections]
    assert classes.count(DetectClass.PERSON) == 1
    assert DetectClass.FIRE in classes


def test_mo_hinh_phu_khong_them_lop_moi_thi_khong_chay(models):
    """Không chạy thì không tốn thêm một lần suy luận mỗi khung."""
    models["coco.pt"] = FakeModel({0: "person"}, [(0, PERSON_BOX, 0.9)], ids=[1])
    models["coco2.pt"] = FakeModel({0: "person"}, [(0, PERSON_BOX, 0.9)])
    p = SafetyPipeline("coco.pt", "xuong_han", extra_models=["coco2.pt"])
    p.process(1.0, FRAME)
    assert p.extras == [] and models["coco2.pt"].predict_calls == 0


def test_detect_classes_gop_ca_hai_mo_hinh(models):
    models["coco.pt"] = FakeModel({0: "person"}, [])
    models["fire.pt"] = FakeModel({0: "fire", 1: "smoke"}, [])
    p = SafetyPipeline("coco.pt", "xuong_han", extra_models=["fire.pt"])
    assert p.detect_classes == {DetectClass.PERSON, DetectClass.FIRE, DetectClass.SMOKE}


def test_khong_co_mo_hinh_phu_thi_chay_nhu_cu(models):
    models["coco.pt"] = FakeModel({0: "person"}, [(0, PERSON_BOX, 0.9)], ids=[3])
    p = SafetyPipeline("coco.pt", "xuong_han")
    assert [d.track_id for d in p.process(1.0, FRAME).detections] == [3]


def test_ten_lop_lech_kieu_viet_van_khop():
    """Lệch chữ hoa hay gạch nối thì vẫn khớp, không mất lớp một cách lặng lẽ."""
    m = _map_classes({0: "Fire", 1: "SMOKE", 2: "No-Helmet", 3: "no vest", 4: "forklift"})
    assert m == {0: DetectClass.FIRE, 1: DetectClass.SMOKE,
                 2: DetectClass.NO_HELMET, 3: DetectClass.NO_VEST}
