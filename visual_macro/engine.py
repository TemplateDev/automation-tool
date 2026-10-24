from __future__ import annotations

from dataclasses import dataclass

from visual_macro.models import Rule
from visual_macro.recognition import Detection


@dataclass
class _RuleState:
    present: bool = False
    last_trigger: float | None = None


class RuleEngine:
    def __init__(self) -> None:
        self._states: dict[str, _RuleState] = {}

    def evaluate(
        self,
        rules: list[Rule],
        detections: dict[str, Detection],
        now: float,
    ) -> list[Rule]:
        triggered: list[Rule] = []
        active_ids = {rule.id for rule in rules if rule.enabled}
        for rule_id in tuple(self._states):
            if rule_id not in active_ids:
                del self._states[rule_id]

        for rule in rules:
            if not rule.enabled:
                continue
            detection = detections.get(rule.id)
            if detection is None:
                raise ValueError(f"Missing recognition result for rule '{rule.name}'.")
            state = self._states.setdefault(rule.id, _RuleState())
            if not detection.matched:
                state.present = False
                continue

            appeared = not state.present
            state.present = True
            should_fire = appeared or rule.repeat
            cooldown_complete = (
                state.last_trigger is None or now - state.last_trigger >= rule.cooldown
            )
            if should_fire and cooldown_complete:
                triggered.append(rule)
                state.last_trigger = now

        return triggered
