from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal


CameraType = Literal["USB", "RTSP"]
RecordingMode = Literal["OFF", "EVENTS_ONLY", "CONTINUOUS", "MANUAL"]


def _now_iso() -> str:
    # Avoid adding dependencies; good enough for local logs.
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class DetectConfig:
    yolo_every_n: int = 8
    pose_every_n: int = 2
    emotion_every_n: int = 14
    min_face_px: int = 80


@dataclass
class PrivacyConfig:
    blur_faces: bool = False
    blur_zones: List[Dict[str, Any]] = field(default_factory=list)  # e.g. rectangles/polygons


@dataclass
class RecordingConfig:
    mode: RecordingMode = "OFF"
    retention_days: int = 7


@dataclass
class CameraConfig:
    id: str
    name: str
    type: CameraType
    source: str  # "0" for USB; "rtsp://..." for RTSP
    enabled: bool = True

    fps_limit: int = 20

    detect: DetectConfig = field(default_factory=DetectConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)

    zones: List[Dict[str, Any]] = field(default_factory=list)

    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


class CameraRegistryError(RuntimeError):
    pass


class CameraRegistry:
    """
    Persistent, config-driven camera registry for GUARDIAN.

    Stores camera configs in JSON:
      config/cameras.json
    """

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self.version: int = 1
        self._cameras: Dict[str, CameraConfig] = {}

        self.load()

    # -------------------------
    # Public APIs
    # -------------------------
    def list(self, include_disabled: bool = True) -> List[CameraConfig]:
        cams = list(self._cameras.values())
        if include_disabled:
            return sorted(cams, key=lambda c: c.id)
        return sorted([c for c in cams if c.enabled], key=lambda c: c.id)

    def get(self, camera_id: str) -> Optional[CameraConfig]:
        return self._cameras.get(camera_id)

    def add(self, camera: CameraConfig) -> CameraConfig:
        if camera.id in self._cameras:
            raise CameraRegistryError(f"Camera id already exists: {camera.id}")
        self._validate(camera)
        camera.created_at = _now_iso()
        camera.updated_at = camera.created_at
        self._cameras[camera.id] = camera
        self.save()
        return camera

    def update(self, camera_id: str, patch: Dict[str, Any]) -> CameraConfig:
        cam = self._require(camera_id)

        # Apply patch shallowly + nested for detect/privacy/recording
        updated = self._apply_patch(cam, patch)
        updated.updated_at = _now_iso()

        self._validate(updated)
        self._cameras[camera_id] = updated
        self.save()
        return updated

    def enable(self, camera_id: str) -> CameraConfig:
        return self.update(camera_id, {"enabled": True})

    def disable(self, camera_id: str) -> CameraConfig:
        return self.update(camera_id, {"enabled": False})

    def delete(self, camera_id: str) -> None:
        if camera_id in self._cameras:
            del self._cameras[camera_id]
            self.save()

    def generate_id(self) -> str:
        # cam_1, cam_2, ...
        used = set(self._cameras.keys())
        i = 1
        while True:
            cid = f"cam_{i}"
            if cid not in used:
                return cid
            i += 1

    # -------------------------
    # Persistence
    # -------------------------
    def load(self) -> None:
        if not self.config_path.exists():
            self._cameras = {}
            self._write_default_file()
            return

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise CameraRegistryError(f"Failed to read {self.config_path}: {e!r}")

        self.version = int(data.get("version", 1))
        cams = data.get("cameras", [])
        self._cameras = {}

        for raw in cams:
            cam = self._from_dict(raw)
            # validate but don't crash whole load if one bad entry; skip it
            try:
                self._validate(cam)
                self._cameras[cam.id] = cam
            except Exception:
                # You can choose to raise instead. For now, skip invalid entry.
                continue

    def save(self) -> None:
        payload = {
            "version": self.version,
            "cameras": [self._to_dict(c) for c in self.list()],
        }
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.config_path)

    # -------------------------
    # Internals
    # -------------------------
    def _write_default_file(self) -> None:
        payload = {"version": self.version, "cameras": []}
        self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _require(self, camera_id: str) -> CameraConfig:
        cam = self._cameras.get(camera_id)
        if not cam:
            raise CameraRegistryError(f"Camera not found: {camera_id}")
        return cam

    def _to_dict(self, cam: CameraConfig) -> Dict[str, Any]:
        d = asdict(cam)
        # dataclasses -> nested dict ok
        return d

    def _from_dict(self, raw: Dict[str, Any]) -> CameraConfig:
        detect = DetectConfig(**raw.get("detect", {}))
        privacy = PrivacyConfig(**raw.get("privacy", {}))
        recording = RecordingConfig(**raw.get("recording", {}))

        return CameraConfig(
            id=str(raw["id"]),
            name=str(raw.get("name", raw["id"])),
            type=str(raw.get("type", "USB")).upper(),  # normalize
            source=str(raw.get("source", "0")),
            enabled=bool(raw.get("enabled", True)),
            fps_limit=int(raw.get("fps_limit", 20)),
            detect=detect,
            privacy=privacy,
            recording=recording,
            zones=list(raw.get("zones", [])),
            created_at=str(raw.get("created_at", _now_iso())),
            updated_at=str(raw.get("updated_at", _now_iso())),
        )

    def _apply_patch(self, cam: CameraConfig, patch: Dict[str, Any]) -> CameraConfig:
        # Create a copy as dict, apply patches, reconstruct
        base = self._to_dict(cam)

        for k, v in patch.items():
            if k in ("detect", "privacy", "recording") and isinstance(v, dict):
                base[k] = {**base.get(k, {}), **v}
            else:
                base[k] = v

        return self._from_dict(base)

    def _validate(self, cam: CameraConfig) -> None:
        # id format
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", cam.id):
            raise CameraRegistryError(f"Invalid camera id: {cam.id}")

        if not cam.name.strip():
            raise CameraRegistryError("Camera name is required")

        ctype = cam.type.upper()
        if ctype not in ("USB", "RTSP"):
            raise CameraRegistryError(f"Invalid camera type: {cam.type}")
        cam.type = ctype  # normalized

        if cam.fps_limit < 1 or cam.fps_limit > 60:
            raise CameraRegistryError("fps_limit must be between 1 and 60")

        # Source validation
        if cam.type == "USB":
            # source should be an integer index in string form: "0", "1"
            if not re.fullmatch(r"\d+", cam.source.strip()):
                raise CameraRegistryError(f"USB camera source must be numeric string. Got: {cam.source}")
        else:  # RTSP
            s = cam.source.strip()
            if not (s.startswith("rtsp://") or s.startswith("rtsps://")):
                raise CameraRegistryError("RTSP source must start with rtsp:// or rtsps://")

        # Detect config sanity
        d = cam.detect
        if d.yolo_every_n < 1 or d.pose_every_n < 1 or d.emotion_every_n < 1:
            raise CameraRegistryError("Detection intervals must be >= 1")
        if d.min_face_px < 40:
            raise CameraRegistryError("min_face_px too small; set >= 40")

        # Recording config
        if cam.recording.mode not in ("OFF", "EVENTS_ONLY", "CONTINUOUS", "MANUAL"):
            raise CameraRegistryError(f"Invalid recording mode: {cam.recording.mode}")
        if cam.recording.retention_days < 0 or cam.recording.retention_days > 365:
            raise CameraRegistryError("retention_days must be 0..365")