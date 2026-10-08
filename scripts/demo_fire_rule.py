"""Chạy luật cháy trên video và chụp lại 4 khoảnh khắc minh hoạ cơ chế của luật.

    python scripts/demo_fire_rule.py --out data/demo_fire.jpg

Ba khung đầu cho thấy cửa sổ 10 khung điền dần tới ngưỡng 6/10 rồi bắn sự cố,
kể cả khi có một khung bị mất dấu. Khung thứ tư cho thấy hộp nằm trong vùng
loại trừ thì dù thấy đủ 10/10 khung vẫn không báo.

Hộp "lửa" là giả lập vì chưa có model cháy; khung hình, nhịp thời gian, phần
nhận diện người và toàn bộ logic luật đều là thật. Khi model của Nam Trường có
lớp fire thì script tự bỏ phần giả lập và chạy bằng kết quả nhận diện thật.
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
from safety.rules import ExcludeZone, FireConfig, FireRule
from safety.stream import FrameSource

GREEN = (76, 175, 80)
AMBER = (0, 170, 255)
RED = (60, 60, 220)
BLUE = (200, 130, 20)
WHITE = (255, 255, 255)
GREY = (120, 120, 120)
DARK = (35, 35, 40)

# Chỗ đặt hộp lửa giả lập và vùng loại trừ, toạ độ tỉ lệ để đổi video vẫn đúng chỗ.
FIRE_AT = (0.08, 0.55, 0.24, 0.82)
LAMP_AT = (0.88, 0.06, 0.97, 0.21)
LAMP_ZONE = ExcludeZone(0.85, 0.03, 1.0, 0.25, "den bao")

# Bốn khung đầu chưa có lửa, để cửa sổ kịp đầy 10 ô trước lúc luật bắn.
START_AT = 4
# Một khung giữa chừng không thấy lửa: lửa bị khói che một nhịp. Luật vẫn phải đạt 6/10.
GAP_AT = 7


def box_of(rel: tuple[float, float, float, float], width: int, height: int) -> BBox:
    x1, y1, x2, y2 = rel
    return BBox(x1 * width, y1 * height, x2 * width, y2 * height)


def label(img: np.ndarray, text: str, x: int, y: int, color, scale: float = 0.45) -> None:
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    y = max(y, th + 6)
    cv2.rectangle(img, (x, y - th - 5), (x + tw + 8, y + 4), color, -1)
    cv2.putText(img, text, (x + 4, y), cv2.FONT_HERSHEY_SIMPLEX, scale, WHITE, 1, cv2.LINE_AA)


def dashed_rect(img: np.ndarray, box: BBox, color, step: int = 9) -> None:
    x1, y1, x2, y2 = (int(v) for v in box.to_list())
    for x in range(x1, x2, step * 2):
        cv2.line(img, (x, y1), (min(x + step, x2), y1), color, 2)
        cv2.line(img, (x, y2), (min(x + step, x2), y2), color, 2)
    for y in range(y1, y2, step * 2):
        cv2.line(img, (x1, y), (x1, min(y + step, y2)), color, 2)
        cv2.line(img, (x2, y), (x2, min(y + step, y2)), color, 2)


def window_strip(img: np.ndarray, hits: list[float], min_hits: int, fired: bool) -> None:
    """Vẽ 10 ô cửa sổ trượt: ô đặc là khung thấy lửa, ô rỗng là khung không thấy."""
    h = img.shape[0]
    cell, pad, y = 16, 4, h - 58
    seen = sum(1 for c in hits if c > 0)
    for i in range(10):
        x = 8 + i * (cell + pad)
        if i >= len(hits):
            # Ô cửa sổ chưa dùng tới: để rỗng, đừng vẽ giống ô "khung không thấy lửa".
            cv2.rectangle(img, (x, y), (x + cell, y + cell), GREY, 1)
            continue
        color = (RED if fired else AMBER) if hits[i] > 0 else DARK
        cv2.rectangle(img, (x, y), (x + cell, y + cell), color, -1)
        cv2.rectangle(img, (x, y), (x + cell, y + cell), GREY, 1)
    text = f"cua so: {seen}/{len(hits)} khung co lua  -  can {min_hits}"
    cv2.putText(img, text, (8 + 10 * (cell + pad) + 6, y + cell - 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)


def draw(frame, result, hits, min_hits, incidents, caption, zone: ExcludeZone | None, faked: bool):
    img = frame.copy()
    h, w = img.shape[:2]

    if zone is not None:
        box = zone.to_bbox(w, h)
        cv2.rectangle(img, (int(box.x1), int(box.y1)), (int(box.x2), int(box.y2)), BLUE, 2)
        label(img, f"vung loai tru: {zone.ten}", int(box.x1), int(box.y2) + 16, BLUE, 0.4)

    for d in result.detections:
        if d.cls is DetectClass.PERSON:
            x1, y1, x2, y2 = (int(v) for v in d.bbox.to_list())
            cv2.rectangle(img, (x1, y1), (x2, y2), GREEN, 1)
            if d.track_id is not None:
                label(img, f"nguoi id={d.track_id}", x1, y1 - 6, GREEN, 0.4)
        elif d.cls is DetectClass.FIRE:
            dashed_rect(img, d.bbox, RED if incidents else AMBER)
            tag = "'lua' GIA LAP" if faked else "lua"
            label(img, f"{tag} conf {d.conf:.2f}", int(d.bbox.x1), int(d.bbox.y1) - 6,
                  RED if incidents else AMBER, 0.4)

    window_strip(img, hits, min_hits, bool(incidents))

    cv2.rectangle(img, (0, 0), (w, 24), DARK, -1)
    cv2.putText(img, caption, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)

    bar, color = "chua bao", DARK
    if incidents:
        inc = incidents[0]
        bar = (f"SU CO: {inc.label.value}  {inc.sub_label}  "
               f"muc {inc.severity.value}  score {inc.score:.2f}")
        color = RED
    cv2.rectangle(img, (0, h - 26), (w, h), color, -1)
    cv2.putText(img, bar, (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)
    return img


def run_pass(args, pipeline, faked: bool, zone: ExcludeZone | None, at: tuple, frames: int):
    """Chạy luật qua `frames` khung, trả về danh sách (ảnh, chỉ số khung, có sự cố)."""
    config = FireConfig(exclude=(zone,)) if zone is not None else FireConfig()
    rule = FireRule("xuong_han", config)
    shots = []
    for idx, (ts, frame) in enumerate(FrameSource(args.source, target_fps=args.fps)):
        if idx < args.skip:
            continue
        step = idx - args.skip
        if step >= frames:
            break
        has_fire = zone is not None or (step >= START_AT and step != GAP_AT)
        result = pipeline.process(ts, frame)
        if faked and has_fire:
            box = box_of(at, result.width, result.height)
            result = FrameResult(
                result.camera, result.ts, result.width, result.height,
                tuple(result.detections) + (Detection(DetectClass.FIRE, box, 0.80),),
            )
        incidents = rule.update(result)
        window = rule.window_of(IncidentLabel.FIRE)
        # Chụp lại trạng thái cửa sổ ngay tại khung này: luật là một đối tượng
        # duy nhất bị sửa liên tục, đọc nó sau vòng lặp sẽ ra trạng thái cuối.
        hits = list(window.hits) if window is not None else []
        shots.append((frame, result, hits, rule.config.min_hits, incidents, step, ts))
        if incidents and zone is None:
            break
    return shots


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="data/samples/xuong_han.mp4")
    p.add_argument("--out", default="data/demo_fire.jpg")
    p.add_argument("--model", default="yolo26n.pt")
    p.add_argument("--device", default="0")
    p.add_argument("--fps", type=float, default=5.0)
    # Tu khung 20 tro di video co 3 nguoi trong khung, de anh demo cho thay
    # phan nhan dien nguoi that chay song song voi hop lua gia lap.
    p.add_argument("--skip", type=int, default=20,
                   help="Bo qua may khung dau, de chon doan video co nguoi trong khung")
    args = p.parse_args()

    pipeline = SafetyPipeline(model=args.model, camera="xuong_han", device=args.device)
    # Model da nhan dien duoc lua thi khong chen gia lap nua.
    faked = DetectClass.FIRE not in pipeline.classes.values()
    print("che do GIA LAP: hop lua do script chen vao" if faked
          else "che do THAT: model da co lop fire, khong chen gia lap")

    normal = run_pass(args, pipeline, faked, None, FIRE_AT, frames=30)
    if not normal or not normal[-1][4]:
        print("luat khong ban ra su co — kiem tra lai video hoac tham so")
        return 1

    fired_at = normal[-1][5]
    delay = (fired_at - START_AT) / args.fps
    want = {GAP_AT - 1: "1. Cua so dien dan, chua du mat do",
            GAP_AT: "2. Mot khung mat dau, nhung cua so khong bi xoa",
            fired_at: f"3. Du 6 khung co lua -> ban su co sau {delay:.1f}s"}
    panels = [draw(f, r, h, m, i, want[k], None, faked)
              for (f, r, h, m, i, k, _) in normal if k in want]

    lamp = run_pass(args, pipeline, faked, LAMP_ZONE, LAMP_AT, frames=10)
    f, r, h, m, i, _, _ = lamp[-1]
    panels.append(draw(f, r, h, m, i, "4. Hop nam trong vung loai tru -> khong bao", LAMP_ZONE, faked))

    if len(panels) != 4:
        print(f"chi dung duoc {len(panels)}/4 khung")
        return 1

    bordered = [cv2.copyMakeBorder(x, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=WHITE)
                for x in panels]
    grid = cv2.vconcat([cv2.hconcat(bordered[:2]), cv2.hconcat(bordered[2:])])
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, grid)
    print(f"da luu {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
