"""Chạy YOLO + tracking trên từng khung hình, trả về FrameResult theo contract.

Mỗi camera phải có một SafetyPipeline riêng: tracker giữ trạng thái giữa các
khung, trộn hai luồng vào một pipeline sẽ làm track_id nhảy loạn.
"""

from __future__ import annotations

import logging

import numpy as np
from ultralytics import YOLO

from safety.contracts import BBox, Detection, DetectClass, FrameResult, Keypoint

log = logging.getLogger(__name__)


def _map_classes(names: dict[int, str]) -> dict[int, DetectClass]:
    """Lớp model không có trong DetectClass thì bỏ qua.

    Model COCO mặc định có 80 lớp nhưng ta chỉ quan tâm person; model PPE và
    model cháy của Nam Trường sau này sẽ khớp thêm helmet/vest/fire/smoke.
    """
    mapping = {}
    for idx, name in names.items():
        try:
            mapping[idx] = DetectClass(name)
        except ValueError:
            continue
    return mapping


class SafetyPipeline:
    def __init__(
        self,
        model: str,
        camera: str,
        device: str | int = 0,
        conf: float = 0.25,
        imgsz: int = 640,
        tracker: str = "bytetrack.yaml",
    ):
        self.camera = camera
        self.device = device
        self.conf = conf
        self.imgsz = imgsz
        self.tracker = tracker
        self.model = YOLO(model)
        self.classes = _map_classes(self.model.names)
        log.info(
            "Model %s: dùng %d/%d lớp -> %s",
            model,
            len(self.classes),
            len(self.model.names),
            sorted(c.value for c in self.classes.values()),
        )

    def process(self, ts: float, frame: np.ndarray) -> FrameResult:
        results = self.model.track(
            frame,
            persist=True,
            tracker=self.tracker,
            device=self.device,
            conf=self.conf,
            imgsz=self.imgsz,
            verbose=False,
        )
        height, width = frame.shape[:2]
        return FrameResult(
            camera=self.camera,
            ts=ts,
            width=width,
            height=height,
            detections=self._detections(results[0]),
        )

    def _detections(self, result) -> tuple[Detection, ...]:
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return ()

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        cls_idx = boxes.cls.cpu().numpy().astype(int)
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else None
        kps = result.keypoints.data.cpu().numpy() if result.keypoints is not None else None

        out = []
        for i, idx in enumerate(cls_idx):
            cls = self.classes.get(idx)
            if cls is None:
                continue
            out.append(
                Detection(
                    cls=cls,
                    bbox=BBox.from_list(xyxy[i]),
                    conf=float(confs[i]),
                    track_id=int(ids[i]) if ids is not None else None,
                    keypoints=_keypoints(kps[i]) if kps is not None else None,
                )
            )
        return tuple(out)


def _keypoints(raw: np.ndarray) -> tuple[Keypoint, ...]:
    return tuple(Keypoint(float(x), float(y), float(c)) for x, y, c in raw)
