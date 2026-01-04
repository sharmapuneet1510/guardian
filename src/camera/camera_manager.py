from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List, Callable, Any

import numpy as np  # type: ignore

from camera.camera_registry import CameraRegistry, CameraConfig
from camera.camera_worker import CameraWorker, CameraHealth, FrameCallback, HealthCallback


@dataclass
class ManagerSnapshot:
    total: int
    running: int
    degraded: int
    stopped: int
    error: int


class CameraManager:
    """
    Owns workers and provides control plane:
    - start_all_enabled()
    - stop_all()
    - restart(camera_id)
    - get_health(camera_id)
    """

    def __init__(
        self,
        registry_path: Path,
        on_frame: Optional[FrameCallback] = None,
        on_health: Optional[HealthCallback] = None,
    ) -> None:
        self.registry = CameraRegistry(registry_path)

        self.on_frame = on_frame
        self.on_health = on_health

        self._workers: Dict[str, CameraWorker] = {}
        self._health: Dict[str, CameraHealth] = {}
        self._lock = threading.Lock()

    # -------------------------
    # Startup/shutdown
    # -------------------------
    def start_all_enabled(self) -> None:
        cams = self.registry.list(include_disabled=False)
        for cam in cams:
            self.start(cam.id)

    def stop_all(self) -> None:
        ids = list(self._workers.keys())
        for cid in ids:
            self.stop(cid)

    # -------------------------
    # Per-camera controls
    # -------------------------
    def start(self, camera_id: str) -> None:
        cam = self._require_config(camera_id)

        with self._lock:
            if camera_id in self._workers and self._workers[camera_id].is_alive():
                return

            worker = CameraWorker(
                config=cam,
                on_frame=self._wrap_frame_cb(self.on_frame),
                on_health=self._wrap_health_cb(self.on_health),
            )
            self._workers[camera_id] = worker

        worker.start()

    def stop(self, camera_id: str) -> None:
        with self._lock:
            worker = self._workers.get(camera_id)

        if worker:
            worker.stop(timeout=2.0)

        with self._lock:
            self._workers.pop(camera_id, None)

    def restart(self, camera_id: str) -> None:
        with self._lock:
            worker = self._workers.get(camera_id)

        if worker:
            worker.restart()
            return

        # if worker didn't exist, just start it
        self.start(camera_id)

    def reload_registry(self) -> None:
        """
        Reload camera configs from disk. Does not auto-stop running workers.
        Use apply_registry_state() to reconcile desired vs actual.
        """
        self.registry.load()

    def apply_registry_state(self) -> None:
        """
        Reconcile running workers with registry 'enabled' flags.
        - start missing enabled cameras
        - stop disabled cameras
        """
        enabled = {c.id for c in self.registry.list(include_disabled=False)}
        all_known = {c.id for c in self.registry.list(include_disabled=True)}

        with self._lock:
            running = set(self._workers.keys())

        # stop cameras that are now disabled or removed
        for cid in list(running):
            if cid not in enabled:
                self.stop(cid)

        # start enabled cameras that are not running
        for cid in enabled:
            with self._lock:
                alive = cid in self._workers and self._workers[cid].is_alive()
            if not alive:
                self.start(cid)

        # cleanup health for deleted cameras (optional)
        with self._lock:
            for cid in list(self._health.keys()):
                if cid not in all_known:
                    self._health.pop(cid, None)

    # -------------------------
    # Health / status
    # -------------------------
    def get_health(self, camera_id: str) -> Optional[CameraHealth]:
        with self._lock:
            return self._health.get(camera_id)

    def list_health(self) -> List[CameraHealth]:
        with self._lock:
            return list(self._health.values())

    def snapshot(self) -> ManagerSnapshot:
        hs = self.list_health()
        total = len(hs)
        running = sum(1 for h in hs if h.state == "RUNNING")
        degraded = sum(1 for h in hs if h.state == "DEGRADED")
        stopped = sum(1 for h in hs if h.state == "STOPPED")
        error = sum(1 for h in hs if h.state == "ERROR")
        return ManagerSnapshot(total, running, degraded, stopped, error)

    # -------------------------
    # Internals
    # -------------------------
    def _require_config(self, camera_id: str) -> CameraConfig:
        cam = self.registry.get(camera_id)
        if not cam:
            raise RuntimeError(f"Camera not found in registry: {camera_id}")
        return cam

    def _wrap_frame_cb(self, cb: Optional[FrameCallback]) -> Optional[FrameCallback]:
        if cb is None:
            return None

        def _inner(camera_id: str, frame: np.ndarray, meta: Dict[str, Any]) -> None:
            cb(camera_id, frame, meta)

        return _inner

    def _wrap_health_cb(self, cb: Optional[HealthCallback]) -> HealthCallback:
        def _inner(h: CameraHealth) -> None:
            with self._lock:
                self._health[h.camera_id] = h
            if cb:
                cb(h)

        return _inner