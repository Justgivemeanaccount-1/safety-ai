"""Nối luật với đầu ra: khung hình -> luật -> ảnh chụp -> Frigate.

Một IncidentProcessor cho mỗi camera, giống SafetyPipeline: luật giữ trạng thái
theo track_id của camera đó, trộn hai camera vào một bộ luật sẽ đếm lẫn người.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from safety.contracts import DetectClass, FrameResult, Incident, IncidentLabel
from safety.rules import FireConfig, FireRule, PPEConfig, PPERule

log = logging.getLogger(__name__)

RED = (60, 60, 220)
WHITE = (255, 255, 255)

# Sự cố cháy/khói không gắn với người nào, nên ảnh chụp khoanh mọi hộp lửa/khói trong khung.
_EVIDENCE = {
    IncidentLabel.FIRE: DetectClass.FIRE,
    IncidentLabel.SMOKE: DetectClass.SMOKE,
}


def snapshot_name(incident: Incident) -> str:
    """Tên tệp ảnh: camera_nhãn_giây[_idN]. Hai người cùng vi phạm trong một giây vẫn khác tên."""
    name = f"{incident.camera}_{incident.label.value}_{incident.ts:.0f}"
    if incident.track_id is not None:
        name += f"_id{incident.track_id}"
    return name + ".jpg"


def save_snapshot(
    image: np.ndarray, result: FrameResult, incident: Incident, folder: str | Path
) -> str | None:
    """Lưu khung hình lúc sự cố kèm hộp khoanh bằng chứng. Lỗi thì trả về None, không ném."""
    import cv2

    img = image.copy()
    evidence = _EVIDENCE.get(incident.label)
    for d in result.detections:
        hit = (d.cls is DetectClass.PERSON and d.track_id is not None
               and d.track_id == incident.track_id) or (evidence is not None and d.cls is evidence)
        if not hit:
            continue
        x1, y1, x2, y2 = (int(v) for v in d.bbox.to_list())
        cv2.rectangle(img, (x1, y1), (x2, y2), RED, 2)

    text = f"{incident.label.value}  {incident.sub_label or ''}  {incident.score:.2f}".strip()
    cv2.rectangle(img, (0, 0), (img.shape[1], 24), RED, -1)
    cv2.putText(img, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)

    path = Path(folder) / snapshot_name(incident)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), img):
            raise OSError("cv2.imwrite trả về False")
    except OSError as e:
        log.error("Không lưu được ảnh sự cố %s: %s", path, e)
        return None
    return path.as_posix()


class IncidentProcessor:
    """Chạy cả hai luật trên mỗi khung, chụp ảnh và gửi sự cố đi."""

    def __init__(
        self,
        camera: str,
        publisher=None,
        snapshot_dir: str | Path | None = "snapshots",
        ppe: PPEConfig | None = None,
        fire: FireConfig | None = None,
    ):
        self.camera = camera
        self.publisher = publisher
        self.snapshot_dir = snapshot_dir
        self.ppe = PPERule(camera, ppe or PPEConfig())
        self.fire = FireRule(camera, fire or FireConfig())

    def handle(self, image: np.ndarray, result: FrameResult) -> list[Incident]:
        incidents = self.ppe.update(result) + self.fire.update(result)
        for incident in incidents:
            if self.snapshot_dir is not None:
                incident.snapshot = save_snapshot(image, result, incident, self.snapshot_dir)
            if self.publisher is not None:
                self.publisher.submit(incident)
        return incidents
