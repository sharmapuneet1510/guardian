# ui/components/video_tile.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import cv2  # type: ignore
import numpy as np  # type: ignore

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy


@dataclass
class TileHealth:
    ts: float
    state: str         # RUNNING / DEGRADED / OFFLINE / ERROR
    fps: float
    last_error: str


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):  # type: ignore
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class VideoTile(QWidget):
    """
    GUARDIAN UI component (per-camera tile):
    - Title + LIVE/DEGRADED/OFFLINE badge
    - Health line (fps, last error snippet)
    - Latest frame preview
    """

    clicked = pyqtSignal(str)  # camera_id

    def __init__(self, camera_id: str, title: str) -> None:
        super().__init__()
        self.camera_id = camera_id
        self._title_text = title

        self._last_frame_ts = 0.0
        self._health: Optional[TileHealth] = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QFrame#tile { background:#0f1a2e; border:1px solid #22304f; border-radius:12px; }
            QLabel#title { color:#e5e7eb; font-weight:bold; }
            QLabel#meta { color:#9ca3af; }
            QLabel#badge { padding:2px 10px; border-radius:10px; font-weight:bold; }
            QLabel#img { background:#0b1220; border-radius:10px; }
        """)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tile = ClickableFrame()
        self.tile.setObjectName("tile")
        self.tile.clicked.connect(lambda: self.clicked.emit(self.camera_id))

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        self.title = QLabel(self._title_text)
        self.title.setObjectName("title")
        self.title.setFont(QFont("Arial", 11, QFont.Bold))

        self.badge = QLabel("OFFLINE")
        self.badge.setObjectName("badge")
        self._set_badge("OFFLINE")

        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.badge)

        self.meta = QLabel("fps: - | last: -")
        self.meta.setObjectName("meta")
        self.meta.setFont(QFont("Arial", 9))

        self.img = QLabel("No frames yet")
        self.img.setObjectName("img")
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setMinimumHeight(220)
        self.img.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout.addLayout(header)
        layout.addWidget(self.meta)
        layout.addWidget(self.img)

        self.tile.setLayout(layout)
        root.addWidget(self.tile)
        self.setLayout(root)

    def set_title(self, title: str) -> None:
        title = (title or "").strip()
        if title and self.title.text() != title:
            self.title.setText(title)

    def _set_badge(self, state: str) -> None:
        s = (state or "").upper()
        if s == "RUNNING":
            self.badge.setText("LIVE")
            self.badge.setStyleSheet("background:#0b3d2e; color:#bbf7d0;")
        elif s == "DEGRADED":
            self.badge.setText("DEGRADED")
            self.badge.setStyleSheet("background:#3b2f0b; color:#fde68a;")
        elif s == "ERROR":
            self.badge.setText("ERROR")
            self.badge.setStyleSheet("background:#3b0b0f; color:#fecaca;")
        else:
            self.badge.setText("OFFLINE")
            self.badge.setStyleSheet("background:#111c33; color:#93c5fd;")

    def update_health(self, hp: Optional[TileHealth]) -> None:
        self._health = hp
        if not hp:
            self._set_badge("OFFLINE")
            self.meta.setText("fps: - | last: -")
            return

        self._set_badge(hp.state)
        age = time.time() - hp.ts
        err = hp.last_error.strip()
        err_part = f" | err: {err[:40]}..." if err else ""
        self.meta.setText(f"fps: {hp.fps:.1f} | health_age: {age:.1f}s{err_part}")

    def update_frame(self, frame_bgr: np.ndarray, ts: float) -> None:
        self._last_frame_ts = ts

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)

        # Scale to current widget size
        self.img.setPixmap(pix.scaled(self.img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))