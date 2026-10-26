from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mss
import cv2
import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class _ScreenMapping:
    logical: QRect
    physical: dict[str, Any]


class ScreenCoordinateMapper:
    """Maps Qt's per-screen logical coordinates to MSS physical desktop pixels."""

    def __init__(
        self,
        screens: list[tuple[QRect, float]],
        monitors: list[dict[str, Any]],
    ) -> None:
        self.virtual_bounds = dict(monitors[0])
        physical_monitors = monitors[1:]
        available = list(enumerate(physical_monitors))
        mappings: list[_ScreenMapping] = []

        for logical, device_pixel_ratio in screens:
            if not available:
                break
            best_index, best_monitor = min(
                available,
                key=lambda entry: self._dimension_score(
                    logical, device_pixel_ratio, entry[1]
                ),
            )
            available = [entry for entry in available if entry[0] != best_index]
            mappings.append(_ScreenMapping(logical, best_monitor))
        self._mappings = mappings

    @classmethod
    def from_desktop(cls) -> ScreenCoordinateMapper:
        screens = [
            (screen.geometry(), screen.devicePixelRatio())
            for screen in QGuiApplication.screens()
        ]
        with mss.mss() as capture:
            monitors = [dict(monitor) for monitor in capture.monitors]
        if len(monitors) < 2:
            raise RuntimeError("No desktop monitor is available for coordinate mapping.")
        return cls(screens, monitors)

    @staticmethod
    def _dimension_score(
        logical: QRect,
        device_pixel_ratio: float,
        physical: dict[str, Any],
    ) -> float:
        scale_x = physical["width"] / max(1, logical.width())
        scale_y = physical["height"] / max(1, logical.height())
        return abs(scale_x - scale_y) + abs(scale_x - device_pixel_ratio) + abs(
            scale_y - device_pixel_ratio
        )

    @property
    def logical_bounds(self) -> QRect:
        if not self._mappings:
            return QRect()
        bounds = QRect(self._mappings[0].logical)
        for mapping in self._mappings[1:]:
            bounds = bounds.united(mapping.logical)
        return bounds

    def map_point(self, x: int, y: int) -> tuple[int, int]:
        mapping = self._mapping_for_point(x, y)
        logical = mapping.logical
        physical = mapping.physical
        px = physical["left"] + round(
            (x - logical.x())
            * max(0, physical["width"] - 1)
            / max(1, logical.width() - 1)
        )
        py = physical["top"] + round(
            (y - logical.y())
            * max(0, physical["height"] - 1)
            / max(1, logical.height() - 1)
        )
        return px, py

    def contains_logical_point(self, x: int, y: int) -> bool:
        return any(mapping.logical.contains(x, y) for mapping in self._mappings)

    def logical_point_for_screen(self, x: int, y: int) -> tuple[int, int] | None:
        for mapping in self._mappings:
            logical = mapping.logical
            physical = mapping.physical
            if (
                physical["left"] <= x < physical["left"] + physical["width"]
                and physical["top"] <= y < physical["top"] + physical["height"]
            ):
                logical_x = logical.x() + round(
                    (x - physical["left"])
                    * max(0, logical.width() - 1)
                    / max(1, physical["width"] - 1)
                )
                logical_y = logical.y() + round(
                    (y - physical["top"])
                    * max(0, logical.height() - 1)
                    / max(1, physical["height"] - 1)
                )
                return logical_x, logical_y
        return None

    def map_rect(self, logical_rect: QRect) -> tuple[int, int, int, int]:
        rect = logical_rect.normalized()
        if rect.width() <= 0 or rect.height() <= 0:
            raise ValueError("Select a region larger than zero pixels.")
        left, top = self.map_point(rect.left(), rect.top())
        right, bottom = self.map_point(rect.right(), rect.bottom())
        physical_rect = (
            min(left, right),
            min(top, bottom),
            abs(right - left) + 1,
            abs(bottom - top) + 1,
        )
        clipped = clip_physical_rect(physical_rect, self.virtual_bounds)
        if clipped is None:
            raise ValueError("The selected region is outside the captured desktop.")
        return clipped

    def _mapping_for_point(self, x: int, y: int) -> _ScreenMapping:
        for mapping in self._mappings:
            if mapping.logical.contains(x, y):
                return mapping
        if not self._mappings:
            raise RuntimeError("No display coordinate mapping is available.")
        return min(
            self._mappings,
            key=lambda mapping: _distance_to_rect(x, y, mapping.logical),
        )


def clip_physical_rect(
    rect: tuple[int, int, int, int],
    bounds: dict[str, Any],
) -> tuple[int, int, int, int] | None:
    x, y, width, height = rect
    left = max(x, bounds["left"])
    top = max(y, bounds["top"])
    right = min(x + width, bounds["left"] + bounds["width"])
    bottom = min(y + height, bounds["top"] + bounds["height"])
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def frame_relative_region(
    screen_rect: tuple[int, int, int, int],
    frame_origin: tuple[int, int],
    frame_shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    x, y, width, height = screen_rect
    frame_height, frame_width = frame_shape
    relative = (x - frame_origin[0], y - frame_origin[1], width, height)
    clipped = clip_physical_rect(
        relative,
        {"left": 0, "top": 0, "width": frame_width, "height": frame_height},
    )
    if clipped is None:
        raise ValueError("The selected region is outside the captured screen.")
    return clipped


def capture_screen_region(
    screen_rect: tuple[int, int, int, int],
) -> np.ndarray:
    x, y, width, height = screen_rect
    if width <= 0 or height <= 0:
        raise ValueError("The selected capture region must have a positive size.")
    with mss.mss() as capture:
        frame = np.asarray(
            capture.grab({"left": x, "top": y, "width": width, "height": height})
        )
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def _distance_to_rect(x: int, y: int, rect: QRect) -> float:
    dx = max(rect.left() - x, 0, x - rect.right())
    dy = max(rect.top() - y, 0, y - rect.bottom())
    return dx * dx + dy * dy
