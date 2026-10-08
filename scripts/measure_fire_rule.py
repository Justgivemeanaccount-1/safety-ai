r"""Do kha nang chong bao nham cua luat chay/khoi va chon nguong min_hits.

Luat chay/khoi khong dem theo ma dinh danh (lua khong gan voi mot nguoi nao) ma
xet mat do: phai thay o it nhat min_hits trong 10 khung gan nhat. Script nay do
hai thu tren chinh lop FireRule:

  1. Ti le cua so 10 khung dat nguong, khi nguon chi la chop nhay gia xuat hien
     o p phan tram so khung. Do voi cooldown = 0 de thay suc phan biet tho cua
     nguong, khong bi thoi gian cho bao lai lam phang so lieu.
  2. Thoi gian tu luc nguon xuat hien den luc luat bao, voi cooldown that.

Chay:
    .venv\Scripts\python.exe scripts/measure_fire_rule.py
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safety.contracts import BBox, DetectClass, Detection, FrameResult
from safety.rules import FireConfig, FireRule

FLAME = BBox(300, 200, 360, 260)
FPS = 5.0


def frame(ts: float, has_fire: bool) -> FrameResult:
    dets = (Detection(DetectClass.FIRE, FLAME, 0.8),) if has_fire else ()
    return FrameResult(camera="xuong_han", ts=ts, width=640, height=360, detections=dets)


def window_pass_rate(p: float, min_hits: int, frames: int, rng: random.Random) -> float:
    """Ti le cua so 10 khung dat nguong (cooldown = 0 nen moi cua so dat la mot lan bao)."""
    rule = FireRule("xuong_han", FireConfig(min_hits=min_hits, cooldown=0.0))
    count = 0
    for i in range(frames):
        count += len(rule.update(frame(i / FPS, rng.random() < p)))
    return 100.0 * count / frames


def delay_to_alert(p: float, min_hits: int, trials: int, rng: random.Random) -> tuple[float, int]:
    """Trung vi so giay tu khung dau tien den luc bao; tra ve ca so lan khong bao."""
    cap = int(60 * FPS)
    delays: list[float] = []
    misses = 0
    for _ in range(trials):
        rule = FireRule("xuong_han", FireConfig(min_hits=min_hits))
        for i in range(cap):
            if rule.update(frame(i / FPS, rng.random() < p)):
                delays.append(i / FPS)
                break
        else:
            misses += 1
    delays.sort()
    median = delays[len(delays) // 2] if delays else float("nan")
    return median, misses


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=36000, help="so khung moi muc p (36000 = 2 gio)")
    ap.add_argument("--trials", type=int, default=300, help="so lan thu khi do do tre")
    ap.add_argument("--seed", type=int, default=20261008)
    args = ap.parse_args()

    rates = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    thresholds = [4, 6, 8]

    print(f"{args.frames} khung moi o ({args.frames / FPS / 3600:.1f} gio video o {FPS:g} fps), "
          f"{args.trials} lan thu moi o khi do do tre\n")

    print("Ti le cua so 10 khung dat nguong, % (nguon xuat hien o p% so khung)")
    print("    p  " + "".join(f"min_hits={m:<6}" for m in thresholds))
    for p in rates:
        row = f"  {p:.1f}  "
        for m in thresholds:
            rng = random.Random(args.seed + m)
            row += f"{window_pass_rate(p, m, args.frames, rng):<15.1f}"
        print(row)

    print("\nTrung vi thoi gian tu khung dau den luc bao (so lan khong bao trong 60s / "
          f"{args.trials})")
    print("    p  " + "".join(f"min_hits={m:<8}" for m in thresholds))
    for p in rates:
        row = f"  {p:.1f}  "
        for m in thresholds:
            rng = random.Random(args.seed + m)
            median, misses = delay_to_alert(p, m, args.trials, rng)
            cell = "khong bao" if misses == args.trials else f"{median:.1f}s ({misses})"
            row += f"{cell:<17}"
        print(row)


if __name__ == "__main__":
    main()
