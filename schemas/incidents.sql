-- Lịch sử sự cố. Module AI ghi, dashboard Streamlit đọc.
-- Tên cột khớp đúng Incident.to_dict() trong safety/contracts.py.

CREATE TABLE IF NOT EXISTS incidents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    camera           TEXT    NOT NULL,
    label            TEXT    NOT NULL,
    sub_label        TEXT,
    severity         TEXT    NOT NULL CHECK (severity IN ('critical', 'high', 'medium')),
    score            REAL    NOT NULL,
    ts               REAL    NOT NULL,
    snapshot         TEXT,
    track_id         INTEGER,
    frigate_event_id TEXT,
    false_alarm      INTEGER NOT NULL DEFAULT 0,
    created_at       REAL    NOT NULL DEFAULT (unixepoch('now'))
);

CREATE INDEX IF NOT EXISTS idx_incidents_ts ON incidents (ts DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_camera_label ON incidents (camera, label);
