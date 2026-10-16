"""Chạy thử cả đường đi của sự cố: luồng Frigate -> nhận diện -> luật -> ảnh -> Frigate.

    python scripts/demo_incident_flow.py --seconds 40

Đọc luồng restream thật của Frigate, nhận diện người thật, rồi chèn nhãn giả lập
"không mũ" lên đầu mỗi người và một hộp "lửa" cố định, vì chưa có model PPE và
model cháy. Từ đó trở đi mọi thứ là đường thật mà safety.cli dùng: hai luật,
chụp ảnh, gửi Frigate ở luồng nền. Cuối cùng hỏi lại Frigate xem sự cố có thật
nằm trong đó và có đoạn ghi hình không.

Phần giả lập chỉ nằm trong script này, không lọt vào safety/. Model nào đã có lớp
no_helmet hay fire thì script tự bỏ phần giả lập tương ứng.
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from demo_fire_rule import FIRE_AT, box_of
from demo_ppe_rule import fake_no_helmet

from safety.contracts import Detection, DetectClass, FrameResult, Incident
from safety.frigate import FrigateClient, FrigatePublisher
from safety.incidents import IncidentProcessor
from safety.pipeline import SafetyPipeline
from safety.stream import FrameSource

log = logging.getLogger("demo")


def inject(result: FrameResult, fake_ppe: bool, fake_fire: bool) -> FrameResult:
    extra = []
    if fake_ppe:
        extra += [fake_no_helmet(d) for d in result.detections
                  if d.cls is DetectClass.PERSON and d.track_id is not None]
    if fake_fire:
        extra.append(Detection(DetectClass.FIRE, box_of(FIRE_AT, result.width, result.height), 0.80))
    if not extra:
        return result
    return FrameResult(result.camera, result.ts, result.width, result.height,
                       tuple(result.detections) + tuple(extra))


def verify(api: str, incidents: list[Incident]) -> int:
    """Hỏi lại Frigate từng sự cố đã gửi. Trả về số sự cố tìm thấy kèm đoạn ghi hình."""
    ok = 0
    for inc in incidents:
        if not inc.frigate_event_id:
            print(f"  {inc.label.value:<10} KHONG gui duoc sang Frigate")
            continue
        r = requests.get(f"{api}/events/{inc.frigate_event_id}", timeout=5)
        if r.status_code != 200:
            print(f"  {inc.label.value:<10} {inc.frigate_event_id}: Frigate tra {r.status_code}")
            continue
        ev = r.json()
        clip = requests.head(f"{api}/events/{inc.frigate_event_id}/clip.mp4", timeout=10)
        has_clip = ev.get("has_clip") and clip.status_code == 200
        ok += bool(has_clip)
        length = (ev["end_time"] - ev["start_time"]) if ev.get("end_time") else None
        print(f"  {ev['label']:<10} sub_label={ev.get('sub_label')!s:<22} "
              f"score={ev.get('data', {}).get('top_score', ev.get('top_score'))}  "
              f"ghi_hinh={'CO' if has_clip else 'KHONG'}  "
              f"dai={f'{length:.0f}s' if length else 'dang mo'}  id={ev['id']}")
    return ok


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="rtsp://127.0.0.1:8554/xuong_han_sub")
    p.add_argument("--camera", default="xuong_han")
    p.add_argument("--frigate", default="http://127.0.0.1:5000/api")
    p.add_argument("--model", default="yolo26n.pt")
    p.add_argument("--device", default="0")
    p.add_argument("--fps", type=float, default=5.0)
    p.add_argument("--seconds", type=float, default=40.0)
    p.add_argument("--snapshots", default="snapshots")
    p.add_argument("--verify-wait", type=float, default=30.0,
                   help="Cho Frigate dong su co (duration 20s) va ghi xong doan video roi moi kiem")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    pipeline = SafetyPipeline(model=args.model, camera=args.camera, device=args.device)
    have = set(pipeline.classes.values())
    fake_ppe = DetectClass.NO_HELMET not in have
    fake_fire = DetectClass.FIRE not in have
    print(f"gia lap: khong mu={'CO' if fake_ppe else 'khong'}, lua={'CO' if fake_fire else 'khong'}")

    client = FrigateClient(args.frigate)
    cameras = client.cameras()
    if cameras is None:
        # Giống safety.cli: Frigate tắt thì vẫn chạy, để thử luôn trường hợp Frigate sập.
        print(f"KHONG goi duoc Frigate o {args.frigate}, van chay tiep")
    elif args.camera not in cameras:
        print(f"Frigate khong co camera {args.camera} (dang co: {sorted(cameras)})")
        return 1

    sent: list[Incident] = []
    publisher = FrigatePublisher(client, on_done=sent.append)
    processor = IncidentProcessor(args.camera, publisher=publisher, snapshot_dir=args.snapshots)

    found: list[Incident] = []
    frames, slowest_handle = 0, 0.0
    deadline = time.time() + args.seconds
    for ts, frame in FrameSource(args.source, target_fps=args.fps):
        result = inject(pipeline.process(ts, frame), fake_ppe, fake_fire)
        t0 = time.perf_counter()
        for inc in processor.handle(frame, result):
            found.append(inc)
            print(f"[{time.strftime('%H:%M:%S')}] SU CO {inc.label.value} ({inc.severity.value}) "
                  f"{inc.sub_label}  anh={inc.snapshot}")
        slowest_handle = max(slowest_handle, time.perf_counter() - t0)
        frames += 1
        if time.time() >= deadline:
            break

    loop_seconds = time.time() - (deadline - args.seconds)
    publisher.close()
    print(f"\n{frames} khung trong {loop_seconds:.1f}s ({frames / loop_seconds:.1f} khung/giay), "
          f"{len(found)} su co; gui Frigate: {publisher.sent} thanh cong, {publisher.failed} loi, "
          f"{publisher.dropped} bo do hang doi day, {publisher.unsent} chua gui kip luc dung")
    print(f"buoc luat+chup anh+dua vao hang doi cham nhat: {1000 * slowest_handle:.1f} ms/khung")

    print(f"\ncho {args.verify_wait:.0f}s de Frigate dong su co va ghi xong doan video...")
    time.sleep(args.verify_wait)
    print("Kiem tra lai trong Frigate:")
    ok = verify(args.frigate, sent)
    print(f"\n{ok}/{len(found)} su co nam trong Frigate kem doan ghi hinh")
    return 0 if found and ok == len(found) else 1


if __name__ == "__main__":
    raise SystemExit(main())
