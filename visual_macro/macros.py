from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from visual_macro.models import validate_action


class MacroExecutor:
    def __init__(
        self,
        simulation: bool,
        log: Callable[[str], None],
        stop_event: threading.Event | None = None,
    ) -> None:
        self.simulation = simulation
        self.log = log
        self.stop_event = stop_event or threading.Event()

    def execute(
        self,
        actions: list[dict[str, Any]],
        detection_rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        for action in actions:
            validate_action(action)
            if self.stop_event.is_set():
                return
            if action["type"] in {"click_center", "click_offset"} and detection_rect is None:
                raise ValueError(
                    f"Action '{action['type']}' requires a detected image position, "
                    "but no detection rectangle was provided."
                )
            click_position = (
                self.click_position(action, detection_rect)
                if action["type"] in {"click_center", "click_offset"}
                else None
            )
            description = self._describe(action, click_position)
            if self.simulation:
                self.log(f"SIMULATION: {description}")
                if action["type"] == "delay":
                    self.stop_event.wait(action["seconds"])
                continue

            self.log(f"Executing: {description}")
            if action["type"] == "delay":
                if self.stop_event.wait(action["seconds"]):
                    return
            elif action["type"] == "click":
                import pyautogui

                pyautogui.click(
                    x=action["x"],
                    y=action["y"],
                    button=action.get("button", "left"),
                    clicks=action.get("clicks", 1),
                )
            elif action["type"] in {"click_center", "click_offset"}:
                import pyautogui

                pyautogui.click(
                    x=click_position[0],
                    y=click_position[1],
                    button=action.get("button", "left"),
                    clicks=action.get("clicks", 1),
                )
            elif action["type"] == "press":
                import pyautogui

                pyautogui.press(action["key"])

    @staticmethod
    def click_position(
        action: dict[str, Any],
        detection_rect: tuple[int, int, int, int] | None,
    ) -> tuple[int, int]:
        if detection_rect is None:
            raise ValueError(
                f"Action '{action['type']}' requires a detected image position, "
                "but no detection rectangle was provided."
            )
        if not isinstance(detection_rect, (tuple, list)) or len(detection_rect) != 4:
            raise ValueError(
                f"Action '{action['type']}' requires a valid detected image rectangle; "
                f"received {detection_rect!r}."
            )
        x, y, width, height = detection_rect
        if (
            any(not isinstance(value, int) or isinstance(value, bool) for value in detection_rect)
            or width <= 0
            or height <= 0
        ):
            raise ValueError(
                f"Action '{action['type']}' requires a valid detected image rectangle; "
                f"received {detection_rect!r}."
            )
        center_x = x + width // 2
        center_y = y + height // 2
        if action["type"] == "click_offset":
            center_x += action["offset_x"]
            center_y += action["offset_y"]
        return center_x, center_y

    @staticmethod
    def _describe(
        action: dict[str, Any],
        click_position: tuple[int, int] | None = None,
    ) -> str:
        if action["type"] == "click":
            button = action.get("button", "left")
            clicks = action.get("clicks", 1)
            return f"click {button} at ({action['x']}, {action['y']}) x{clicks}"
        if action["type"] in {"click_center", "click_offset"}:
            button = action.get("button", "left")
            clicks = action.get("clicks", 1)
            kind = "image center" if action["type"] == "click_center" else "image center with offset"
            return f"click {button} at {kind} ({click_position[0]}, {click_position[1]}) x{clicks}"
        if action["type"] == "press":
            return f"press key {action['key']}"
        return f"delay {action['seconds']} seconds"
