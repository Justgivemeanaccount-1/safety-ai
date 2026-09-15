"""Định dạng dữ liệu dùng chung giữa các phần của hệ thống.

Chốt tuần 1. Frigate, module AI, Telegram, SQLite và dashboard Streamlit đều
đọc theo file này — đổi field ở đây là đổi hợp đồng của cả nhóm.
Giải thích đầy đủ: docs/data-contract.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DetectClass(str, Enum):
    """Lớp model YOLO trả về (AI -> luật)."""

    PERSON = "person"
    HELMET = "helmet"
    NO_HELMET = "no_helmet"
    VEST = "vest"
    NO_VEST = "no_vest"
    FIRE = "fire"
    SMOKE = "smoke"


class IncidentLabel(str, Enum):
    """Nhãn sự cố (luật -> Frigate / Telegram / DB).

    Giá trị phải trùng đúng chữ với label khai trong Frigate, vì nó đi thẳng
    vào URL POST /api/events/<camera>/<label>/create.
    """

    NO_HELMET = "no_helmet"
    NO_VEST = "no_vest"
    FIRE = "fire"
    SMOKE = "smoke"
    FALL = "fall"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"

    @property
    def vi(self) -> str:
        return _SEVERITY_VI[self]


_SEVERITY_VI = {
    Severity.CRITICAL: "Nghiêm trọng",
    Severity.HIGH: "Cao",
    Severity.MEDIUM: "Trung bình",
}

DEFAULT_SEVERITY: dict[IncidentLabel, Severity] = {
    IncidentLabel.FALL: Severity.CRITICAL,
    IncidentLabel.FIRE: Severity.CRITICAL,
    IncidentLabel.SMOKE: Severity.HIGH,
    IncidentLabel.NO_HELMET: Severity.HIGH,
    IncidentLabel.NO_VEST: Severity.MEDIUM,
}

COCO_KEYPOINTS = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)


@dataclass(frozen=True)
class BBox:
    """Pixel trên khung đã resize để detect, gốc toạ độ ở góc trên trái."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def to_list(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]

    @staticmethod
    def from_list(values) -> BBox:
        x1, y1, x2, y2 = (float(v) for v in values)
        return BBox(x1, y1, x2, y2)


@dataclass(frozen=True)
class Keypoint:
    x: float
    y: float
    conf: float


@dataclass(frozen=True)
class Detection:
    """Một vật thể trong một khung hình. Tương ứng {track_id, class, bbox, conf, keypoints}."""

    cls: DetectClass
    bbox: BBox
    conf: float
    track_id: int | None = None
    keypoints: tuple[Keypoint, ...] | None = None

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "cls": self.cls.value,
            "bbox": self.bbox.to_list(),
            "conf": self.conf,
            "keypoints": (
                [[k.x, k.y, k.conf] for k in self.keypoints] if self.keypoints else None
            ),
        }

    @staticmethod
    def from_dict(d: dict) -> Detection:
        kps = d.get("keypoints")
        return Detection(
            cls=DetectClass(d["cls"]),
            bbox=BBox.from_list(d["bbox"]),
            conf=float(d["conf"]),
            track_id=d.get("track_id"),
            keypoints=tuple(Keypoint(*map(float, k)) for k in kps) if kps else None,
        )


@dataclass(frozen=True)
class FrameResult:
    """Kết quả một khung hình của một camera. Đơn vị mà luật nhận vào."""

    camera: str
    ts: float
    width: int
    height: int
    detections: tuple[Detection, ...] = ()

    def of(self, *classes: DetectClass) -> tuple[Detection, ...]:
        return tuple(d for d in self.detections if d.cls in classes)

    def to_dict(self) -> dict:
        return {
            "camera": self.camera,
            "ts": self.ts,
            "width": self.width,
            "height": self.height,
            "detections": [d.to_dict() for d in self.detections],
        }

    @staticmethod
    def from_dict(d: dict) -> FrameResult:
        return FrameResult(
            camera=d["camera"],
            ts=float(d["ts"]),
            width=int(d["width"]),
            height=int(d["height"]),
            detections=tuple(Detection.from_dict(x) for x in d.get("detections", [])),
        )


@dataclass
class Incident:
    """Một sự cố đã qua luật. Tương ứng {camera, label, sub_label, severity, score, time, snapshot}."""

    camera: str
    label: IncidentLabel
    severity: Severity
    score: float
    ts: float
    sub_label: str | None = None
    snapshot: str | None = None
    track_id: int | None = None
    frigate_event_id: str | None = None

    def to_dict(self) -> dict:
        """Khớp đúng tên cột bảng incidents trong schemas/incidents.sql."""
        return {
            "camera": self.camera,
            "label": self.label.value,
            "sub_label": self.sub_label,
            "severity": self.severity.value,
            "score": self.score,
            "ts": self.ts,
            "snapshot": self.snapshot,
            "track_id": self.track_id,
            "frigate_event_id": self.frigate_event_id,
        }

    @staticmethod
    def from_dict(d: dict) -> Incident:
        return Incident(
            camera=d["camera"],
            label=IncidentLabel(d["label"]),
            severity=Severity(d["severity"]),
            score=float(d["score"]),
            ts=float(d["ts"]),
            sub_label=d.get("sub_label"),
            snapshot=d.get("snapshot"),
            track_id=d.get("track_id"),
            frigate_event_id=d.get("frigate_event_id"),
        )

    @property
    def frigate_path(self) -> str:
        return f"/events/{self.camera}/{self.label.value}/create"

    def to_frigate_payload(self, duration: int = 20) -> dict:
        return {
            "sub_label": self.sub_label,
            "score": self.score,
            "duration": duration,
            "include_recording": True,
        }
