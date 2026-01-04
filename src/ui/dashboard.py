# ui/dashboard.py
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, List

import numpy as np  # type: ignore

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout, QScrollArea
)

from ui.components.video_tile import VideoTile, TileHealth

# If you already have CameraManager (Issue #4), this import should match your project.
# from camera.camera_manager import CameraManager


@dataclass
class FramePacket:
    ts: float
    frame_bgr: np.ndarray
    meta: Dict[str, Any]


class LatestFrameStore:
    """Thread-safe latest frame per camera (keeps only one)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frames: Dict[str, FramePacket] = {}

    def put(self, camera_id: str, frame_bgr: np.ndarray, meta: Dict[str, Any]) -> None:
        with self._lock:
            self._frames[camera_id] = FramePacket(ts=time.time(), frame_bgr=frame_bgr.copy(), meta=dict(meta))

    def get(self, camera_id: str) -> Optional[FramePacket]:
        with self._lock:
            return self._frames.get(camera_id)

    def ids(self) -> List[str]:
        with self._lock:
            return list(self._frames.keys())


class LatestHealthStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._health: Dict[str, TileHealth] = {}

    def put(self, camera_id: str, state: str, fps: float, last_error: str) -> None:
        with self._lock:
            self._health[camera_id] = TileHealth(
                ts=time.time(),
                state=str(state),
                fps=float(fps),
                last_error=str(last_error or "")
            )

    def get(self, camera_id: str) -> Optional[TileHealth]:
        with self._lock:
            return self._health.get(camera_id)


class Dashboard(QWidget):
    """
    GUARDIAN Dashboard (Phase 1): Multi-Camera Grid
    - UI-only: display frames + camera health
    - CameraManager feeds callbacks: on_frame, on_health
    """

    def __init__(self, columns: int = 2, ui_fps: int = 12) -> None:
        super().__init__()
        self.setWindowTitle("GUARDIAN — Dashboard")

        self.columns = max(1, int(columns))
        self.ui_interval_ms = int(1000 / max(1, int(ui_fps)))

        self.frames = LatestFrameStore()
        self.health = LatestHealthStore()

        self._tiles: Dict[str, VideoTile] = {}
        self._camera_titles: Dict[str, str] = {}

        self._build_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self._render_tick)
        self.timer.start(self.ui_interval_ms)

    # ---- callbacks for CameraManager ----
    def on_frame(self, camera_id: str, frame_bgr: np.ndarray, meta: Dict[str, Any]) -> None:
        title = meta.get("camera_name")
        if isinstance(title, str) and title.strip():
            self._camera_titles[camera_id] = title.strip()
        self.frames.put(camera_id, frame_bgr, meta)

    def on_health(self, h: Any) -> None:
        """
        Accepts either:
        - object with attributes: camera_id, state, fps_estimate, last_error
        - dict: {camera_id, state, fps, last_error}
        """
        try:
            camera_id = getattr(h, "camera_id", None) or h.get("camera_id")
            state = getattr(h, "state", None) or h.get("state", "OFFLINE")

            fps = getattr(h, "fps_estimate", None)
            if fps is None:
                fps = h.get("fps", 0.0)

            last_error = getattr(h, "last_error", None) or h.get("last_error", "")

            if camera_id:
                self.health.put(str(camera_id), str(state), float(fps), str(last_error))
        except Exception:
            return

    # ---- UI ----
    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QWidget { background:#0b1220; color:#e5e7eb; }
            QFrame#top { background:#111c33; border:1px solid #22304f; border-radius:12px; }
            QLabel#left { color:#bbf7d0; font-weight:bold; }
            QLabel#right { color:#93c5fd; }
        """)

        root = QVBoxLayout()
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # top bar
        top = QFrame()
        top.setObjectName("top")
        t = QHBoxLayout()
        t.setContentsMargins(12, 10, 12, 10)

        self.status_left = QLabel("STATUS: OK")
        self.status_left.setObjectName("left")
        self.status_left.setFont(QFont("Arial", 11, QFont.Bold))

        self.status_right = QLabel("Cameras: 0 | Live: 0 | Degraded: 0 | Offline: 0")
        self.status_right.setObjectName("right")
        self.status_right.setFont(QFont("Arial", 10))

        t.addWidget(self.status_left)
        t.addStretch(1)
        t.addWidget(self.status_right)
        top.setLayout(t)

        # grid
        self.grid_container = QWidget()
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid_container.setLayout(self.grid)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.grid_container)

        root.addWidget(top)
        root.addWidget(scroll)
        self.setLayout(root)

        self.resize(1280, 820)

    def _ensure_tile(self, camera_id: str) -> None:
        if camera_id in self._tiles:
            return

        title = self._camera_titles.get(camera_id, camera_id)
        tile = VideoTile(camera_id=camera_id, title=title)
        tile.clicked.connect(self._on_tile_clicked)

        self._tiles[camera_id] = tile
        self._reflow_grid()

    def _reflow_grid(self) -> None:
        # Clear and re-add tiles in stable order
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        ids = sorted(self._tiles.keys(), key=lambda x: (len(x), x))
        for idx, cid in enumerate(ids):
            row = idx // self.columns
            col = idx % self.columns
            self.grid.addWidget(self._tiles[cid], row, col)

    def _render_tick(self) -> None:
        cam_ids = set(self.frames.ids()) | set(self._tiles.keys())

        # Ensure tiles exist
        for cid in sorted(cam_ids, key=lambda x: (len(x), x)):
            self._ensure_tile(cid)

            fp = self.frames.get(cid)
            hp = self.health.get(cid)

            # update title if changed
            title = self._camera_titles.get(cid)
            if title:
                self._tiles[cid].set_title(title)

            self._tiles[cid].update_health(hp)
            if fp:
                self._tiles[cid].update_frame(fp.frame_bgr, fp.ts)

        # summary
        live = degraded = offline = 0
        for cid in self._tiles.keys():
            hp = self.health.get(cid)
            s = (hp.state.upper() if hp else "OFFLINE")
            if s == "RUNNING":
                live += 1
            elif s == "DEGRADED":
                degraded += 1
            else:
                offline += 1

        total = len(self._tiles)
        self.status_right.setText(f"Cameras: {total} | Live: {live} | Degraded: {degraded} | Offline: {offline}")

        if offline > 0:
            self.status_left.setText("STATUS: ATTENTION")
            self.status_left.setStyleSheet("color:#fde68a; font-weight:bold;")
        else:
            self.status_left.setText("STATUS: OK")
            self.status_left.setStyleSheet("color:#bbf7d0; font-weight:bold;")

    def _on_tile_clicked(self, camera_id: str) -> None:
        # Architecture hook: later open Focus View / Incidents / Person timeline
        self.status_right.setText(self.status_right.text() + f" | Focus: {camera_id}")


# Optional quick-run (wire this in your main.py instead for real use)
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    # from camera.camera_manager import CameraManager

    app = QApplication(sys.argv)
    dash = Dashboard(columns=2, ui_fps=12)

    # Example wiring (adjust to your CameraManager signature)
    # mgr = CameraManager(Path("config/cameras.json"), on_frame=dash.on_frame, on_health=dash.on_health)
    # mgr.start_all_enabled()

    dash.show()
    sys.exit(app.exec_())