"""FFmpeg-based video streaming thread for 360 video playback."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal


def gs_ffmpeg_path() -> Path:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return Path(system_ffmpeg)
    for candidate in [
        Path.home() / "miniconda3" / "bin" / "ffmpeg",
        Path.home() / "anaconda3" / "bin" / "ffmpeg",
        Path("/usr/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("ffmpeg not found — install it or add it to PATH")


def gs_video_resolution(video_path: str | Path) -> tuple[int, int]:
    try:
        ffmpeg = gs_ffmpeg_path()
    except FileNotFoundError:
        return 0, 0
    result = subprocess.run(
        [str(ffmpeg), "-i", str(video_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    match = re.search(r"(\d{2,5})x(\d{2,5})", result.stderr)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


class GsVideoStream(QThread):
    frame_rgb_changed = Signal(object)   # np.ndarray (H, W, 3) uint8 RGB
    error_occurred    = Signal(str)

    def __init__(self, video_path: str | Path, scale: float = 0.5, parent=None):
        super().__init__(parent)
        self._video_path    = Path(video_path)
        self._scale         = max(0.01, min(1.0, float(scale)))
        self._process: subprocess.Popen | None = None
        self._running       = False
        self._source_width, self._source_height = gs_video_resolution(self._video_path)

    # ------------------------------------------------------------------
    def run(self) -> None:
        self._running = True
        while self._running:
            if not self._stream_once():
                break
        self.stop()

    def _stream_once(self) -> bool:
        try:
            ffmpeg = gs_ffmpeg_path()
        except FileNotFoundError as exc:
            self.error_occurred.emit(str(exc))
            return False
        if not self._video_path.exists():
            self.error_occurred.emit(f"Video not found: {self._video_path}")
            return False
        if self._source_width <= 0 or self._source_height <= 0:
            self.error_occurred.emit(f"Cannot read resolution: {self._video_path.name}")
            return False

        out_w = max(1, int(self._source_width  * self._scale))
        out_h = max(1, int(self._source_height * self._scale))
        frame_bytes = out_w * out_h * 3

        cmd = [str(ffmpeg), "-i", str(self._video_path)]
        if self._scale != 1.0:
            cmd += ["-vf", f"scale={out_w}:{out_h}"]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.error_occurred.emit(str(exc))
            return False

        stdout = self._process.stdout
        while self._running and stdout is not None:
            raw = stdout.read(frame_bytes)
            if len(raw) != frame_bytes:
                break
            frame = np.frombuffer(raw, np.uint8).reshape((out_h, out_w, 3)).copy()
            self.frame_rgb_changed.emit(frame)

        self._cleanup_process()
        return self._running

    def stop(self) -> None:
        self._running = False
        self._cleanup_process()

    def _cleanup_process(self) -> None:
        if self._process is None:
            return
        try:
            if self._process.stdout:
                self._process.stdout.close()
        except OSError:
            pass
        try:
            self._process.terminate()
            self._process.wait(timeout=2)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None

    def source_width(self)  -> int: return self._source_width
    def source_height(self) -> int: return self._source_height
    def output_width(self)  -> int: return max(1, int(self._source_width  * self._scale))
    def output_height(self) -> int: return max(1, int(self._source_height * self._scale))
