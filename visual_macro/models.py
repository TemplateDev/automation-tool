from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when a profile or rule contains invalid configuration."""


@dataclass
class Rule:
    id: str
    name: str
    template_path: str
    threshold: float = 0.8
    region: tuple[int, int, int, int] | None = None
    cooldown: float = 1.0
    repeat: bool = False
    enabled: bool = True
    actions: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.actions is None:
            self.actions = []
        validate_rule(self)


@dataclass
class Profile:
    interval: float = 1.0
    simulation: bool = True
    rules: list[Rule] | None = None

    def __post_init__(self) -> None:
        if self.rules is None:
            self.rules = []
        validate_profile(self)


def validate_action(action: Any) -> None:
    if not isinstance(action, dict):
        raise ConfigurationError("Each macro action must be a JSON object.")

    kind = action.get("type")
    if kind == "click":
        _integer(action.get("x"), "click x coordinate")
        _integer(action.get("y"), "click y coordinate")
        button = action.get("button", "left")
        if not isinstance(button, str) or button not in {"left", "right", "middle"}:
            raise ConfigurationError("Click button must be left, right, or middle.")
        clicks = action.get("clicks", 1)
        if not _is_integer(clicks) or not 1 <= clicks <= 10:
            raise ConfigurationError("Click count must be an integer from 1 to 10.")
    elif kind == "click_center":
        _validate_click_options(action)
    elif kind == "click_offset":
        _integer(action.get("offset_x"), "horizontal click offset")
        _integer(action.get("offset_y"), "vertical click offset")
        _validate_click_options(action)
    elif kind == "press":
        key = action.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ConfigurationError("A press action requires a non-empty key.")
    elif kind == "delay":
        seconds = action.get("seconds")
        if not _is_number(seconds) or not 0 <= seconds <= 300:
            raise ConfigurationError("Delay seconds must be between 0 and 300.")
    else:
        raise ConfigurationError(f"Unsupported macro action type: {kind!r}.")


def _validate_click_options(action: dict[str, Any]) -> None:
    button = action.get("button", "left")
    if not isinstance(button, str) or button not in {"left", "right", "middle"}:
        raise ConfigurationError("Click button must be left, right, or middle.")
    clicks = action.get("clicks", 1)
    if not _is_integer(clicks) or not 1 <= clicks <= 10:
        raise ConfigurationError("Click count must be an integer from 1 to 10.")


def validate_rule(rule: Rule) -> None:
    for field_name in ("id", "name", "template_path"):
        value = getattr(rule, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"Rule {field_name} must be a non-empty string.")

    if not _is_number(rule.threshold) or not 0 <= rule.threshold <= 1:
        raise ConfigurationError("Rule threshold must be between 0 and 1.")
    if not _is_number(rule.cooldown) or rule.cooldown < 0:
        raise ConfigurationError("Rule cooldown must be a non-negative number.")
    if not isinstance(rule.repeat, bool) or not isinstance(rule.enabled, bool):
        raise ConfigurationError("Rule repeat and enabled values must be booleans.")
    if rule.region is not None:
        if (
            not isinstance(rule.region, (tuple, list))
            or len(rule.region) != 4
            or any(not _is_integer(value) for value in rule.region)
        ):
            raise ConfigurationError("Rule region must contain four integers: x, y, width, height.")
        x, y, width, height = rule.region
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ConfigurationError("Rule region coordinates must be non-negative and size positive.")
        rule.region = tuple(rule.region)
    if not isinstance(rule.actions, list):
        raise ConfigurationError("Rule actions must be a list.")
    for action in rule.actions:
        validate_action(action)


def validate_profile(profile: Profile) -> None:
    if not _is_number(profile.interval) or not 0.1 <= profile.interval <= 3600:
        raise ConfigurationError("Capture interval must be between 0.1 and 3600 seconds.")
    if not isinstance(profile.simulation, bool):
        raise ConfigurationError("Simulation mode must be a boolean.")
    if not isinstance(profile.rules, list) or any(not isinstance(rule, Rule) for rule in profile.rules):
        raise ConfigurationError("Profile rules must be a list of rules.")
    identifiers = [rule.id for rule in profile.rules]
    if len(identifiers) != len(set(identifiers)):
        raise ConfigurationError("Rule IDs must be unique.")
    for rule in profile.rules:
        validate_rule(rule)


def rule_from_dict(data: Any, base_dir: Path) -> Rule:
    if not isinstance(data, dict):
        raise ConfigurationError("Each rule must be a JSON object.")
    region = data.get("region")
    if region is not None and not isinstance(region, (list, tuple)):
        raise ConfigurationError("Rule region must be an array or null.")
    template_path = data.get("template_path")
    if not isinstance(template_path, str):
        raise ConfigurationError("Rule template_path must be a string.")
    path = Path(template_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return Rule(
        id=data.get("id"),
        name=data.get("name"),
        template_path=str(path.resolve()),
        threshold=data.get("threshold", 0.8),
        region=tuple(region) if region is not None else None,
        cooldown=data.get("cooldown", 1.0),
        repeat=data.get("repeat", False),
        enabled=data.get("enabled", True),
        actions=data.get("actions", []),
    )


def profile_from_dict(data: Any, base_dir: Path) -> Profile:
    if not isinstance(data, dict):
        raise ConfigurationError("Profile root must be a JSON object.")
    version = data.get("version", 1)
    if type(version) is not int or version != 1:
        raise ConfigurationError(f"Unsupported profile version: {version!r}.")
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ConfigurationError("Profile rules must be an array.")
    return Profile(
        interval=data.get("interval", 1.0),
        simulation=data.get("simulation", True),
        rules=[rule_from_dict(rule, base_dir) for rule in rules],
    )


def load_profile(path: str | Path) -> Profile:
    profile_path = Path(path).expanduser().resolve()
    try:
        with profile_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in profile: {exc}") from exc
    return profile_from_dict(data, profile_path.parent)


def save_profile(profile: Profile, path: str | Path) -> None:
    validate_profile(profile)
    profile_path = Path(path).expanduser().resolve()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "interval": profile.interval,
        "simulation": profile.simulation,
        "rules": [_rule_to_dict(rule, profile_path.parent) for rule in profile.rules],
    }
    temporary_path = profile_path.with_name(profile_path.name + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")
        os.replace(temporary_path, profile_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _rule_to_dict(rule: Rule, base_dir: Path) -> dict[str, Any]:
    data = asdict(rule)
    template = Path(rule.template_path).expanduser()
    if template.is_absolute():
        try:
            data["template_path"] = Path(os.path.relpath(template, base_dir)).as_posix()
        except ValueError:
            data["template_path"] = str(template)
    if rule.region is not None:
        data["region"] = list(rule.region)
    return data


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _integer(value: Any, label: str) -> None:
    if not _is_integer(value):
        raise ConfigurationError(f"{label.capitalize()} must be an integer.")
