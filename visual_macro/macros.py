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

    def execute(self, actions: list[dict[str, Any]]) -> None:
        for action in actions:
            validate_action(action)
            if self.stop_event.is_set():
                return
            description = self._describe(action)
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
            elif action["type"] == "press":
                import pyautogui

                pyautogui.press(action["key"])

    @staticmethod
    def _describe(action: dict[str, Any]) -> str:
        if action["type"] == "click":
            button = action.get("button", "left")
            clicks = action.get("clicks", 1)
            return f"click {button} at ({action['x']}, {action['y']}) x{clicks}"
        if action["type"] == "press":
            return f"press key {action['key']}"
        return f"delay {action['seconds']} seconds"
