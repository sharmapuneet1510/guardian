from pathlib import Path
from camera.camera_registry import CameraRegistry, CameraConfig

reg = CameraRegistry(Path("src/config/cameras.json"))

cam_id = reg.generate_id()
reg.add(CameraConfig(
    id=cam_id,
    name="Entrance",
    type="RTSP",
    source="rtsp://user:pass@192.168.0.20:554/stream1",
    enabled=True
))

print([c.id for c in reg.list()])