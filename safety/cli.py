"""Chạy module trên một luồng: python -m safety.cli --source 0

Mỗi khung đi qua nhận diện + tracking, rồi qua luật đồ bảo hộ và luật cháy/khói.
Sự cố được chụp ảnh vào thư mục snapshots/. Có --frigate thì đẩy sang Frigate để
xem lại kèm đoạn ghi hình; có --telegram thì gửi tiếp vào nhóm Telegram chung
(mã bot và chat id lấy từ .env):

    python -m safety.cli --source rtsp://127.0.0.1:8554/xuong_han_sub \\
        --camera xuong_han --frigate http://127.0.0.1:5000/api --telegram
"""

from __future__ import annotations

import argparse
import json
import logging
import time

from safety.contracts import FrameResult
from safety.incidents import IncidentProcessor
from safety.outputs import build_outputs
from safety.pipeline import SafetyPipeline
from safety.stream import DEFAULT_FPS, FrameSource

log = logging.getLogger("safety.cli")


def parse_source(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Đọc luồng + tracking + luật, đẩy sự cố sang Frigate")
    p.add_argument("--source", default="0", help="RTSP URL, đường dẫn file, hoặc số hiệu webcam")
    p.add_argument("--camera", default="xuong_han", help="Tên camera, phải trùng tên trong Frigate")
    p.add_argument("--model", default="yolo26n.pt")
    p.add_argument("--extra-model", action="append", default=[], metavar="PATH",
                   help="Mô hình phụ chạy song song, không bám vết, vd models/fire_smoke_v0.pt (lặp lại được)")
    p.add_argument("--device", default="0", help="0 = GPU đầu tiên, cpu = chạy CPU")
    p.add_argument("--fps", type=float, default=DEFAULT_FPS)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--max-frames", type=int, default=0, help="0 = chạy mãi")
    p.add_argument("--json", action="store_true", help="In FrameResult dạng JSON mỗi dòng")
    p.add_argument("--show", action="store_true", help="Mở cửa sổ xem trực tiếp, nhấn Q để dừng sớm")
    p.add_argument("--frigate", default=None,
                   help="Địa chỉ API Frigate, vd http://127.0.0.1:5000/api. Bỏ trống = không gửi")
    p.add_argument("--snapshots", default="snapshots", help="Thư mục lưu ảnh sự cố")
    p.add_argument("--telegram", action="store_true",
                   help="Gửi sự cố vào nhóm Telegram chung (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID trong .env)")
    return p


def draw(frame, result):
    import cv2

    for d in result.detections:
        x1, y1, x2, y2 = (int(v) for v in d.bbox.to_list())
        cv2.rectangle(frame, (x1, y1), (x2, y2), (76, 175, 80), 2)
        text = f"{d.cls.value}#{d.track_id} {d.conf:.2f}"
        cv2.putText(frame, text, (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (76, 175, 80), 1, cv2.LINE_AA)
    cv2.imshow("safety-ai", frame)
    return cv2.waitKey(1) & 0xFF == ord("q")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    pipeline = SafetyPipeline(
        extra_models=args.extra_model,
        model=args.model,
        camera=args.camera,
        device=args.device,
        conf=args.conf,
    )
    source = FrameSource(parse_source(args.source), target_fps=args.fps)
    outputs = build_outputs(args.frigate, args.camera, telegram=args.telegram)
    processor = IncidentProcessor(args.camera, publisher=outputs, snapshot_dir=args.snapshots)

    seen_tracks: set[int] = set()
    frames = 0
    incidents = 0
    started = 0.0
    infer_ms: list[float] = []

    try:
        for ts, frame in source:
            if not frames:
                started = time.time()
            t0 = time.perf_counter()
            result = pipeline.process(ts, frame)
            infer_ms.append(1000 * (time.perf_counter() - t0))
            frames += 1
            seen_tracks.update(d.track_id for d in result.detections if d.track_id is not None)

            if args.json:
                print(json.dumps(result.to_dict(), ensure_ascii=False))
            else:
                print(_summarise(frames, result))

            for incident in processor.handle(frame, result):
                incidents += 1
                log.warning("SỰ CỐ %s [%s] %s score %.2f, ảnh %s", incident.label.value,
                            incident.severity.vi, incident.sub_label or "", incident.score,
                            incident.snapshot)

            if args.show and draw(frame, result):
                break
            if args.max_frames and frames >= args.max_frames:
                break
    except KeyboardInterrupt:
        print()
    finally:
        if args.show:
            import cv2

            cv2.destroyAllWindows()
        outputs.close()

    elapsed = time.time() - started if frames else 0.0
    print(
        f"Đã xử lý {frames} khung trong {elapsed:.1f}s "
        f"({frames / elapsed if elapsed else 0:.1f} FPS, không tính lúc nạp model), "
        f"{len(seen_tracks)} track_id khác nhau: {sorted(seen_tracks)}"
    )
    print(_speed(infer_ms))
    print(f"{incidents} sự cố; {outputs.summary()}")
    return 0


# Vài khung đầu chậm hơn hẳn vì GPU còn khởi động (khung đầu tiên ~2 giây).
# Tính chung vào trung bình thì một lần chạy 40 khung ra ~75 ms thay vì ~20 ms:
# chính lỗi này từng làm nhóm tin con số 71 ms/khung ở tuần 2.
WARMUP_FRAMES = 5


def _speed(infer_ms: list[float]) -> str:
    if not infer_ms:
        return "Chưa xử lý khung nào"
    steady = sorted(infer_ms[WARMUP_FRAMES:])
    if not steady:
        return f"Suy luận: mới có {len(infer_ms)} khung, toàn là khung khởi động GPU, chưa đo được tốc độ ổn định"
    return (f"Suy luận: khung đầu {infer_ms[0]:.0f} ms (GPU khởi động); "
            f"bỏ {WARMUP_FRAMES} khung đầu thì trung vị {steady[len(steady) // 2]:.0f} ms/khung, "
            f"95% số khung dưới {steady[min(len(steady) - 1, int(0.95 * len(steady)))]:.0f} ms")


def _summarise(n: int, result: FrameResult) -> str:
    if not result.detections:
        return f"[{n:4d}] {time.strftime('%H:%M:%S', time.localtime(result.ts))}  (khong co gi)"
    parts = [
        f"{d.cls.value}#{d.track_id} {d.conf:.2f}" for d in result.detections
    ]
    return (
        f"[{n:4d}] {time.strftime('%H:%M:%S', time.localtime(result.ts))}  "
        f"{len(result.detections)} vật thể: " + "  ".join(parts)
    )


if __name__ == "__main__":
    raise SystemExit(main())
