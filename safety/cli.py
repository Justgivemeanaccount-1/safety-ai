"""Chạy thử pipeline trên một luồng: python -m safety.cli --source 0

Mục đích là kiểm chứng module đọc được luồng và tracking giữ được track_id.
Phần luật sự cố nằm ở bước sau, chưa nối vào đây.
"""

from __future__ import annotations

import argparse
import json
import logging
import time

from safety.contracts import FrameResult
from safety.pipeline import SafetyPipeline
from safety.stream import DEFAULT_FPS, FrameSource


def parse_source(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Đọc luồng + tracking, in ra FrameResult")
    p.add_argument("--source", default="0", help="RTSP URL, đường dẫn file, hoặc số hiệu webcam")
    p.add_argument("--camera", default="xuong_han", help="Tên camera, phải trùng tên trong Frigate")
    p.add_argument("--model", default="yolo26n.pt")
    p.add_argument("--device", default="0", help="0 = GPU đầu tiên, cpu = chạy CPU")
    p.add_argument("--fps", type=float, default=DEFAULT_FPS)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--max-frames", type=int, default=0, help="0 = chạy mãi")
    p.add_argument("--json", action="store_true", help="In FrameResult dạng JSON mỗi dòng")
    p.add_argument("--show", action="store_true", help="Mở cửa sổ xem trực tiếp, nhấn Q để dừng sớm")
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
        model=args.model,
        camera=args.camera,
        device=args.device,
        conf=args.conf,
    )
    source = FrameSource(parse_source(args.source), target_fps=args.fps)

    seen_tracks: set[int] = set()
    frames = 0
    started = 0.0
    infer_total = 0.0

    try:
        for ts, frame in source:
            if not frames:
                started = time.time()
            t0 = time.perf_counter()
            result = pipeline.process(ts, frame)
            infer_total += time.perf_counter() - t0
            frames += 1
            seen_tracks.update(d.track_id for d in result.detections if d.track_id is not None)

            if args.json:
                print(json.dumps(result.to_dict(), ensure_ascii=False))
            else:
                print(_summarise(frames, result))

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

    elapsed = time.time() - started if frames else 0.0
    print(
        f"Đã xử lý {frames} khung trong {elapsed:.1f}s "
        f"({frames / elapsed if elapsed else 0:.1f} FPS, không tính lúc nạp model), "
        f"suy luận {1000 * infer_total / frames if frames else 0:.0f}ms/khung, "
        f"{len(seen_tracks)} track_id khác nhau: {sorted(seen_tracks)}"
    )
    return 0


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
