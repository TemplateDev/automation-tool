from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from visual_macro.models import validate_action


class MacroExecutor:
    def __init__(
        self,
        simulation: bool,
        log: Callable[[str], None],
        stop_event: threading.Event | None = None,
        image_check: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.simulation = simulation
        self.log = log
        self.stop_event = stop_event or threading.Event()
        self.image_check = image_check

    def execute(
        self,
        actions: list[dict[str, Any]],
        detection_rect: tuple[int, int, int, int] | None = None,
    ) -> None:
        self._validate_sequence(actions, detection_rect)
        held_keys: set[str] = set()
        try:
            self._execute_sequence(actions, detection_rect, held_keys)
        finally:
            if not self.simulation and held_keys:
                import pyautogui

                for key in held_keys:
                    try:
                        pyautogui.keyUp(key.casefold())
                    except Exception as exc:
                        self.log(f"ERROR: Could not release held key {key!r}: {exc}")

    def _validate_sequence(
        self,
        actions: list[dict[str, Any]],
        detection_rect: tuple[int, int, int, int] | None,
    ) -> None:
        if not isinstance(actions, list):
            raise ValueError("A macro action sequence must be a list.")
        for action in actions:
            validate_action(action)
            if action["type"] in {"click_center", "click_offset"}:
                self.click_position(action, detection_rect)
            if action["type"] in {"wait_image", "if_image"} and self.image_check is None:
                raise ValueError(
                    f"Action '{action['type']}' requires an image recognition callback."
                )
            if action["type"] == "repeat":
                self._validate_sequence(action["actions"], detection_rect)
            elif action["type"] == "if_image":
                self._validate_sequence(action["then_actions"], detection_rect)
                self._validate_sequence(action["else_actions"], detection_rect)

    def _execute_sequence(
        self,
        actions: list[dict[str, Any]],
        detection_rect: tuple[int, int, int, int] | None,
        held_keys: set[str],
    ) -> None:
        for action in actions:
            if self.stop_event.is_set():
                return
            validate_action(action)
            if action["type"] == "wait_image":
                description = (
                    f"wait until image {action['condition']} "
                    f"({action['template_path']})"
                )
                self.log(f"{'SIMULATION: ' if self.simulation else ''}{description}")
                matched = self._wait_for_image(action, expected=action["condition"] == "appears")
                if self.stop_event.is_set():
                    return
                if not matched:
                    raise TimeoutError(
                        f"Timed out waiting for image to {action['condition']}: "
                        f"{action['template_path']}"
                    )
                self.log(f"Image condition satisfied: {action['condition']}.")
                continue
            if action["type"] == "if_image":
                description = self._describe(action)
                self.log(f"{'SIMULATION: ' if self.simulation else ''}{description}")
                matched = self._wait_for_image(action, expected=True)
                if self.stop_event.is_set():
                    return
                branch_name = "then" if matched else "else"
                self.log(f"Image condition {'matched' if matched else 'timed out'}; running {branch_name} branch.")
                branch = action["then_actions"] if matched else action["else_actions"]
                self._execute_sequence(branch, detection_rect, held_keys)
                continue
            if action["type"] == "repeat":
                self.log(f"{'SIMULATION: ' if self.simulation else ''}repeat sequence x{action['count']}")
                for iteration in range(action["count"]):
                    if self.stop_event.is_set():
                        return
                    self.log(f"Sequence iteration {iteration + 1}/{action['count']}")
                    self._execute_sequence(action["actions"], detection_rect, held_keys)
                continue

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
                    if self.stop_event.wait(action["seconds"]):
                        return
                continue

            self.log(f"Executing: {description}")
            if action["type"] == "delay":
                if self.stop_event.wait(action["seconds"]):
                    return
            else:
                self._execute_live(action, click_position, held_keys)

    def _wait_for_image(self, action: dict[str, Any], expected: bool) -> bool:
        if self.image_check is None:
            raise ValueError(f"Action '{action['type']}' requires an image recognition callback.")
        deadline = time.monotonic() + action["timeout"]
        while not self.stop_event.is_set():
            matched = self.image_check(action)
            if not isinstance(matched, bool):
                raise ValueError("Image recognition callback must return a boolean result.")
            if matched == expected:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self.stop_event.wait(min(action.get("interval", 0.25), remaining)):
                return False
        return False

    @staticmethod
    def _execute_live(
        action: dict[str, Any],
        click_position: tuple[int, int] | None,
        held_keys: set[str],
    ) -> None:
        import pyautogui

        kind = action["type"]
        if kind == "click":
            pyautogui.click(
                x=action["x"],
                y=action["y"],
                button=action.get("button", "left"),
                clicks=action.get("clicks", 1),
            )
        elif kind in {"click_center", "click_offset"}:
            pyautogui.click(
                x=click_position[0],
                y=click_position[1],
                button=action.get("button", "left"),
                clicks=action.get("clicks", 1),
            )
        elif kind == "move":
            pyautogui.moveTo(x=action["x"], y=action["y"])
        elif kind == "scroll":
            scroll = pyautogui.scroll if action["direction"] == "vertical" else pyautogui.hscroll
            scroll(action["amount"])
        elif kind == "press":
            pyautogui.press(action["key"].casefold())
        elif kind == "type_text":
            text_buffer: list[str] = []
            for character in action["text"]:
                if character in "\n\t":
                    if text_buffer:
                        pyautogui.write("".join(text_buffer))
                        text_buffer.clear()
                    pyautogui.press("enter" if character == "\n" else "tab")
                else:
                    text_buffer.append(character)
            if text_buffer:
                pyautogui.write("".join(text_buffer))
        elif kind == "hotkey":
            pyautogui.hotkey(*(key.casefold() for key in action["keys"]))
        elif kind == "key_down":
            pyautogui.keyDown(action["key"].casefold())
            held_keys.add(action["key"])
        elif kind == "key_up":
            pyautogui.keyUp(action["key"].casefold())
            held_keys.discard(action["key"])

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
        if action["type"] == "key_down":
            return f"hold key {action['key']}"
        if action["type"] == "key_up":
            return f"release key {action['key']}"
        if action["type"] == "type_text":
            return f"type text {action['text']!r}"
        if action["type"] == "hotkey":
            return f"press key combination {'+'.join(action['keys'])}"
        if action["type"] == "move":
            return f"move mouse to ({action['x']}, {action['y']})"
        if action["type"] == "scroll":
            return f"scroll {action['direction']} by {action['amount']}"
        if action["type"] == "wait_image":
            return (
                f"wait for image to {action['condition']} "
                f"({action['template_path']}, threshold {action['threshold']:.0%}, "
                f"timeout {action['timeout']}s)"
            )
        if action["type"] == "if_image":
            return (
                f"check image {action['template_path']} "
                f"(threshold {action['threshold']:.0%}, timeout {action['timeout']}s)"
            )
        return f"delay {action['seconds']} seconds"
