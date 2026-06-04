"""
OpenGL equirectangular 360 viewer.

Mouse drag: yaw/pitch pan  |  Scroll wheel: zoom (FOV)
Gesture input: apply_look_delta(dyaw, dpitch) for hand-driven pan/tilt.
"""
from __future__ import annotations

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_COLOR_BUFFER_BIT, GL_FLOAT,
    GL_LINEAR, GL_RGB, GL_STATIC_DRAW, GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TRIANGLE_FAN,
    GL_UNPACK_ALIGNMENT, GL_UNSIGNED_BYTE,
    glBindBuffer, glBindTexture, glBufferData, glClear, glClearColor,
    glDisableVertexAttribArray, glDrawArrays, glEnableVertexAttribArray,
    glGenBuffers, glGenTextures, glPixelStorei, glTexImage2D,
    glTexParameteri, glTexSubImage2D, glUseProgram,
    glVertexAttribPointer, glViewport,
)
from OpenGL.GL.shaders import compileProgram, compileShader
from PySide6.QtCore import QPointF, QTimer, Qt, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from gs_core.gs_qt.gs_ffmpeg import GsVideoStream

_VERT = """
#version 330
layout(location = 0) in vec2 pos;
out vec2 uv;
void main() {
    uv = pos * 0.5 + 0.5;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_FRAG = """
#version 130
uniform sampler2D tex;
uniform float aspect;
uniform vec2 resolution;
uniform float fov;
uniform float yaw;
uniform float pitch;

void main()
{
    vec2 uv = gl_FragCoord.xy / resolution;
    uv = uv * 2.0 - 1.0;
    uv.x *= aspect;

    float fov_rad = radians(fov);
    float z = 1.0 / tan(fov_rad * 0.5);
    vec3 dir = normalize(vec3(uv.x, uv.y, -z));

    float yaw_rad   = radians(yaw);
    float pitch_rad = radians(pitch);

    mat3 rotY = mat3(
         cos(yaw_rad), 0.0, sin(yaw_rad),
         0.0,          1.0, 0.0,
        -sin(yaw_rad), 0.0, cos(yaw_rad)
    );
    mat3 rotX = mat3(
        1.0, 0.0,             0.0,
        0.0,  cos(pitch_rad), -sin(pitch_rad),
        0.0,  sin(pitch_rad),  cos(pitch_rad)
    );

    dir = rotY * rotX * dir;

    float pi = 3.1415926535;
    float u  = atan(dir.x, -dir.z) / (2.0 * pi) + 0.5;
    float v  = 0.5 - asin(clamp(dir.y, -1.0, 1.0)) / pi;
    u = fract(u);

    gl_FragColor = vec4(texture(tex, vec2(u, v)).rgb, 1.0);
}
"""


class Gs360ViewerWidget(QOpenGLWidget):
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._texture        = None
        self._shader_program = None
        self._vbo            = None
        self._frame_rgb: np.ndarray | None = None
        self._tex_w = self._tex_h = 0
        self._yaw   = 0.0
        self._pitch = 0.0
        self._fov   = 100.0
        self._last_mouse: QPointF | None = None
        self._stream: GsVideoStream | None = None
        self._video_path: str | None = None
        self._scale = 0.5

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(16)
        self._render_timer.timeout.connect(self.update)
        self._render_timer.start()

    # ── Public API ────────────────────────────────────────────────────────
    def set_video_path(self, path: str) -> None:
        self._video_path = path
        self._stop_stream()
        self._frame_rgb = None
        self._tex_w = self._tex_h = 0
        self._stream = GsVideoStream(path, scale=self._scale, parent=self)
        self._stream.frame_rgb_changed.connect(self._on_frame)
        self._stream.error_occurred.connect(self.status_changed.emit)
        self._stream.start()
        self.status_changed.emit(f"Loading: {path}")

    def apply_look_delta(self, dyaw: float, dpitch: float) -> None:
        """Apply a gesture-driven yaw/pitch change (values in degrees)."""
        self._yaw   -= dyaw
        self._pitch -= dpitch
        self._pitch  = max(-85.0, min(85.0, self._pitch))
        self.update()

    def reset_view(self) -> None:
        self._yaw = 0.0
        self._pitch = 0.0
        self._fov = 100.0
        self.update()

    def set_stream_scale(self, scale: float) -> None:
        scale = max(0.01, min(1.0, float(scale)))
        if abs(scale - self._scale) < 1e-6:
            return
        self._scale = scale
        if self._video_path:
            self.set_video_path(self._video_path)

    def stop_stream(self) -> None:
        self._stop_stream()

    # ── OpenGL ────────────────────────────────────────────────────────────
    def initializeGL(self) -> None:
        self._shader_program = compileProgram(
            compileShader(_VERT, 35633),
            compileShader(_FRAG, 35632),
        )
        self._texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)

        verts = np.array([-1, -1, 1, -1, 1, 1, -1, 1], dtype=np.float32)
        self._vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)

    def paintGL(self) -> None:
        glClearColor(0.08, 0.08, 0.1, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        if self._shader_program is None or self._frame_rgb is None:
            return

        frame = self._frame_rgb
        fh, fw = frame.shape[:2]
        glBindTexture(GL_TEXTURE_2D, self._texture)
        if fw != self._tex_w or fh != self._tex_h:
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, fw, fh, 0,
                         GL_RGB, GL_UNSIGNED_BYTE, None)
            self._tex_w, self._tex_h = fw, fh
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, fw, fh,
                        GL_RGB, GL_UNSIGNED_BYTE, frame)

        glViewport(0, 0, self.width(), self.height())
        glUseProgram(self._shader_program)
        self._uni1f("yaw",    self._yaw)
        self._uni1f("pitch",  self._pitch)
        self._uni1f("fov",    self._fov)
        self._uni1f("aspect", self.width() / max(1.0, float(self.height())))
        self._uni2f("resolution", float(self.width()), float(self.height()))
        self._uni1i("tex", 0)

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, False, 0, None)
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4)
        glDisableVertexAttribArray(0)

    # ── Mouse (keep for manual control) ──────────────────────────────────
    def mousePressEvent(self, event) -> None:
        self._last_mouse = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._last_mouse is not None:
            dx = event.position().x() - self._last_mouse.x()
            dy = event.position().y() - self._last_mouse.y()
            self._yaw   -= dx * 0.1
            self._pitch -= dy * 0.1
            self._pitch  = max(-85.0, min(85.0, self._pitch))
            self._last_mouse = event.position()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._last_mouse = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        self._fov -= event.angleDelta().y() * 0.05
        self._fov  = max(30.0, min(120.0, self._fov))
        self.update()
        super().wheelEvent(event)

    def closeEvent(self, event) -> None:
        self._stop_stream()
        super().closeEvent(event)

    # ── Internal ──────────────────────────────────────────────────────────
    def _on_frame(self, frame: np.ndarray) -> None:
        self._frame_rgb = np.ascontiguousarray(frame)
        self.update()

    def _stop_stream(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.wait()
            self._stream = None

    def _uni1f(self, name: str, v: float) -> None:
        from OpenGL.GL import glGetUniformLocation, glUniform1f
        glUniform1f(glGetUniformLocation(self._shader_program, name), v)

    def _uni1i(self, name: str, v: int) -> None:
        from OpenGL.GL import glGetUniformLocation, glUniform1i
        glUniform1i(glGetUniformLocation(self._shader_program, name), v)

    def _uni2f(self, name: str, x: float, y: float) -> None:
        from OpenGL.GL import glGetUniformLocation, glUniform2f
        glUniform2f(glGetUniformLocation(self._shader_program, name), x, y)
