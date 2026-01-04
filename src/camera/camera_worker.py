from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Literal, Dict, Any

import cv2  # type: ignore
import numpy as np  # type: ignore

from camera.camera_registry import CameraConfig


WorkerState = Literal["STOPPED", "STARTING", "RUNNING", "DEGRADED", "ERROR"]


@dataclass
class CameraHealth:
    camera_id: str
    state: WorkerState = "STOPPED"
    fps_estimate: float = 0.0
    last_frame_ts: float = 0.0
    last_ok_ts: float = 0.0
    last_error: str = ""
    frames_total: int = 0
    dropped_total: int = 0


FrameCallback = Callable[[str, np.ndarray, Dict[str, Any]], None]
HealthCallback = Callable[[CameraHealth], None]


class CameraWorker:
    """
    One worker per camera.
    - Reads frames from USB index or RTSP URL.
    - Emits frames via callback.
    - Maintains health/heartbeat.
    - Automatically reconnects on errors (RTSP / transient USB issues).
    """

    def __init__(
        self,
        config: CameraConfig,
        on_frame: Optional[FrameCallback] = None,
        on_health: Optional[HealthCallback] = None,
        reconnect_backoff_sec: float = 1.5,
        max_backoff_sec: float = 20.0,
    ) -> None:
        self.config = config
        self.on_frame = on_frame
        self.on_health = on_health

        self.reconnect_backoff_sec = reconnect_backoff_sec
        self.max_backoff_sec = max_backoff_sec

        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None

        self.health = CameraHealth(camera_id=config.id)

        # FPS limiting
        self._min_frame_interval = 1.0 / max(1, int(config.fps_limit))
        self._last_emit_ts = 0.0

        # FPS estimate
        self._fps_window_start = time.time()
        self._fps_window_frames = 0

    # -------------------------
    # Lifecycle
    # -------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self.health.state = "STARTING"
        self._notify_health()

        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"CameraWorker[{self.config.id}]",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_evt.set()
        self._release_capture()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self.health.state = "STOPPED"
        self._notify_health()

    def restart(self) -> None:
        self.stop(timeout=2.0)
        # refresh fps limiter from latest config
        self._min_frame_interval = 1.0 / max(1, int(self.config.fps_limit))
        self.start()

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -------------------------
    # Internal: capture open/close
    # -------------------------
    def _open_capture(self) -> bool:
        self._release_capture()

        src: Any
        if self.config.type == "USB":
            src = int(self.config.source)
        else:
            src = self.config.source

        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            self.health.last_error = f"Could not open capture source: {self.config.source}"
            self.health.state = "ERROR"
            self._notify_health()
            return False

        self._cap = cap
        self.health.last_error = ""
        self.health.state = "RUNNING"
        now = time.time()
        self.health.last_ok_ts = now
        self._notify_health()
        return True

    def _release_capture(self) -> None:
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception:
            pass
        self._cap = None

    # -------------------------
    # Run Loop
    # -------------------------
    def _run_loop(self) -> None:
        backoff = self.reconnect_backoff_sec

        # Ensure capture open at least once
        if not self._open_capture():
            # fall through to reconnect loop
            pass

        while not self._stop_evt.is_set():
            if self._cap is None or not self._cap.isOpened():
                # reconnect flow
                self.health.state = "DEGRADED"
                self._notify_health()
                time.sleep(backoff)
                if self._open_capture():
                    backoff = self.reconnect_backoff_sec
                else:
                    backoff = min(self.max_backoff_sec, backoff * 1.6)
                continue

            ok, frame = self._cap.read()
            now = time.time()

            if not ok or frame is None:
                self.health.dropped_total += 1
                self.health.last_error = "Frame read failed"
                self.health.state = "DEGRADED"
                self._notify_health()

                # release and reconnect next loop
                self._release_capture()
                continue

            # FPS limiting (do not overwhelm CPU/UI)
            if (now - self._last_emit_ts) < self._min_frame_interval:
                continue

            self._last_emit_ts = now

            # Health update
            self.health.frames_total += 1
            self.health.last_frame_ts = now
            self.health.last_ok_ts = now
            self.health.state = "RUNNING"

            # FPS estimate window (1s)
            self._fps_window_frames += 1
            if (now - self._fps_window_start) >= 1.0:
                dt = max(1e-6, now - self._fps_window_start)
                self.health.fps_estimate = float(self._fps_window_frames) / dt
                self._fps_window_frames = 0
                self._fps_window_start = now
                self._notify_health()

            # Frame callback
            if self.on_frame:
                meta = {
                    "camera_id": self.config.id,
                    "camera_name": self.config.name,
                    "ts": now,
                }
                try:
                    self.on_frame(self.config.id, frame, meta)
                except Exception as e:
                    # Callback should never crash the worker
                    self.health.last_error = f"on_frame callback error: {e!r}"
                    self._notify_health()

        # Stop cleanup
        self._release_capture()
        self.health.state = "STOPPED"
        self._notify_health()

    def _notify_health(self) -> None:
        if self.on_health:
            try:
                self.on_health(self.health)
            except Exception:
                pass