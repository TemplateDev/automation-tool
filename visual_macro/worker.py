from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal

from visual_macro.engine import RuleEngine
from visual_macro.macros import MacroExecutor
from visual_macro.models import Profile, Rule
from visual_macro.recognition import ScreenCapture, TemplateMatcher


class MacroWorker(QThread):
    log_message = Signal(str)
    error_message = Signal(str)

    def __init__(
        self,
        profile: Profile,
        rules: list[Rule] | None = None,
        once: bool = False,
    ) -> None:
        super().__init__()
        self.profile = profile
        self.rules = rules if rules is not None else profile.rules
        self.once = once
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        matcher = TemplateMatcher()
        engine = RuleEngine()
        executor = MacroExecutor(
            simulation=True if self.once else self.profile.simulation,
            log=self.log_message.emit,
            stop_event=self._stop_event,
        )
        try:
            for rule in self.rules:
                if rule.enabled:
                    matcher.ensure_template(rule)
            with ScreenCapture() as capture:
                if self.once:
                    self._run_once(capture, matcher, engine, executor)
                    return
                self.log_message.emit("Monitoring started.")
                while not self._stop_event.is_set():
                    cycle_started = time.monotonic()
                    frame = capture.grab()
                    if self._stop_event.is_set():
                        break
                    detections = self._recognize(
                        frame, matcher, getattr(capture, "origin", (0, 0))
                    )
                    if self._stop_event.is_set():
                        break
                    self._report_results(detections)
                    for rule in engine.evaluate(self.rules, detections, cycle_started):
                        if self._stop_event.is_set():
                            break
                        self.log_message.emit(f"Triggered rule: {rule.name}")
                        detection = detections[rule.id]
                        executor.execute(rule.actions, detection_rect=detection.bbox)
                    remaining = self.profile.interval - (time.monotonic() - cycle_started)
                    if remaining > 0:
                        self._stop_event.wait(remaining)
        except Exception as exc:
            self.error_message.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if not self.once:
                self.log_message.emit("Monitoring stopped.")

    def _run_once(
        self,
        capture: ScreenCapture,
        matcher: TemplateMatcher,
        engine: RuleEngine,
        executor: MacroExecutor,
    ) -> None:
        frame = capture.grab()
        detections = self._recognize(frame, matcher, getattr(capture, "origin", (0, 0)))
        self._report_results(detections, include_absent=True)
        triggered = engine.evaluate(self.rules, detections, time.monotonic())
        if not triggered:
            self.log_message.emit("Test complete: template was not detected; no actions run.")
        for rule in triggered:
            self.log_message.emit(f"Test matched rule: {rule.name}")
            if not rule.actions:
                self.log_message.emit(f"No actions configured for {rule.name}.")
            executor.execute(rule.actions, detection_rect=detections[rule.id].bbox)

    def _recognize(
        self,
        frame,
        matcher: TemplateMatcher,
        screen_origin: tuple[int, int] = (0, 0),
    ):
        return {
            rule.id: matcher.match(frame, rule, screen_origin=screen_origin)
            for rule in self.rules
            if rule.enabled
        }

    def _report_results(self, detections, include_absent: bool = False) -> None:
        for rule in self.rules:
            detection = detections.get(rule.id)
            if detection is not None and detection.matched:
                x, y = detection.bbox[:2] if detection.bbox is not None else detection.location
                self.log_message.emit(
                    f"Recognized {rule.name} at ({x}, {y}), confidence "
                    f"{detection.confidence:.3f}."
                )
            elif include_absent and detection is not None:
                self.log_message.emit(
                    f"No match for {rule.name}; best confidence {detection.confidence:.3f} "
                    f"(threshold {rule.threshold:.3f})."
                )
