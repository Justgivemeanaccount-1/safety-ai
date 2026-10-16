"""Kiểm thử phần đẩy sự cố sang Frigate, không cần Docker hay Frigate thật.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from safety.contracts import Incident, IncidentLabel, Severity
from safety.frigate import FrigateClient, FrigatePublisher

API = "http://frigate.test:5000/api"


def incident(label=IncidentLabel.NO_HELMET, track_id=7) -> Incident:
    return Incident(camera="xuong_han", label=label, severity=Severity.HIGH, score=0.87,
                    ts=1789012348.1, sub_label="ID 7", track_id=track_id)


class FakeResponse:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.text = json.dumps(body) if body is not None else "<html>loi</html>"

    def json(self):
        if self._body is None:
            raise ValueError("khong phai JSON")
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


OK = FakeResponse(200, {"success": True, "message": "Successfully created event.",
                        "event_id": "1790570171.546709-qo7bdt"})


class FakeSession:
    """Trả lần lượt các phản hồi đã kịch bản sẵn; phần tử là ngoại lệ thì ném ra."""

    def __init__(self, *script, delay: float = 0.0):
        self.script = list(script)
        self.calls = []
        self.delay = delay

    def _next(self):
        if self.delay:
            time.sleep(self.delay)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return self._next()

    def get(self, url, timeout=None):
        self.calls.append((url, None))
        return self._next()


def client(session, waits=None) -> FrigateClient:
    return FrigateClient(API, session=session,
                         sleep=(waits.append if waits is not None else lambda s: None))


# ---------- FrigateClient ----------

def test_gui_dung_dia_chi_va_noi_dung():
    s = FakeSession(OK)
    assert client(s).create_event(incident()) == "1790570171.546709-qo7bdt"
    url, payload = s.calls[0]
    assert url == f"{API}/events/xuong_han/no_helmet/create"
    assert payload == {"sub_label": "ID 7", "score": 0.87, "duration": 20,
                       "include_recording": True}


def test_mat_ket_noi_thi_thu_lai_roi_thanh_cong():
    waits = []
    s = FakeSession(requests.ConnectionError(), requests.ConnectionError(), OK)
    assert client(s, waits).create_event(incident()) is not None
    assert len(s.calls) == 3
    assert waits == [1.0, 2.0]          # chờ tăng dần, không dội liên tục vào Frigate


def test_het_so_lan_thu_thi_bo_khong_nem_loi():
    s = FakeSession(requests.ConnectionError())
    assert client(s).create_event(incident()) is None
    assert len(s.calls) == 3            # 1 lần đầu + 2 lần thử lại


def test_frigate_loi_5xx_thi_thu_lai():
    s = FakeSession(FakeResponse(503), OK)
    assert client(s).create_event(incident()) is not None
    assert len(s.calls) == 2


def test_frigate_tu_choi_4xx_thi_khong_thu_lai():
    """Sai tên camera: gửi lại bao nhiêu lần cũng vẫn sai."""
    s = FakeSession(FakeResponse(404, {"success": False, "message": "Camera not found"}))
    assert client(s).create_event(incident()) is None
    assert len(s.calls) == 1


def test_het_gio_cho_phan_hoi_thi_khong_gui_lai():
    """Yêu cầu có thể đã tới Frigate; gửi lại sẽ tạo hai sự cố trùng nhau."""
    s = FakeSession(requests.ReadTimeout())
    assert client(s).create_event(incident()) is None
    assert len(s.calls) == 1


def test_het_gio_luc_ket_noi_thi_van_thu_lai():
    """Chưa kết nối được thì yêu cầu chưa đi, gửi lại không sợ trùng."""
    s = FakeSession(requests.ConnectTimeout(), OK)
    assert client(s).create_event(incident()) is not None
    assert len(s.calls) == 2


def test_danger_zone_khong_bao_gio_gui_nguoc_vao_frigate():
    s = FakeSession(OK)
    assert client(s).create_event(incident(IncidentLabel.DANGER_ZONE)) is None
    assert s.calls == []


def test_doc_ten_camera_cua_frigate():
    s = FakeSession(FakeResponse(200, {"cameras": {"xuong_han": {}, "kho": {}}}))
    assert client(s).cameras() == {"xuong_han", "kho"}


def test_frigate_tat_thi_doc_camera_tra_ve_none():
    assert client(FakeSession(requests.ConnectionError())).cameras() is None


def test_gui_that_qua_http():
    """Dựng một máy chủ HTTP thật trong máy để chắc requests gửi đúng như Frigate nhận."""
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.update(path=self.path, type=self.headers["Content-Type"], body=json.loads(body))
            out = json.dumps({"success": True, "event_id": "abc"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    try:
        api = f"http://127.0.0.1:{server.server_port}/api"
        assert FrigateClient(api).create_event(incident()) == "abc"
    finally:
        server.server_close()
    assert seen["path"] == "/api/events/xuong_han/no_helmet/create"
    assert seen["type"] == "application/json"
    assert seen["body"]["include_recording"] is True


# ---------- FrigatePublisher ----------

def test_frigate_treo_cung_khong_lam_khung_camera():
    pub = FrigatePublisher(client(FakeSession(OK, delay=1.0)))
    t0 = time.perf_counter()
    for _ in range(5):
        pub.submit(incident())
    assert time.perf_counter() - t0 < 0.05     # 5 lần gửi mà vòng lặp camera không phải chờ


def test_gui_xong_thi_gan_event_id_vao_su_co():
    pub = FrigatePublisher(client(FakeSession(OK)))
    items = [incident(track_id=i) for i in range(3)]
    for inc in items:
        pub.submit(inc)
    assert pub.close()
    assert pub.sent == 3 and pub.failed == 0
    assert all(inc.frigate_event_id == "1790570171.546709-qo7bdt" for inc in items)


def test_hang_doi_day_thi_bo_su_co_moi():
    started, release = threading.Event(), threading.Event()

    class Blocking(FakeSession):
        def post(self, url, json=None, timeout=None):
            started.set()
            release.wait(5)
            return OK

    pub = FrigatePublisher(client(Blocking(OK)), maxsize=1)
    assert pub.submit(incident(track_id=1))     # luồng nền nhận và bị treo ở đây
    assert started.wait(5)
    assert pub.submit(incident(track_id=2))     # nằm chờ trong hàng đợi
    assert not pub.submit(incident(track_id=3)) # hàng đợi đầy -> bỏ
    assert pub.dropped == 1
    release.set()
    assert pub.close()
    assert pub.sent == 2


def test_dung_khi_frigate_treo_thi_dem_so_su_co_bi_bo_do():
    """Lần chạy thật với Frigate tắt: 4 sự cố mà chỉ đếm được 1. Ba cái kia không được mất lặng lẽ."""
    release = threading.Event()

    class Blocking(FakeSession):
        def post(self, url, json=None, timeout=None):
            release.wait(5)
            return OK

    pub = FrigatePublisher(client(Blocking(OK)))
    for i in range(4):
        pub.submit(incident(track_id=i))
    assert not pub.close(timeout=0.2)
    assert pub.unsent == 4                      # 1 đang gửi dở + 3 còn trong hàng đợi
    release.set()


def test_loi_bat_ngo_khong_giet_luong_gui():
    calls = []

    def on_done(inc):
        calls.append(inc.track_id)
        if inc.track_id == 1:
            raise RuntimeError("loi trong ham goi lai")

    pub = FrigatePublisher(client(FakeSession(OK)), on_done=on_done)
    pub.submit(incident(track_id=1))
    pub.submit(incident(track_id=2))
    assert pub.close()
    assert calls == [1, 2]                      # sự cố thứ hai vẫn được gửi
