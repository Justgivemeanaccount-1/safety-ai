"""Chạy luật PPE trên video và chụp lại 3 khoảnh khắc: đang đếm, sắp đủ, bắn sự cố.

    python scripts/demo_ppe_rule.py --out data/demo_ppe.jpg

Dùng để minh hoạ luật cho báo cáo khi chưa có model PPE. Hộp "không đội mũ" là
giả lập đặt vào giữa vùng đầu; người, mã định danh, nhịp thời gian và toàn bộ
logic luật đều là thật. Khi có model của Nam Trường thì bỏ phần giả lập đi.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from safety.contracts import BBox, Detection, DetectClass, FrameResult, IncidentLabel
from safety.pipeline import SafetyPipeline
from safety.rules import PPERule, head_region
from safety.stream import FrameSource

GREEN = (76, 175, 80)
AMBER = (0, 170, 255)
RED = (60, 60, 220)
WHITE = (255, 255, 255)
DARK = (35, 35, 40)


def fake_no_helmet(person: Detection) -> Detection:
    head = head_region(person.bbox, 0.25)
    cx, cy = (head.x1 + head.x2) / 2, (head.y1 + head.y2) / 2
    w, h = head.width * 0.5, head.height * 0.6
    return Detection(
        DetectClass.NO_HELMET, BBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 0.83
    )


def label(img: np.ndarray, text: str, x: int, y: int, color) -> None:
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    y = max(y, th + 6)
    cv2.rectangle(img, (x, y - th - 5), (x + tw + 8, y + 4), color, -1)
    cv2.putText(img, text, (x + 4, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)


def draw(frame, result, rule, incidents, caption):
    img = frame.copy()
    for d in result.detections:
        if d.cls is not DetectClass.PERSON or d.track_id is None:
            continue
        streak = rule.streak_of(d.track_id, IncidentLabel.NO_HELMET)
        elapsed = (result.ts - streak.since) if streak and streak.since else 0.0
        fired = any(i.track_id == d.track_id for i in incidents)
        color = RED if fired else (AMBER if elapsed > 0 else GREEN)

        x1, y1, x2, y2 = (int(v) for v in d.bbox.to_list())
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        head = head_region(d.bbox, 0.25)
        cv2.rectangle(img, (int(head.x1), int(head.y1)), (int(head.x2), int(head.y2)), color, 1)
        label(img, f"id={d.track_id}  thieu mu {elapsed:.1f}s", x1, y1 - 6, color)

    h, w = img.shape[:2]
    cv2.rectangle(img, (0, 0), (w, 24), DARK, -1)
    cv2.putText(img, caption, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)
    if incidents:
        inc = incidents[0]
        bar = f"SU CO: {inc.label.value}  {inc.sub_label}  muc {inc.severity.value}  score {inc.score:.2f}"
        cv2.rectangle(img, (0, h - 26), (w, h), RED, -1)
        cv2.putText(img, bar, (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)
    return img


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="data/samples/xuong_han.mp4")
    p.add_argument("--out", default="data/demo_ppe.jpg")
    p.add_argument("--model", default="yolo26n.pt")
    p.add_argument("--device", default="0")
    p.add_argument("--fps", type=float, default=5.0)
    args = p.parse_args()

    pipeline = SafetyPipeline(model=args.model, camera="xuong_han", device=args.device)
    rule = PPERule("xuong_han")
    shots = []

    for ts, frame in FrameSource(args.source, target_fps=args.fps):
        result = pipeline.process(ts, frame)
        people = [d for d in result.detections if d.cls is DetectClass.PERSON and d.track_id]
        result = FrameResult(
            result.camera, result.ts, result.width, result.height,
            tuple(result.detections) + tuple(fake_no_helmet(x) for x in people),
        )
        incidents = rule.update(result)

        longest = 0.0
        for person in people:
            s = rule.streak_of(person.track_id, IncidentLabel.NO_HELMET)
            if s and s.since:
                longest = max(longest, result.ts - s.since)

        if incidents:
            shots.append(draw(frame, result, rule, incidents, "3. Du 3 giay -> luat ban ra su co"))
            break
        if not shots and longest >= 0.8:
            shots.append(draw(frame, result, rule, incidents, "1. Bat dau dem gio"))
        elif len(shots) == 1 and longest >= 2.2:
            shots.append(draw(frame, result, rule, incidents, "2. Sap du nguong, chua bao"))

    if len(shots) < 3:
        print(f"chi chup duoc {len(shots)}/3 khung — thu video dai hon")
        return 1

    strip = cv2.vconcat(
        [cv2.copyMakeBorder(s, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=WHITE) for s in shots]
    )
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, strip)
    print(f"da luu {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
