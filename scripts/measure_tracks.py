"""Đo độ ổn định của track_id trên một luồng, trước khi viết luật tính theo thời gian.

Luật PPE đòi "thiếu mũ kéo dài >= 3 giây" nên nó chỉ chạy được nếu tracker giữ
được cùng một track_id suốt 3 giây. Script đo xem thực tế có giữ được không.

    python scripts/measure_tracks.py --source rtsp://127.0.0.1:8554/xuong_han_sub --seconds 180

Video giả lập phát lặp, mỗi vòng là một lần cảnh nhảy đột ngột nên tracker mất dấu —
đó là lỗi của cách kiểm thử, không phải của tracker. Script dò thời điểm video quay
vòng bằng cách so từng khung với khung đầu của file video, rồi tách riêng hai loại
đứt đoạn. (Không so hai khung liên tiếp với nhau được: người đi ngang camera gây
độ lệch ngang bằng lúc quay vòng.)
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict

import cv2
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from safety.contracts import DetectClass
from safety.pipeline import SafetyPipeline
from safety.stream import FrameSource

RESTART_THRESHOLD = 5.0
RESTART_MIN_SPACING = 10


def thumbnail(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)


def first_frame_of(path: str) -> np.ndarray | None:
    cap = cv2.VideoCapture(path)
    ok, frame = cap.read()
    cap.release()
    return thumbnail(frame) if ok else None


def segments(frames: list[int], gap_tolerance: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = prev = frames[0]
    for f in frames[1:]:
        if f - prev > gap_tolerance + 1:
            out.append((start, prev))
            start = f
        prev = f
    out.append((start, prev))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="rtsp://127.0.0.1:8554/xuong_han_sub")
    p.add_argument("--camera", default="xuong_han")
    p.add_argument("--model", default="yolo26n.pt")
    p.add_argument("--device", default="0")
    p.add_argument("--fps", type=float, default=5.0)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--seconds", type=float, default=180.0)
    p.add_argument("--loop-video", default="data/samples/xuong_han.mp4",
                   help="File video mà camera giả lập đang phát lặp, để dò lúc quay vòng")
    args = p.parse_args()

    pipeline = SafetyPipeline(model=args.model, camera=args.camera, device=args.device, conf=args.conf)
    seen: dict[int, list[int]] = defaultdict(list)
    cuts: list[int] = []
    ts0 = None
    idx = 0
    frames_with_person = 0
    reference = first_frame_of(args.loop_video)
    if reference is None:
        print(f"canh bao: khong doc duoc {args.loop_video}, bo qua phan do vong lap")

    for ts, frame in FrameSource(args.source, target_fps=args.fps):
        if ts0 is None:
            ts0 = ts
        if ts - ts0 > args.seconds:
            break

        if reference is not None:
            near_start = float(np.abs(thumbnail(frame) - reference).mean()) < RESTART_THRESHOLD
            if near_start and (not cuts or idx - cuts[-1] >= RESTART_MIN_SPACING):
                cuts.append(idx)

        result = pipeline.process(ts, frame)
        people = [d for d in result.detections if d.cls is DetectClass.PERSON and d.track_id]
        if people:
            frames_with_person += 1
        for d in people:
            seen[d.track_id].append(idx)
        idx += 1

    if not idx:
        print("khong doc duoc khung nao")
        return 1

    spf = 1.0 / args.fps
    print(f"\n{idx} khung trong {args.seconds:.0f}s, {frames_with_person} khung co nguoi, "
          f"{len(cuts)} lan video quay vong")

    # Vòng đời một mã: từ lần thấy đầu tới lần thấy cuối, kèm tỉ lệ khung thực sự
    # thấy trong quãng đó. Mã sống lâu mà tỉ lệ thấp nghĩa là tracker giữ đúng người,
    # chỉ có phát hiện bị ngắt quãng (bị kệ hàng che) — luật phải chịu được lỗ hổng
    # đó thay vì đòi thấy liên tục.
    spans = [(max(f) - min(f) + 1) * spf for f in seen.values()]
    covers = [len(f) / (max(f) - min(f) + 1) for f in seen.values()]
    long_lived = sum(1 for s in spans if s >= 3.0)
    print(
        f"\nVong doi ma dinh danh (tu lan thay dau toi lan thay cuoi):"
        f"\n  dai nhat {max(spans):.1f}s, trung vi {statistics.median(spans):.1f}s"
        f"\n  {long_lived}/{len(spans)} ma song >= 3 giay ({100 * long_lived / len(spans):.0f}%)"
        f"\n  ti le khung thuc su thay duoc trong vong doi: trung vi {100 * statistics.median(covers):.0f}%"
    )

    for tol in (0, 2):
        segs = [s for frames in seen.values() for s in segments(frames, tol)]
        durs = sorted((e - s + 1) * spf for s, e in segs)
        ends_at_cut = sum(1 for s, e in segs if any(abs(c - e) <= 2 for c in cuts))
        long_enough = sum(1 for d in durs if d >= 3.0)
        print(
            f"\nBo qua toi da {tol} khung mat dau:"
            f"\n  {len(seen)} track_id khac nhau, {len(segs)} doan lien tuc"
            f"\n  dai nhat {durs[-1]:.1f}s, trung vi {statistics.median(durs):.1f}s"
            f"\n  {long_enough}/{len(segs)} doan dat >= 3 giay ({100 * long_enough / len(segs):.0f}%)"
            f"\n  {ends_at_cut}/{len(segs)} doan ket thuc ngay luc video quay vong (loi cua cach kiem thu)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
