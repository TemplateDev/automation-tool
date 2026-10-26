from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np

from visual_macro.models import Rule


@dataclass(frozen=True)
class Detection:
    confidence: float
    location: tuple[int, int] | None
    matched: bool
    bbox: tuple[int, int, int, int] | None = None


class ScreenCapture:
    def __enter__(self) -> ScreenCapture:
        self._capture = mss.mss()
        self._monitor = self._capture.monitors[0]
        self.origin = (self._monitor["left"], self._monitor["top"])
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._capture.close()

    def grab(self) -> np.ndarray:
        frame = np.asarray(self._capture.grab(self._monitor))
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


class TemplateMatcher:
    def __init__(self) -> None:
        self._templates: dict[str, tuple[int, int, np.ndarray]] = {}

    def ensure_template(self, rule: Rule) -> np.ndarray:
        path = Path(rule.template_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Template for rule '{rule.name}' was not found: {path}")
        modified = path.stat().st_mtime_ns
        cached = self._templates.get(str(path.resolve()))
        if cached is not None and cached[0] == modified:
            return cached[2]
        template = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if template is None or template.size == 0:
            raise ValueError(f"Template for rule '{rule.name}' is not a readable image: {path}")
        self._templates[str(path.resolve())] = (modified, template.shape[1], template)
        return template

    def match(
        self,
        frame: np.ndarray,
        rule: Rule,
        screen_origin: tuple[int, int] = (0, 0),
    ) -> Detection:
        template = self.ensure_template(rule)
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Screen frame must be a three-channel BGR image.")
        screen = frame
        offset_x = 0
        offset_y = 0
        if rule.region is not None:
            x, y, width, height = rule.region
            if x + width > screen.shape[1] or y + height > screen.shape[0]:
                raise ValueError(f"Screen region for rule '{rule.name}' extends beyond the captured screen.")
            screen = screen[y : y + height, x : x + width]
            offset_x, offset_y = x, y

        template_height, template_width = template.shape[:2]
        if template_width > screen.shape[1] or template_height > screen.shape[0]:
            raise ValueError(f"Template for rule '{rule.name}' is larger than its search region.")

        if np.all(np.std(template, axis=(0, 1)) == 0):
            scores = cv2.matchTemplate(screen, template, cv2.TM_SQDIFF_NORMED)
            min_score, _, min_location, _ = cv2.minMaxLoc(scores)
            confidence = 1.0 - min_score
            location = min_location
        else:
            scores = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, max_score, _, max_location = cv2.minMaxLoc(scores)
            confidence = max_score
            location = max_location
        confidence = float(np.clip(confidence, 0.0, 1.0))
        matched = confidence >= rule.threshold
        absolute_location = (location[0] + offset_x, location[1] + offset_y) if matched else None
        screen_bbox = (
            (
                location[0] + offset_x + screen_origin[0],
                location[1] + offset_y + screen_origin[1],
                template_width,
                template_height,
            )
            if matched
            else None
        )
        return Detection(
            confidence=confidence,
            location=absolute_location,
            matched=matched,
            bbox=screen_bbox,
        )
